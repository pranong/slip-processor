"""
run_pipeline.py — ตัวจัดการ pipeline ทั้งหมด
sort_slips → notify → gen_pdf → notify → clear rawFile
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

from config.config import RAW_MOUNT, DATA_MOUNT, LOG_DIR, IMAGE_EXTS
import sort_slips
import gen_pdf
from utils import notify as notify


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
    result = subprocess.run([
        "rclone", "delete", "gdrive:SlipProcessor/rawFile",
        "--filter", "+ *.jpg",
        "--filter", "+ *.jpeg", 
        "--filter", "+ *.png",
        "--filter", "+ *.webp",
        "--filter", "+ *.JPG",
        "--filter", "+ *.JPEG",
        "--filter", "+ *.PNG",
        "--filter", "+ *.WEBP",
        "--filter", "- *",
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


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} วิ"
    return f"{s // 60} นาที {s % 60} วิ"


def build_sort_message(sort_result: dict, elapsed: str = "") -> str:
    lines = [
        f"📥 Sort เสร็จแล้ว{f' ({elapsed})' if elapsed else ''}",
        "─────────────────",
        f"✅ ใหม่         : {sort_result.get('new', 0)}",
        f"⚠️  ซ้ำ          : {sort_result.get('duplicate', 0)}",
        f"❓ ไม่มี note   : {sort_result.get('no_note', 0)}",
        f"❌ อ่านไม่ได้   : {sort_result.get('invalid', 0)}",
    ]
    return "\n".join(lines)


def build_gen_message(gen_result: dict, elapsed: str = "") -> str:
    lines = [
        f"📄 Gen PDF เสร็จแล้ว{f' ({elapsed})' if elapsed else ''}",
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
    import time
    t_total = time.time()

    print("=" * 55)
    print(f"▶ Slip Processor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    log_file = setup_logging()

    if not check_mounts():
        sys.exit(1)

    notify.send(f"🚀 Pipeline เริ่มแล้ว — {datetime.now().strftime('%H:%M:%S')}")

    # ── 1. sort slips ──
    print("\n── ขั้นตอน 1: sort ──")
    t0 = time.time()
    sort_result = sort_slips.run()
    sort_elapsed = fmt_duration(time.time() - t0)

    notify.send(build_sort_message(sort_result, sort_elapsed))

    # แจ้ง unclassified
    no_note = [d for d in sort_result.get("details", []) if d.get("status") == "no_note"]
    if no_note:
        lines = [f"❓ ไม่มี note {len(no_note)} ไฟล์ → unclassified/no_note/"]
        for u in no_note[:10]:
            lines.append(f"  - {u['file']}")
        notify.send("\n".join(lines))

    invalid = [d for d in sort_result.get("details", []) if d.get("status") == "invalid"]
    if invalid:
        lines = [f"❌ อ่านไม่ได้ {len(invalid)} ไฟล์ → unclassified/invalid/"]
        for u in invalid[:10]:
            lines.append(f"  - {u['file']}")
        notify.send("\n".join(lines))

    # ── 2. gen PDF ──
    print("\n── ขั้นตอน 2: gen PDF ──")
    t0 = time.time()
    gen_result = gen_pdf.run()
    gen_elapsed = fmt_duration(time.time() - t0)

    notify.send(build_gen_message(gen_result, gen_elapsed))

    # ── 3. clear raw files ──
    print("\n── ขั้นตอน 3: clear rawFile ──")
    clear_raw_files()

    total_elapsed = fmt_duration(time.time() - t_total)
    notify.send(f"✅ Pipeline เสร็จสิ้น\n⏱ รวม: {total_elapsed}")

    print(f"\n✅ เสร็จสิ้น {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — รวม: {total_elapsed}")
    print(f"   log: {log_file}")
    print("=" * 55)


if __name__ == "__main__":
    main()