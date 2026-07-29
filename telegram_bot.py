from utils.logger import log
"""
telegram_bot.py — รับคำสั่งจาก Telegram แล้วรัน pipeline
คำสั่งที่รองรับ:
  /run    — รัน pipeline ทั้งหมด (sort + gen)
  /sort   — รัน sort_slips เท่านั้น
  /gen    — รัน gen_pdf เท่านั้น
  /status — เช็คสถานะ mount
  /help   — ดูคำสั่งทั้งหมด
"""

import time
import requests
import threading
from pathlib import Path
from datetime import datetime

from config.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RAW_MOUNT, DATA_MOUNT

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
OFFSET  = 0
RUNNING = False
RUNNING_SINCE = None
MAX_RUNNING_SECONDS = 30 * 60  # ค้างเกินนี้ถือว่า stuck (mount/rclone หลุดแบบไม่ raise) ปลดล็อกอัตโนมัติ
LOCK    = threading.Lock()


def send(text: str):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        log(f"[send error] {e}")


def get_updates(offset: int) -> list:
    try:
        r = requests.get(f"{API_URL}/getUpdates", params={
            "offset": offset,
            "timeout": 30,
        }, timeout=40)
        return r.json().get("result", [])
    except Exception:
        return []


def check_mounts() -> str:
    raw_ok  = Path(RAW_MOUNT).is_mount()
    data_ok = Path(DATA_MOUNT).is_mount()
    lines = [
        "📊 <b>Status</b>",
        f"rawFile : {'✅ mounted' if raw_ok else '❌ ไม่ได้ mount'}",
        f"data    : {'✅ mounted' if data_ok else '❌ ไม่ได้ mount'}",
        f"เวลา    : {datetime.now().strftime('%H:%M:%S')}",
    ]
    return "\n".join(lines)


def send_sort_summary(result: dict, elapsed: str = ""):
    lines = [
        f"📥 <b>Sort เสร็จแล้ว</b>{f' ({elapsed})' if elapsed else ''}",
        "─────────────────",
        f"✅ ใหม่         : {result.get('new', 0)}",
        f"⚠️  ซ้ำ          : {result.get('duplicate', 0)}",
        f"❓ ไม่มี note   : {result.get('no_note', 0)}",
        f"❌ อ่านไม่ได้   : {result.get('invalid', 0)}",
    ]
    send("\n".join(lines))

    no_note = [d for d in result.get("details", []) if d.get("status") == "no_note"]
    if no_note:
        msg = [f"❓ <b>ไม่มี note {len(no_note)} ไฟล์</b>", "→ <code>unclassified/no_note/</code>", "─────────────────"]
        for u in no_note[:10]:
            msg.append(f"  - {u['file']}")
        if len(no_note) > 10:
            msg.append(f"  ... อีก {len(no_note) - 10} ไฟล์")
        send("\n".join(msg))

    invalid = [d for d in result.get("details", []) if d.get("status") == "invalid"]
    if invalid:
        msg = [f"❌ <b>อ่านไม่ได้ {len(invalid)} ไฟล์</b>", "→ <code>unclassified/invalid/</code>", "─────────────────"]
        for u in invalid[:10]:
            msg.append(f"  - {u['file']}")
        if len(invalid) > 10:
            msg.append(f"  ... อีก {len(invalid) - 10} ไฟล์")
        send("\n".join(msg))


def send_gen_summary(result: dict, elapsed: str = ""):
    """ส่งสรุป gen PDF"""
    lines = [
        f"📄 <b>Gen PDF เสร็จแล้ว</b>{f' ({elapsed})' if elapsed else ''}",
        "─────────────────",
        f"✅ gen ใหม่  : {result.get('new', 0)}",
        f"❌ ล้มเหลว  : {result.get('failed', 0)}",
    ]
    monthly = result.get("monthly", {})
    if monthly:
        lines.append("─────────────────")
        lines.append("💰 ยอดรายจ่ายรอบนี้:")
        for m in sorted(monthly.keys()):
            lines.append(f"  {m}: ฿{monthly[m]:,.0f}")
    send("\n".join(lines))


def fmt_duration(seconds: float) -> str:
    """แปลงวินาทีเป็นข้อความ เช่น 1 นาที 23 วิ"""
    s = int(seconds)
    if s < 60:
        return f"{s} วิ"
    return f"{s // 60} นาที {s % 60} วิ"


def do_run(cmd: str):
    global RUNNING
    import sort_slips
    import gen_pdf
    import time
    from datetime import datetime

    try:
        if cmd == "/sort":
            t0 = time.time()
            send(f"🚀 Sort เริ่มแล้ว — {datetime.now().strftime('%H:%M:%S')}")
            result = sort_slips.run()
            from utils.vendor import reload_vendors
            reload_vendors()
            elapsed = fmt_duration(time.time() - t0)
            send_sort_summary(result, elapsed)

        elif cmd == "/gen":
            t0 = time.time()
            send(f"🚀 Gen PDF เริ่มแล้ว — {datetime.now().strftime('%H:%M:%S')}")
            result = gen_pdf.run()
            elapsed = fmt_duration(time.time() - t0)
            send_gen_summary(result, elapsed)

        elif cmd == "/run":
            t_total = time.time()
            send(f"🚀 Pipeline เริ่มแล้ว — {datetime.now().strftime('%H:%M:%S')}")

            # sort
            t0 = time.time()
            sort_result = sort_slips.run()
            from utils.vendor import reload_vendors
            reload_vendors()
            sort_elapsed = fmt_duration(time.time() - t0)
            send_sort_summary(sort_result, sort_elapsed)

            # clear
            from run_pipeline import clear_raw_files
            clear_raw_files()

            # gen
            t0 = time.time()
            gen_result = gen_pdf.run()
            gen_elapsed = fmt_duration(time.time() - t0)
            send_gen_summary(gen_result, gen_elapsed)

            # รวม
            total_elapsed = fmt_duration(time.time() - t_total)
            send(f"✅ Pipeline เสร็จสิ้น\n⏱ รวม: {total_elapsed}")

    except Exception as e:
        import traceback
        send(f"❌ เกิดข้อผิดพลาด\n<code>{e}</code>")
        log(traceback.format_exc())
    finally:
        global RUNNING, RUNNING_SINCE
        with LOCK:
            RUNNING = False
            RUNNING_SINCE = None


def reset_pdf_generated(path_filter: str) -> int:
    """Reset state local ตาม path filter — เร็วมาก ไม่แตะ Drive เลย"""
    from utils.state import load_state, save_state, reset_state
    state = load_state()
    count = reset_state(state, path_filter)
    save_state(state)
    return count


def do_regen(scope: str):
    """regen ตาม scope เช่น 2026 / 2026/JUN / 2026/JUN/24"""
    global RUNNING
    import time
    from datetime import datetime
    try:
        import gen_pdf
        t0 = time.time()
        send(f"🚀 Regen เริ่มแล้ว — {datetime.now().strftime('%H:%M:%S')}\nscope: <code>{scope}</code>")
        count = reset_pdf_generated(scope)
        send(f"♻️ Reset {count} groups — กำลัง gen...")
        result = gen_pdf.run()
        elapsed = fmt_duration(time.time() - t0)
        send(f"📄 <b>Regen เสร็จแล้ว ({scope})</b>")
        send_gen_summary(result, elapsed)
    except Exception as e:
        import traceback
        send(f"❌ เกิดข้อผิดพลาด\n<code>{e}</code>")
        log(traceback.format_exc())
    finally:
        global RUNNING, RUNNING_SINCE
        with LOCK:
            RUNNING = False
            RUNNING_SINCE = None


def run_command(cmd: str, extra: str = ""):
    global RUNNING, RUNNING_SINCE
    with LOCK:
        if RUNNING:
            stuck_for = time.time() - RUNNING_SINCE if RUNNING_SINCE else 0
            if stuck_for < MAX_RUNNING_SECONDS:
                send("⚠️ กำลังรันอยู่แล้ว รอให้เสร็จก่อนนะครับ")
                return
            log(f"⚠️  RUNNING ค้างเกิน {MAX_RUNNING_SECONDS}s (น่าจะ mount/rclone แฮงค์) — ปลดล็อกอัตโนมัติ")
            send("⚠️ รอบก่อนค้างนานผิดปกติ (mount/rclone อาจแฮงค์) — ปลดล็อกแล้วรันรอบใหม่ให้")
        RUNNING = True
        RUNNING_SINCE = time.time()

    if cmd in ("/genyear", "/genmonth", "/genday"):
        t = threading.Thread(target=do_regen, args=(extra,), daemon=True)
    else:
        t = threading.Thread(target=do_run, args=(cmd,), daemon=True)
    t.start()


def handle_command(text: str):
    parts = text.strip().split()
    cmd   = parts[0].lower()
    extra = parts[1].lstrip("-") if len(parts) > 1 else ""

    if cmd == "/status":
        send(check_mounts())
    elif cmd == "/reloadvendor":
        from utils.vendor import reload_vendors
        vendors = reload_vendors()
        send(f"✅ Reload vendor สำเร็จ — มี {len(vendors)} รายการ")
    elif cmd in ("/run", "/sort", "/gen"):
        run_command(cmd)
    elif cmd in ("/genyear", "/genmonth", "/genday"):
        if not extra:
            examples = {
                "/genyear": "/genYear -2026",
                "/genmonth": "/genMonth -2026/JUN",
                "/genday": "/genDay -2026/JUN/24",
            }
            send(f"❗ ระบุ scope ด้วยครับ เช่น\n<code>{examples[cmd]}</code>")
            return
        run_command(cmd, extra)
    elif cmd == "/help":
        send(
            "📋 <b>คำสั่งที่ใช้ได้</b>\n"
            "─────────────────\n"
            "/run              — รัน pipeline ทั้งหมด\n"
            "/sort             — อ่าน slip + แยก folder\n"
            "/gen              — gen PDF เท่านั้น\n"
            "/genYear -2026    — regen ทั้งปี\n"
            "/genMonth -2026/JUN — regen ทั้งเดือน\n"
            "/genDay -2026/JUN/24 — regen วันเดียว\n"
            "/reloadvendor     — โหลด vendor จาก GSheet ใหม่\n"
            "/status           — เช็คสถานะ mount\n"
            "/help             — แสดงคำสั่ง"
        )
    else:
        send(f"❓ ไม่รู้จักคำสั่ง <code>{cmd}</code>\nพิมพ์ /help เพื่อดูคำสั่ง")


def main():
    global OFFSET
    log(f"🤖 Bot เริ่มทำงาน — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    send("🤖 <b>Slip Processor Bot พร้อมแล้ว!</b>\nพิมพ์ /help เพื่อดูคำสั่ง")

    while True:
        updates = get_updates(OFFSET)
        for update in updates:
            OFFSET = update["update_id"] + 1
            msg = update.get("message") or update.get("channel_post")
            if not msg:
                continue
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue
            text = msg.get("text", "")
            if text.startswith("/"):
                log(f"[cmd] {text}")
                handle_command(text)
        time.sleep(1)


if __name__ == "__main__":
    main()
