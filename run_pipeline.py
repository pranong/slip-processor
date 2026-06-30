from utils.logger import log
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
        log("🗑️  ลบรูปใน rawFile เสร็จแล้ว")
    else:
        log(f"⚠️  ลบ rawFile error: {result.stderr[:100]}")
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

    log("=" * 55)
    log(f"▶ Slip Processor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 55)

    log_file = setup_logging()

    if not check_mounts():
        sys.exit(1)

    notify.send(f"🚀 Pipeline เริ่มแล้ว — {datetime.now().strftime('%H:%M:%S')}")

    # ── รอ rawFile mount sync ──
    import time as _time
    log("\n── รอ rawFile sync ──")
    _time.sleep(10)

    # ── 1. sort slips ──
    log("\n── ขั้นตอน 1: sort ──")
    t0 = time.time()
    sort_result = sort_slips.run()
    sort_elapsed = fmt_duration(time.time() - t0)
    local_data = sort_result.get("_local_data")

    notify.send(build_sort_message(sort_result, sort_elapsed))

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

    if sort_result.get("new", 0) == 0:
        msg = "ℹ️ ไม่มี slip ใหม่ที่ต้อง gen PDF — หยุด pipeline"
        log(msg)
        notify.send(msg)
        return

    # ── 2. gen PDF ──
    log("\n── ขั้นตอน 2: gen PDF ──")
    t0 = time.time()
    gen_result = gen_pdf.run(local_data_path=local_data)
    gen_elapsed = fmt_duration(time.time() - t0)
    local_output = gen_result.get("_local_output")

    notify.send(build_gen_message(gen_result, gen_elapsed))

    process_elapsed = fmt_duration(time.time() - t_total)
    log(f"\n── Process เสร็จ ({process_elapsed}) — เริ่ม Sync ──")
    notify.send(f"⚙️ Process เสร็จใน {process_elapsed}\n🔄 กำลัง sync ขึ้น Drive...")

    # ── 3. Sync ขึ้น Drive ทีเดียว ──
    t_sync = time.time()
    import subprocess

    # 3a. upload metadata + images จาก sort
    if local_data:
        log("\n── Sync data ──")
        subprocess.run([
            "rclone", "copy", local_data,
            "gdrive:SlipProcessor/data",
            "--config", str(Path.home() / ".config/rclone/rclone.conf"),
        ], capture_output=True)
        log("   ✅ data synced")

    # 3b. upload PDFs จาก gen
    if local_output:
        log("\n── Sync PDFs ──")
        subprocess.run([
            "rclone", "copy", local_output,
            "gdrive:SlipProcessor/data",
            "--config", str(Path.home() / ".config/rclone/rclone.conf"),
        ], capture_output=True)
        log("   ✅ PDFs synced")

    # 3c. clear rawFile
    log("\n── ขั้นตอน 3: clear rawFile ──")
    clear_raw_files()

    sync_elapsed = fmt_duration(time.time() - t_sync)

    # ── 4. บันทึก transactions ลง Google Sheets (หลัง sync เสร็จ ไฟล์มีบน Drive แล้ว) ──
    pending = gen_result.get("_pending_transactions", [])
    if pending:
        log("\n── บันทึก Transactions ──")
        from utils.transactions import append_transactions
        for item in pending:
            try:
                append_transactions(
                    slips=item["slips"],
                    category=item["category"],
                    cert_filename=item["cert_filename"],
                    receipt_filenames=item["receipt_filenames"],
                )
            except Exception as e:
                log(f"   ⚠️  บันทึก transactions ไม่ได้: {e}")

    total_elapsed = fmt_duration(time.time() - t_total)
    notify.send(f"✅ Pipeline เสร็จสิ้น\n⏱ Process: {process_elapsed}\n🔄 Sync: {sync_elapsed}\n⏱ รวม: {total_elapsed}")

    log(f"\n✅ เสร็จสิ้น {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — รวม: {total_elapsed}")
    log(f"   Process: {process_elapsed} | Sync: {sync_elapsed}")
    log(f"   log: {log_file}")
    log("=" * 55)


if __name__ == "__main__":
    main()
