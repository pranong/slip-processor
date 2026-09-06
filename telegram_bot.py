from utils.logger import log
"""
telegram_bot.py — รับคำสั่งจาก Telegram แล้วรัน pipeline
คำสั่งที่รองรับ (พิมพ์เปล่าๆ = บอทถามทีละคำถามเป็น wizard, หรือพิมพ์ arg รวดเดียวก็ได้):
  /run [เดือน] [ปี]  — รัน pipeline ทั้งหมด (sort + gen)
  /sort [เดือน] [ปี] — รัน sort_slips เท่านั้น
  /gen               — รัน gen_pdf เท่านั้น
  /genYear /genMonth /genDay [scope] — regen (wizard ถามปี→เดือน→วัน ถ้าไม่ใส่ scope)
  /status — เช็คสถานะ mount
  /help   — ดูคำสั่งทั้งหมด
"""

import time
import requests
import threading
from pathlib import Path
from datetime import datetime

from config.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RAW_MOUNT, DATA_MOUNT, MONTH_MAP

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
OFFSET  = 0
RUNNING = False
RUNNING_SINCE = None
MAX_RUNNING_SECONDS = 60 * 60  # ค้างเกินนี้ถือว่า stuck (mount/rclone หลุดแบบไม่ raise) ปลดล็อกอัตโนมัติ
                                # ต้องนานกว่า rclone copy timeout (1800s ใน sort_slips.py) รวม gen+sync ด้วย ไม่งั้น auto-unlock ไวเกินไปตอนเน็ตช้าจริง
LOCK    = threading.Lock()

PENDING = None  # dict = wizard กำลังรอคำตอบอยู่ (ถามทีละคำถาม แทนให้พิมพ์ arg รวดเดียว)


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
        f"🔀 เดือนไม่ตรง  : {result.get('month_mismatch', 0)}",
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

    month_mismatch = [d for d in result.get("details", []) if d.get("status") == "month_mismatch"]
    if month_mismatch:
        exp = month_mismatch[0]
        msg = [
            f"🔀 <b>เดือนไม่ตรงกับที่คาดไว้ {len(month_mismatch)} ไฟล์</b>",
            f"คาดไว้ว่าเป็น {exp.get('expected_month')}/{exp.get('expected_year') or '?'}",
            "→ <code>unclassified/month_mismatch/</code> (เช็คมือ)",
            "─────────────────",
        ]
        for u in month_mismatch[:10]:
            msg.append(f"  - {u['file']} (อ่านได้ {u.get('month')}/{u.get('year')})")
        if len(month_mismatch) > 10:
            msg.append(f"  ... อีก {len(month_mismatch) - 10} ไฟล์")
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


def do_run(cmd: str, month: int | None = None, year: int | None = None):
    global RUNNING
    import sort_slips
    import gen_pdf
    import time
    from datetime import datetime

    try:
        if cmd == "/sort":
            t0 = time.time()
            month_note = f" (คาดเดือน {month}{f'/{year}' if year else ''})" if month else ""
            send(f"🚀 Sort เริ่มแล้ว{month_note} — {datetime.now().strftime('%H:%M:%S')}")
            result = sort_slips.run(expected_month=month, expected_year=year)
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
            # เรียก run_pipeline.main() ตรงๆ แทนการ duplicate logic เอง — กัน sort/gen ผ่าน
            # Telegram แล้วไม่ sync ขึ้น Drive / ลบ rawFile ทั้งที่ยังไม่ sync (บั๊กที่เจอมาก่อนหน้า)
            # run_pipeline.main() ส่ง notify.send() ของตัวเองอยู่แล้ว (Telegram bot เดียวกัน)
            from run_pipeline import main as run_pipeline_main
            run_pipeline_main(expected_month=month, expected_year=year)

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


def run_command(cmd: str, extra: str = "", month: int | None = None, year: int | None = None):
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
        t = threading.Thread(target=do_run, args=(cmd, month, year), daemon=True)
    t.start()


# ── Wizard: ถามทีละคำถามแทนต้องพิมพ์ arg รวดเดียว ────────────────────────────────

def start_month_wizard(cmd: str):
    """ใช้กับ /run, /sort — ถามแค่เดือน (0 = ไม่ระบุ)"""
    global PENDING
    PENDING = {"flow": "month_only", "cmd": cmd}
    send("ระบุเดือน (กรณีไม่ระบุ ใส่ 0) >")


def start_regen_wizard():
    """ใช้กับ /genYear, /genMonth, /genDay — ถามปี → เดือน (0=ทั้งปี) → วัน (0=ทั้งเดือน)"""
    global PENDING
    PENDING = {"flow": "regen", "step": "year"}
    send("ระบุปี >")


def handle_pending(text: str):
    """ประมวลผลคำตอบของ wizard ที่ค้างอยู่ (เรียกเมื่อข้อความไม่ขึ้นต้นด้วย / และมี PENDING)"""
    global PENDING
    if PENDING is None:
        return
    text = text.strip()
    flow = PENDING["flow"]

    if flow == "month_only":
        if not text.isdigit():
            send("ขอเป็นตัวเลขครับ (0 ถ้าไม่ระบุเดือน) >")
            return
        month = int(text)
        cmd = PENDING["cmd"]
        PENDING = None
        run_command(cmd, month=(month or None))
        return

    if flow == "regen":
        step = PENDING["step"]

        if step == "year":
            if not text.isdigit():
                send("ปีต้องเป็นตัวเลขครับ ลองใหม่ >")
                return
            PENDING["year"] = int(text)
            PENDING["step"] = "month"
            send("ระบุเดือน (กรณีต้องการทั้งปี ใส่ 0) >")
            return

        if step == "month":
            if not text.isdigit() or not (0 <= int(text) <= 12):
                send("เดือนต้องเป็นตัวเลข 0-12 ครับ ลองใหม่ >")
                return
            month = int(text)
            year  = PENDING["year"]
            if month == 0:
                scope = str(year)
                PENDING = None
                send(f"▶ regen ทั้งปี {scope}")
                run_command("/genyear", scope)
                return
            PENDING["month"] = month
            PENDING["step"] = "day"
            send("ระบุวัน (กรณีต้องการทั้งเดือน ใส่ 0) >")
            return

        if step == "day":
            if not text.isdigit():
                send("วันต้องเป็นตัวเลขครับ ลองใหม่ >")
                return
            day        = int(text)
            year       = PENDING["year"]
            month_name = MONTH_MAP.get(PENDING["month"], f"{PENDING['month']:02d}")
            PENDING = None
            if day == 0:
                scope = f"{year}/{month_name}"
                send(f"▶ regen ทั้งเดือน {scope}")
                run_command("/genmonth", scope)
            else:
                scope = f"{year}/{month_name}/{day:02d}"
                send(f"▶ regen วันเดียว {scope}")
                run_command("/genday", scope)
            return


def handle_command(text: str):
    global PENDING
    PENDING = None  # คำสั่งใหม่เข้ามา ยกเลิก wizard ค้างเก่าทิ้งไปเลย กันสับสน

    parts = text.strip().split()
    cmd   = parts[0].lower()
    extra = parts[1].lstrip("-") if len(parts) > 1 else ""

    if cmd == "/status":
        send(check_mounts())
    elif cmd == "/reloadvendor":
        from utils.vendor import reload_vendors
        vendors = reload_vendors()
        send(f"✅ Reload vendor สำเร็จ — มี {len(vendors)} รายการ")
    elif cmd in ("/run", "/sort"):
        if len(parts) > 1 and parts[1].isdigit():
            month = int(parts[1])
            year  = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            run_command(cmd, month=month, year=year)
        else:
            start_month_wizard(cmd)
    elif cmd == "/gen":
        run_command(cmd)
    elif cmd in ("/genyear", "/genmonth", "/genday"):
        if extra:
            run_command(cmd, extra)
        else:
            start_regen_wizard()
    elif cmd == "/help":
        send(
            "📋 <b>คำสั่งที่ใช้ได้</b>\n"
            "─────────────────\n"
            "/run   — รัน pipeline ทั้งหมด (ถามเดือนก่อนเริ่ม, 0=ไม่ระบุ) หรือพิมพ์ /run 7 เลยก็ได้\n"
            "/sort  — อ่าน slip + แยก folder เท่านั้น (ถามเดือนเหมือนกัน)\n"
            "/gen   — gen PDF เท่านั้น\n"
            "/genYear  — regen (ถามปี→เดือน→วัน ทีละขั้น) หรือพิมพ์ /genYear -2026 เลยก็ได้\n"
            "/genMonth — เหมือนกัน หรือพิมพ์ /genMonth -2026/JUN\n"
            "/genDay   — เหมือนกัน หรือพิมพ์ /genDay -2026/JUN/24\n"
            "/reloadvendor — โหลด vendor จาก GSheet ใหม่\n"
            "/status       — เช็คสถานะ mount\n"
            "/help         — แสดงคำสั่ง"
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
            text = msg.get("text", "")
            log(f"[recv] chat_id={chat_id!r} expected={str(TELEGRAM_CHAT_ID)!r} "
                f"text={text!r} pending={PENDING!r}")
            if chat_id != str(TELEGRAM_CHAT_ID):
                log("[recv] chat_id ไม่ตรง — ข้าม")
                continue
            if text.startswith("/"):
                log(f"[cmd] {text}")
                handle_command(text)
            elif PENDING is not None:
                log(f"[wizard answer] {text}")
                handle_pending(text)
        time.sleep(1)


if __name__ == "__main__":
    main()
