from utils.logger import log
"""
sort_slips.py — อ่าน slip + ดึงข้อมูลทั้งหมดในรอบเดียว + แยก folder + เช็คซ้ำ
เรียก Claude API แค่ครั้งเดียวต่อรูป (ประหยัด cost)
"""

import anthropic
import base64
import json
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imagehash
from PIL import Image

from config.config import (
    RAW_MOUNT, DATA_MOUNT, HASH_DB_PATH,
    ANTHROPIC_API_KEY, CLAUDE_MODEL, HASH_THRESHOLD, MONTH_MAP, IMAGE_EXTS
)

# ── Claude Prompt (ดึงทุกอย่างในรอบเดียว) ────────────────────────────────────

SYSTEM_PROMPT = """คุณคือระบบดึงข้อมูลจาก slip โอนเงินธนาคาร
ตอบเฉพาะ JSON เท่านั้น ห้ามมีข้อความอื่น ห้ามมี markdown backticks

รูปแบบ:
{
  "day": <1-31>,
  "month": <1-12>,
  "year_ce": <ปี ค.ศ.>,
  "amount": <จำนวนเงิน ตัวเลขเท่านั้น>,
  "note": "<ข้อความใน Note / บันทึกช่วยจำ / หมายเหตุ ของ slip ถ้าไม่มีให้ใส่ null>",
  "from_account": "<ชื่อผู้โอน หรือ เลขบัญชี>",
  "to_name": "<ชื่อ-นามสกุล ผู้รับเท่านั้น ไม่เอาเลขบัญชี ไม่เอาชื่อธนาคาร ไม่เอาเลข ref>",
  "to_account": "<ข้อมูลผู้รับเต็มๆ รวมเลขบัญชีและธนาคาร>",
  "bank": "<ธนาคาร>",
  "ref": "<เลข reference/transaction ID>"
}
หมายเหตุ:
- to_name คือชื่อ-นามสกุลสะอาดๆ เช่น "นาย วุฒิ กล่ำนคร" หรือ "หจก. ทริปเปิลเอ็น"
- ถ้าไม่พบข้อมูลใดให้ใส่ null
- ถ้าปีเป็น พ.ศ. ให้แปลงเป็น ค.ศ. (พ.ศ. - 543 = ค.ศ.)
- ถ้าหาวันที่ไม่ได้เลยให้ตอบ: {"error": "date not found"}"""

# ── Hash DB ───────────────────────────────────────────────────────────────────

def load_hash_db() -> dict:
    p = Path(HASH_DB_PATH)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_hash_db(db: dict):
    Path(HASH_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(HASH_DB_PATH).write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_phash(path: Path) -> str | None:
    try:
        return str(imagehash.phash(Image.open(path).convert("RGB")))
    except Exception:
        return None


PHASH_EXACT     = 3   # ≤3 = ซ้ำแน่นอน ไม่ต้องเช็ค ref
PHASH_UNCERTAIN = 8   # 4-8 = ไม่แน่ใจ ต้องเช็ค ref ด้วย


def find_duplicate(phash_str: str, db: dict, ref: str | None = None) -> dict | None:
    """
    เช็คซ้ำ 2 ชั้น:
    - phash ≤ 3  → ซ้ำแน่นอน
    - phash 4-8  → เช็ค ref ด้วย ถ้า ref ตรง = ซ้ำ
    - phash > 8  → ไม่ซ้ำ
    """
    current = imagehash.hex_to_hash(phash_str)
    for stored_str, record in db.items():
        diff = current - imagehash.hex_to_hash(stored_str)
        if diff <= PHASH_EXACT:
            return record  # ซ้ำแน่นอน
        if diff <= PHASH_UNCERTAIN and ref and record.get("ref"):
            if ref == record["ref"]:
                return record  # ref ตรง = ซ้ำ
    return None

# ── Claude API ────────────────────────────────────────────────────────────────

def read_slip(client: anthropic.Anthropic, image_path: Path) -> dict | None:
    """อ่านข้อมูลทั้งหมดจาก slip ในรอบเดียว"""
    ext = image_path.suffix.lower()
    media_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
    }
    try:
        img_data = base64.standard_b64encode(image_path.read_bytes()).decode()
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": media_map.get(ext, "image/jpeg"),
                        "data": img_data
                    }},
                    {"type": "text", "text": "ดึงข้อมูลทั้งหมดจาก slip นี้"},
                ],
            }],
        )
        text = resp.content[0].text.strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r'\{[^}]+\}', text, re.DOTALL)
            result = json.loads(m.group()) if m else None

        if result and "error" in result:
            return None
        if result and all(k in result for k in ("day", "month", "year_ce")):
            return result
    except Exception as e:
        log(f"    ⚠️  API error: {e}")
    return None

# ── File ops ──────────────────────────────────────────────────────────────────

def safe_copy(src: Path, dest_dir: Path) -> Path:
    """copy ไฟล์ไป dest_dir ถ้าชื่อซ้ำให้เพิ่ม suffix — retry ถ้าเจอ IO error"""
    import time
    for attempt in range(3):
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{src.stem}_{counter}{src.suffix}"
                counter += 1
            shutil.copy(src, dest)
            return dest
        except OSError as e:
            if attempt < 2:
                log(f"    ⚠️  IO error retry {attempt+1}/3: {e}")
                time.sleep(3)
            else:
                raise

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    import tempfile, subprocess
    raw  = Path(RAW_MOUNT)

    if not raw.exists():
        log("❌ rawFile mount ไม่พบ — เช็ค mount ก่อน")
        return {"new": 0, "duplicate": 0, "no_note": 0, "invalid": 0}

    images = [f for f in sorted(raw.iterdir()) if f.suffix.lower() in IMAGE_EXTS]
    if not images:
        log("ℹ️  ไม่มีรูปใหม่")
        return {"new": 0, "duplicate": 0, "no_note": 0, "invalid": 0}

    log(f"📂 พบรูปใหม่ {len(images)} ไฟล์")

    # ── copy รูปจาก rawFile ลงมา local ด้วย rclone (เร็วกว่า shutil.copy จาก mount) ──
    local_raw = Path(tempfile.mkdtemp()) / "rawFile"
    local_raw.mkdir(parents=True)
    log("   📥 copy รูปมา local...")
    import subprocess
    subprocess.run([
        "rclone", "copy", "gdrive:SlipProcessor/rawFile", str(local_raw),
        "--include", "*.jpg", "--include", "*.jpeg",
        "--include", "*.png", "--include", "*.webp",
        "--include", "*.JPG", "--include", "*.JPEG",
        "--include", "*.PNG", "--include", "*.WEBP",
        "--config", str(Path.home() / ".config/rclone/rclone.conf"),
    ])
    local_images = [f for f in sorted(local_raw.iterdir()) if f.suffix.lower() in IMAGE_EXTS]
    log(f"   ✅ copy {len(local_images)} รูปเสร็จ")

    # ── local staging dir ──
    local_data = Path(tempfile.mkdtemp()) / "data"
    local_data.mkdir(parents=True)

    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    hash_db  = load_hash_db()
    results  = {"new": 0, "duplicate": 0, "no_note": 0, "invalid": 0, "failed": 0, "details": []}
    lock     = threading.Lock()

    from utils.vendor import load_vendors, find_vendor
    vendors = load_vendors(force_reload=True)

    def process_one(args):
        i, img = args
        try:
            log(f"[{i:4d}/{len(local_images)}] {img.name}")

            phash = get_phash(img)
            if phash:
                with lock:
                    dup = find_duplicate(phash, hash_db, ref=None)
                if dup:
                    log(f"⚠️  ซ้ำ → '{img.name}' ซ้ำกับ '{dup['filename']}' (อยู่ที่ {dup['dest']})")
                    with lock:
                        results["duplicate"] += 1
                        results["details"].append({"file": img.name, "status": "duplicate", "original": dup["filename"]})
                    return

            info = read_slip(client, img)
            if info is None:
                safe_copy(img, local_data / "unclassified" / "invalid")
                log(f"❌ อ่านไม่ได้")
                with lock:
                    results["invalid"] += 1
                    results["details"].append({"file": img.name, "status": "invalid"})
                return

            ref = info.get("ref")
            if phash:
                with lock:
                    dup = find_duplicate(phash, hash_db, ref=ref)
                if dup:
                    log(f"⚠️  ซ้ำ (ref) → ref={ref}")
                    with lock:
                        results["duplicate"] += 1
                        results["details"].append({"file": img.name, "status": "duplicate", "ref": ref})
                    return

            note = info.get("note")
            if not note:
                safe_copy(img, local_data / "unclassified" / "no_note")
                log(f"❓ ไม่มี note")
                with lock:
                    results["no_note"] += 1
                    results["details"].append({"file": img.name, "status": "no_note"})
                return

            year       = info["year_ce"]
            month      = info["month"]
            day        = info["day"]
            month_name = MONTH_MAP.get(month, f"{month:02d}")
            day_str    = f"{day:02d}"
            year_str   = str(year)

            dest_dir     = local_data / year_str / month_name / day_str / "images"
            metadata_dir = local_data / year_str / month_name / day_str / "metadata"
            dest_img     = safe_copy(img, dest_dir)

            metadata_dir.mkdir(parents=True, exist_ok=True)
            slip_json = metadata_dir / (dest_img.stem + ".json")
            info["source_file"]   = img.name
            info["dest_file"]     = dest_img.name
            info["pdf_generated"] = False
            slip_json.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

            log(f"📅 {day_str}/{month_name}/{year} ฿{info.get('amount', 0):,.0f}")

            with lock:
                if phash:
                    hash_db[phash] = {
                        "filename": img.name,
                        "dest": f"{year_str}/{month_name}/{day_str}/images/{dest_img.name}",
                        "day": day, "month": month, "year": year,
                        "ref": info.get("ref"),
                    }
                results["new"] += 1
                results["details"].append({
                    "file": img.name, "status": "ok",
                    "day": day, "month": month, "year": year,
                    "amount": info.get("amount"),
                })
        except Exception as e:
            log(f"❌ error: {e}")
            import traceback; traceback.print_exc()
            with lock:
                results["failed"] += 1

    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(process_one, enumerate(local_images, 1))

    save_hash_db(hash_db)

    # ── rclone upload ย้ายไปทำที่ run_pipeline แทน ──
    log(f"\n{'='*55}")
    log(f"✅ ใหม่: {results['new']}  ⚠️ ซ้ำ: {results['duplicate']}  ❓ ไม่มี note: {results['no_note']}  ❌ อ่านไม่ได้: {results['invalid']}")
    results["_local_data"] = str(local_data)  # ส่ง path กลับไปให้ run_pipeline sync
    return results


if __name__ == "__main__":
    run()