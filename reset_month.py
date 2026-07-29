from utils.logger import log
"""
reset_month.py — reset ข้อมูลเฉพาะ scope (ปี/เดือน/วัน) แบบเจาะจง ไม่กระทบ scope อื่นเลย

ใช้ตอนข้อมูลช่วงนั้นเสียหาย (เช่น SSH หลุดกลาง sync ทำให้ data ครึ่งๆ กลางๆ) แต่ rawFile
ยังมีรูปต้นฉบับอยู่ครบ อยากลบของเก่าทิ้งแล้วให้ sort ใหม่จาก rawFile

ทำ 4 อย่างตามลำดับ:
  1. reset generated_log.json state ของ scope นั้น (เหมือน gen_pdf.py --regen)
  2. ลบ ref ของ scope นั้นออกจาก processed_refs.json (กัน sort_slips.py เข้าใจผิดว่าซ้ำ)
  3. ลบข้อมูล data/{scope} ทั้งหมดบน Drive (รูป/metadata/PDF ของ scope นั้น)
  4. ลบ key เดือนนั้นออกจาก summary.json ของปี (กัน merge_to_summary บวกซ้ำตอน gen ใหม่)

**ไม่แตะ rawFile เลย** — รูปต้นฉบับต้องยังอยู่ใน rawFile ถึงจะ sort ใหม่ได้หลัง reset
ถ้า rawFile ไม่มีรูปของ scope นี้แล้ว (เคยถูกลบไปแล้ว) ข้อมูลจะหายถาวร ห้ามรันสคริปต์นี้

usage:
  python3 reset_month.py --scope 2026/APR --dry-run   # เช็คก่อนว่าจะลบอะไรบ้าง ไม่ลบจริง
  python3 reset_month.py --scope 2026/APR             # ลบจริง
"""

import json
import subprocess
from pathlib import Path

from config.config import DATA_MOUNT, REF_DB_PATH
from utils.state import load_state, save_state, reset_state

MONTH_MAP_NUM = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def run(scope: str, dry_run: bool = False):
    parts = scope.strip("/").split("/")
    year  = parts[0]
    month = parts[1] if len(parts) >= 2 else None
    day   = parts[2] if len(parts) >= 3 else None

    log(f"🎯 scope: {scope}{'  (DRY RUN — ไม่ลบจริง)' if dry_run else ''}")

    # ── 1. reset state ──
    state = load_state()
    count = reset_state(state, scope)
    log(f"1. state: {'จะ' if dry_run else ''}reset {count} groups")
    if not dry_run:
        save_state(state)

    # ── 2. ลบ ref ของ scope นี้ออกจาก processed_refs.json ──
    ref_path = Path(REF_DB_PATH)
    if ref_path.exists():
        db = json.loads(ref_path.read_text(encoding="utf-8"))
        month_num = MONTH_MAP_NUM.get(month) if month else None

        def matches(record):
            if str(record.get("year")) != year:
                return False
            if month and record.get("month") != month_num:
                return False
            if day and str(record.get("day")).zfill(2) != day.zfill(2):
                return False
            return True

        before = len(db)
        db = {k: v for k, v in db.items() if not matches(v)}
        removed = before - len(db)
        log(f"2. ref_db: {'จะ' if dry_run else ''}ลบ {removed} refs")
        if not dry_run:
            ref_path.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        log("2. ref_db: ไม่มีไฟล์ ข้าม")

    # ── 3. ลบข้อมูลบน Drive ──
    drive_path = f"gdrive:SlipProcessor/data/{scope}"
    log(f"3. Drive: {'จะ' if dry_run else ''}ลบ {drive_path}")
    if not dry_run:
        result = subprocess.run([
            "rclone", "purge", drive_path,
            "--config", str(Path.home() / ".config/rclone/rclone.conf"),
        ], capture_output=True, text=True)
        if result.returncode != 0:
            log(f"   ⚠️  {result.stderr[:200]}")

    # ── 4. ลบ key เดือนออกจาก summary.json ของปี (เฉพาะกรณี scope มีระบุเดือน) ──
    if month:
        summary_path = Path(DATA_MOUNT) / year / "summary.json"
        log(f"4. summary.json: {'จะ' if dry_run else ''}ลบ key '{month}' จาก {summary_path}")
        if not dry_run and summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary.pop(month, None)
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if dry_run:
        log("\nℹ️  dry-run เท่านั้น ไม่มีอะไรถูกลบจริง — รันไม่ใส่ --dry-run เพื่อลบจริง")
    else:
        log("\n✅ เสร็จ — รัน run_pipeline.py ต่อ (แนะนำ nohup กัน SSH หลุด) เพื่อ sort+gen ใหม่จาก rawFile")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Reset ข้อมูลเฉพาะ scope (ปี/เดือน/วัน) แบบเจาะจง")
    parser.add_argument("--scope", required=True, help='เช่น "2026", "2026/APR", "2026/APR/15"')
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(scope=args.scope, dry_run=args.dry_run)
