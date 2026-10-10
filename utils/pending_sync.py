"""
pending_sync.py — เก็บงานที่ sort/gen เสร็จแล้วแต่ sync ขึ้น Drive ไม่ผ่าน ไว้รอ /resync

ย้าย local temp (/tmp/tmpXXXXXXXX/{data,output}) มาไว้ที่ data/pending_sync/<timestamp>/ บน disk
ของ Pi (ไม่ใช่ rclone mount) — /tmp หายตอน reboot และไม่มีใครจำ path ได้ เก็บตรงนี้แทนจะได้ sync
ไฟล์เดิมขึ้น Drive ซ้ำได้โดยไม่ต้องอ่านสลิปใหม่ (ประหยัด API) และไม่ต้องล้าง processed_refs.json

โครงสร้าง 1 batch:
  data/pending_sync/20261010_153000/
    ├── data/           ← รูป + metadata จาก sort (ถ้ามี)
    ├── output/         ← PDF จาก gen (ถ้ามี)
    └── manifest.json   ← pending transactions + รายชื่อรูปใน rawFile ที่ต้องลบหลัง sync ผ่าน
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from config.config import CODE_DIR
from utils.logger import log

PENDING_SYNC_DIR = Path(CODE_DIR) / "data" / "pending_sync"
MANIFEST_NAME    = "manifest.json"


def stash(source: str, local_data: str | None = None, local_output: str | None = None,
          pending_transactions: list | None = None, raw_files: list[str] | None = None) -> Path | None:
    """
    ย้าย local_data/local_output ออกจาก /tmp มาเก็บเป็น batch ใหม่ + เขียน manifest
    source: ชื่อคำสั่งที่ sync fail (เช่น "/run") ไว้โชว์ตอน resync
    raw_files: ชื่อรูปใน rawFile ของรอบนี้ — resync จะลบเฉพาะไฟล์พวกนี้ ไม่ลบทั้ง rawFile
               (ระหว่างรอ resync ผู้ใช้อาจโยนสลิปใหม่เข้ามาแล้ว)
    return path ของ batch, หรือ None ถ้าย้ายไม่ได้ (ไฟล์ยังอยู่ที่ /tmp เหมือนเดิม)
    """
    batch = PENDING_SYNC_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        batch.mkdir(parents=True, exist_ok=False)
        for name, src in (("data", local_data), ("output", local_output)):
            if src and Path(src).exists():
                shutil.move(str(src), str(batch / name))
                # โฟลเดอร์แม่ /tmp/tmpXXXXXXXX ว่างแล้ว ลบทิ้ง (ไม่ว่างก็ปล่อยไว้)
                try:
                    Path(src).parent.rmdir()
                except OSError:
                    pass
        manifest = {
            "source": source,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw_files": raw_files or [],
            "pending_transactions": pending_transactions or [],
        }
        (batch / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        log(f"   📦 ย้ายไฟล์ที่ยังไม่ได้ sync ไปเก็บที่ {batch}")
        return batch
    except Exception as e:
        log(f"   ⚠️  ย้ายไฟล์ไป pending_sync ไม่ได้: {e}")
        return None


def list_batches() -> list[Path]:
    """batch ที่ค้างอยู่ทั้งหมด เรียงเก่า → ใหม่"""
    if not PENDING_SYNC_DIR.exists():
        return []
    return sorted(d for d in PENDING_SYNC_DIR.iterdir() if d.is_dir())


def load_manifest(batch: Path) -> dict:
    try:
        return json.loads((batch / MANIFEST_NAME).read_text(encoding="utf-8"))
    except Exception as e:
        log(f"   ⚠️  อ่าน manifest ของ {batch.name} ไม่ได้: {e}")
        return {}


def save_manifest(batch: Path, manifest: dict):
    (batch / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def count_files(batch: Path) -> int:
    return sum(1 for f in batch.rglob("*") if f.is_file() and f.name != MANIFEST_NAME)


def remove(batch: Path):
    shutil.rmtree(batch, ignore_errors=True)


def fail_message(source: str, batch: Path | None, extra: str = "") -> str:
    """ข้อความแจ้ง Telegram ตอน sync ไม่ผ่าน — ใช้ร่วมกันทุกคำสั่งที่ sync ขึ้น Drive"""
    if batch is None:
        return (f"🔴 <b>Sync ขึ้น Drive ไม่สำเร็จ</b> ({source}) และย้ายไฟล์ออกจาก /tmp ไม่ได้ — "
                f"ไฟล์ยังค้างอยู่ใน /tmp บน Pi (หายตอน reboot) ต้อง sync เองด้วยมือ ดู log")
    return (f"🔴 <b>Sync ขึ้น Drive ไม่สำเร็จ</b> ({source})\n"
            f"📦 เก็บไฟล์ไว้แล้ว {count_files(batch)} ไฟล์ ที่ <code>{batch}</code> (ไม่หายตอน reboot)\n"
            f"{extra}"
            f"👉 พิมพ์ /resync เพื่อ sync ใหม่ (ไม่ต้องอ่านสลิปซ้ำ ไม่เสีย API)")
