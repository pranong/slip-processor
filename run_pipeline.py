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
    try:
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
        ], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        log("⚠️  ลบ rawFile ค้างเกิน 2 นาที — เช็ค mount/network")
        return 0
    if result.returncode == 0:
        log("🗑️  ลบรูปใน rawFile เสร็จแล้ว")
    else:
        log(f"⚠️  ลบ rawFile error: {result.stderr[:100]}")
    return 0


def sync_to_drive(local_dir: str, timeout: int = 1800) -> bool:
    """
    Upload local_dir ขึ้น Drive (`gdrive:SlipProcessor/data`) — copy ก้อนเดียว (--ignore-times
    บังคับทับไฟล์เดิมเสมอ เผื่อ regen แล้วขนาด/เวลาเผอิญตรงกัน)
    timeout ยาวเท่ากับตอนโหลด rawFile (เน็ต Pi ช้า ~150-200 KB/s เป็นปกติ ไม่ใช่ค้าง)
    return True = sync สำเร็จจริง, False = timeout/error — ห้ามให้ caller ทำ clear_raw_files()
    หรือบันทึก transactions ต่อถ้า return False เพราะไฟล์อาจยังไม่ครบบน Drive
    """
    import subprocess
    base = Path(local_dir)
    if not base.exists():
        return True
    try:
        result = subprocess.run([
            "rclone", "copy", str(base),
            "gdrive:SlipProcessor/data",
            "--ignore-times",
            "--config", str(Path.home() / ".config/rclone/rclone.conf"),
        ], capture_output=True, timeout=timeout)
        if result.returncode != 0:
            log(f"   ⚠️  sync error: {result.stderr[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log(f"   ⚠️  sync ค้างเกิน {timeout} วิ — เช็ค mount/network")
        return False


# alias เดิม (ใช้ใน gen_pdf.py --regen)
sync_output_dir = sync_to_drive


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

    # 3a. upload metadata + images จาก sort
    data_ok = True
    if local_data:
        log("\n── Sync data ──")
        data_ok = sync_to_drive(local_data)
        log("   ✅ data synced" if data_ok else "   ❌ sync data ล้มเหลว")

    # 3b. upload PDFs จาก gen
    pdf_ok = True
    if local_output:
        log("\n── Sync PDFs ──")
        pdf_ok = sync_to_drive(local_output)
        log("   ✅ PDFs synced" if pdf_ok else "   ❌ sync PDFs ล้มเหลว")

    sync_elapsed = fmt_duration(time.time() - t_sync)

    if not (data_ok and pdf_ok):
        msg = (f"🔴 Sync ขึ้น Drive ไม่สำเร็จ ({sync_elapsed}) — "
               f"ข้าม clear rawFile และ บันทึก transactions เพื่อกันข้อมูลเพี้ยน "
               f"รูปต้นฉบับใน rawFile ยังไม่ถูกลบ ปลอดภัย แต่ ref ของสลิปกลุ่มนี้ถูกบันทึกไปแล้วตอน sort "
               f"ต้องล้าง data/processed_refs.json (หรือรัน scripts/reset.sh) ก่อน rerun ไม่งั้นจะโดนเข้าใจว่าซ้ำ")
        log(f"\n{msg}")
        notify.send(msg)
        return

    # 3c. clear rawFile (ทำเฉพาะตอน sync สำเร็จจริงเท่านั้น กันรูปต้นฉบับหายทั้งที่ยังไม่ขึ้น Drive)
    log("\n── ขั้นตอน 3: clear rawFile ──")
    clear_raw_files()

    # ── 4. บันทึก transactions ลง Google Sheets (หลัง sync เสร็จ ไฟล์มีบน Drive แล้ว) ──
    pending = gen_result.get("_pending_transactions", [])
    log(f"\n── บันทึก Transactions ({len(pending)} groups) ──")
    if pending:
        from utils.transactions import append_transactions
        for item in pending:
            log(f"   📦 category={item['category']} cert={item['cert_filename']} receipts={list(item['receipt_filenames'].keys())}")
            try:
                append_transactions(
                    slips=item["slips"],
                    category=item["category"],
                    cert_filename=item["cert_filename"],
                    receipt_filenames=item["receipt_filenames"],
                )
            except Exception as e:
                log(f"   ⚠️  บันทึก transactions ไม่ได้: {e}")
    else:
        log("   ℹ️  ไม่มี pending transactions")

    total_elapsed = fmt_duration(time.time() - t_total)
    notify.send(f"✅ Pipeline เสร็จสิ้น\n⏱ Process: {process_elapsed}\n🔄 Sync: {sync_elapsed}\n⏱ รวม: {total_elapsed}")

    # ── cleanup temp files ──
    import shutil as _shutil
    if local_data:
        _shutil.rmtree(local_data, ignore_errors=True)
    if local_output:
        _shutil.rmtree(local_output, ignore_errors=True)

    log(f"\n✅ เสร็จสิ้น {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — รวม: {total_elapsed}")
    log(f"   Process: {process_elapsed} | Sync: {sync_elapsed}")
    log(f"   log: {log_file}")
    log("=" * 55)


if __name__ == "__main__":
    main()
