"""
run_pipeline.py — ตัวจัดการ pipeline ทั้งหมด
sort_slips → gen_pdf → notify → clear rawFile
"""

import sys
import shutil
import logging
from datetime import datetime
from pathlib import Path

from config import RAW_MOUNT, DATA_MOUNT, LOG_DIR, IMAGE_EXTS
import sort_slips
import gen_pdf
import notify


def setup_logging():
    """สร้าง log file สำหรับแต่ละรอบ"""
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{ts}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file


def clear_raw_files():
    """ลบรูปที่ประมวลผลแล้วใน rawFile"""
    raw = Path(RAW_MOUNT)
    count = 0
    for f in raw.iterdir():
        if f.suffix.lower() in IMAGE_EXTS:
            f.unlink()
            count += 1
    print(f"🗑️  ลบรูปใน rawFile: {count} ไฟล์")
    return count


def check_mounts() -> bool:
    """เช็คว่า mount points ยัง alive อยู่"""
    raw_ok  = Path(RAW_MOUNT).exists() and Path(RAW_MOUNT).is_dir()
    data_ok = Path(DATA_MOUNT).exists() and Path(DATA_MOUNT).is_dir()

    if not raw_ok:
        print(f"❌ rawFile mount ไม่พบ: {RAW_MOUNT}")
        notify.send(f"\n🔴 Pipeline Error\nrawFile mount ไม่พบ\nกรุณาเช็ค mount")
    if not data_ok:
        print(f"❌ data mount ไม่พบ: {DATA_MOUNT}")
        notify.send(f"\n🔴 Pipeline Error\ndata mount ไม่พบ\nกรุณาเช็ค mount")

    return raw_ok and data_ok


def main():
    print("=" * 55)
    print(f"▶ Slip Processor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    log_file = setup_logging()

    # ── เช็ค mount ──
    if not check_mounts():
        sys.exit(1)

    # ── 1. sort slips ──
    print("\n── ขั้นตอน 1: อ่าน + แยก folder ──")
    sort_result = sort_slips.run()

    # ── 2. gen PDF ──
    print("\n── ขั้นตอน 2: gen PDF ──")
    gen_result = gen_pdf.run()

    # ── 3. clear raw files ──
    print("\n── ขั้นตอน 3: clear rawFile ──")
    clear_raw_files()

    # ── 4. notify ──
    print("\n── ขั้นตอน 4: แจ้ง Line ──")
    msg = notify.build_summary_message(sort_result, gen_result)
    notify.send(msg)

    # แจ้งเตือน unclassified แยก (ถ้ามี)
    unclass_msg = notify.build_unclassified_message(sort_result)
    if unclass_msg:
        notify.send(unclass_msg)

    print(f"\n✅ เสร็จสิ้น — log: {log_file}")
    print("=" * 55)


if __name__ == "__main__":
    main()
