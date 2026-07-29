from utils.logger import log
"""
recover_metadata.py — กู้ metadata JSON ที่หายไป โดยไม่ต้องยัดรูปกลับเข้า rawFile ใหม่

ใช้ตอนที่ data/{year}/{month}/{day}/images/ มีรูปอยู่ครบ แต่ metadata/ หายหรือไม่ครบ
(เช่นตอน sync ล้มเหลวกลางทางในอดีต ก่อนจะแก้บั๊กใน run_pipeline.py) — รูปอยู่ถูกวันที่โฟลเดอร์อยู่แล้ว
สคริปต์นี้แค่อ่านรูปที่ขาด JSON ซ้ำผ่าน Claude Vision แล้วเติม metadata กลับเข้าที่เดิม

usage:
  python3 recover_metadata.py --dry-run   # แค่สแกนนับจำนวนวัน/รูปที่ขาด ไม่เรียก API ไม่เขียนอะไร
  python3 recover_metadata.py             # กู้จริง เรียก Claude Vision ทุกรูปที่ขาด แล้ว sync ขึ้น Drive
"""

import json
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from config.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, DATA_MOUNT, IMAGE_EXTS
from sort_slips import read_slip, load_ref_db, save_ref_db


def find_missing_metadata_days(data_root: Path):
    """เดินหา {year}/{month}/{day}/images ที่มีรูปแต่ขาด metadata คู่กัน (บางส่วนหรือทั้งหมด)"""
    missing = []
    for year_dir in sorted(data_root.iterdir()):
        if not year_dir.is_dir() or year_dir.name in ("unclassified", "backups", "logs"):
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue
                images_dir   = day_dir / "images"
                metadata_dir = day_dir / "metadata"
                if not images_dir.exists():
                    continue
                image_files = [f for f in images_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS]
                if not image_files:
                    continue
                existing_stems = {f.stem for f in metadata_dir.glob("*.json")} if metadata_dir.exists() else set()
                missing_images = [f for f in image_files if f.stem not in existing_stems]
                if missing_images:
                    missing.append((year_dir.name, month_dir.name, day_dir.name, missing_images))
    return missing


def run(dry_run: bool = False):
    data_root = Path(DATA_MOUNT)
    missing_days = find_missing_metadata_days(data_root)
    total_images = sum(len(imgs) for *_, imgs in missing_days)

    log(f"📋 พบ {len(missing_days)} วันที่ metadata ขาด รวม {total_images} รูป")
    for year, month, day, imgs in missing_days:
        log(f"   {year}/{month}/{day} — {len(imgs)} รูป")

    if dry_run or total_images == 0:
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    ref_db = load_ref_db()
    lock   = threading.Lock()
    results = {"recovered": 0, "failed": 0}

    for year, month, day, images in missing_days:
        log(f"\n── {year}/{month}/{day} — {len(images)} รูป ──")

        # ── copy รูปที่ขาดมา local ก่อน (เร็วกว่าอ่านผ่าน mount ทีละไฟล์) ──
        local_dir = Path(tempfile.mkdtemp())
        for img in images:
            (local_dir / img.name).write_bytes(img.read_bytes())

        local_metadata = local_dir / "metadata"
        local_metadata.mkdir(parents=True, exist_ok=True)

        def process_one(img_name: str):
            img = local_dir / img_name
            try:
                info = read_slip(client, img)
                if info is None:
                    log(f"  ❌ อ่านไม่ได้: {img.name}")
                    with lock:
                        results["failed"] += 1
                    return
                info["source_file"]   = img.name
                info["dest_file"]     = img.name
                info["pdf_generated"] = False
                info["_recovered"]    = True
                (local_metadata / f"{img.stem}.json").write_text(
                    json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                ref = info.get("ref")
                with lock:
                    if ref:
                        ref_db[ref] = {
                            "filename": img.name,
                            "dest": f"{year}/{month}/{day}/images/{img.name}",
                            "day": info.get("day"), "month": info.get("month"), "year": info.get("year_ce"),
                        }
                    results["recovered"] += 1
                log(f"  ✅ {img.name}")
            except Exception as e:
                log(f"  ❌ error {img.name}: {e}")
                with lock:
                    results["failed"] += 1

        with ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(process_one, [i.name for i in images])

        # ── sync metadata ที่กู้ได้ของวันนี้ขึ้น Drive ──
        try:
            subprocess.run([
                "rclone", "copy", str(local_metadata),
                f"gdrive:SlipProcessor/data/{year}/{month}/{day}/metadata",
                "--config", str(Path.home() / ".config/rclone/rclone.conf"),
            ], capture_output=True, timeout=600)
            log(f"   ✅ sync metadata {year}/{month}/{day} ขึ้น Drive")
        except subprocess.TimeoutExpired:
            log(f"   ⚠️  sync metadata {year}/{month}/{day} ค้างเกิน 10 นาที — ต้องรันสคริปต์นี้ซ้ำ (ข้ามไฟล์ที่กู้แล้ว)")

    save_ref_db(ref_db)
    log(f"\n✅ กู้คืน {results['recovered']}  ❌ ล้มเหลว {results['failed']}")
    log("ℹ️  รัน run_pipeline.py หรือ gen_pdf.py --regen ต่อเพื่อ gen PDF ให้สลิปที่กู้คืนมา")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="กู้ metadata JSON ที่หายไปจากรูปที่มีอยู่แล้ว")
    parser.add_argument("--dry-run", action="store_true", help="แค่สแกนนับจำนวน ไม่เรียก API ไม่เขียนอะไร")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
