"""
run_pipeline.py — ตัวจัดการ pipeline ทั้งหมด
sort_slips → notify → gen_pdf → notify → clear rawFile
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

from config import RAW_MOUNT, DATA_MOUNT, LOG_DIR, IMAGE_EXTS
import sort_slips
import gen_pdf
import notify


def setup_logging():
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
    import subprocess
    from config import RCLONE_REMOTE
    result = subprocess.run([
        "rclone", "delete", f"{RCLONE_REMOTE}:SlipProcessor/rawFile",
        "--include", "*.jpg", "--include", "*.jpeg",
        "--include", "*.png", "--include", "*.webp",
        "--config", str(Path.home() / ".config/rclone/rclone.conf"),
    ], capture_output=True, text=True)
    if result.returncode == 0:
        print("🗑️  ลบรูปใน rawFile เสร็จแล้ว")
    else:
        print(f"⚠️  ลบ rawFile error: {result.stderr[:100]}")
    return 0


def check_mounts() -> bool:
    raw_ok  = Path(RAW_MOUNT).exists() and Path(RAW_MOUNT).is_dir()
    data_ok = Path(DATA_MOUNT).exists() and Path(DATA_MOUNT).is_dir()
    if not raw_ok:
        notify.send("🔴 Pipeline Error\nrawFile mount ไม่พบ\nกรุณาเช็ค mount")
    if not data_ok:
        notify.send("🔴 Pipeline Error\ndata mount ไม่พบ\nกรุณาเช็ค mount")
    return raw_ok and data_ok


def build_sort_message(sort_result: dict) -> str:
    lines = [
        "📥 Sort เสร็จแล้ว",
        "─────────────────",
        f"✅ ใหม่      : {sort_result.get('new', 0)}",
        f"⚠️  ซ้ำ       : {sort_result.get('duplicate', 0)}",
        f"❓ จัดไม่ได้ : {sort_result.get('unclassified', 0)}",
        f"❌ ล้มเหลว  : {sort_result.get('failed', 0)}",
    ]
    return "\n".join(lines)


def build_gen_message(gen_result: dict) -> str:
    lines = [
        "📄 Gen PDF เสร็จแล้ว",
        "─────────────────",
        f"✅ gen ใหม่  : {gen_result.get('new', 0)}",
        f"❌ ล้มเหลว  : {gen_result.get('failed', 0)}",
    ]
    monthly = gen_result.get("monthly", {})
    if monthly:
        lines.append("─────────────────")
        lines.append("💰 ยอดรายจ่ายรอบนี้:")
        for m in sorted(monthly.keys()):
            lines.append(f"  {m}: ฿{monthly[m]:,.0f}")
    return "\n".join(lines)


def main():
    print("=" * 55)
    print(f"▶ Slip Processor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    log_file = setup_logging()

    # ── เช็ค mount ──
    if not check_mounts():
        sys.exit(1)

    # ── 1. sort slips ──
    print("\n── ขั้นตอน 1: sort ──")
    sort_result = sort_slips.run()

    # ── แจ้ง sort ──
    notify.send(build_sort_message(sort_result))
    if sort_result.get("unclassified", 0) > 0:
        notify.send(notify.build_unclassified_message(sort_result))

    # ── 2. gen PDF ──
    print("\n── ขั้นตอน 2: gen PDF ──")
    gen_result = gen_pdf.run()

    # ── แจ้ง gen ──
    notify.send(build_gen_message(gen_result))

    # ── 3. clear raw files ──
    print("\n── ขั้นตอน 3: clear rawFile ──")
    clear_raw_files()

    print(f"\n✅ เสร็จสิ้น — log: {log_file}")
    print("=" * 55)


if __name__ == "__main__":
    main()
