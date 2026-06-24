"""
telegram_bot.py — รับคำสั่งจาก Telegram แล้วรัน pipeline
คำสั่งที่รองรับ:
  /run    — รัน pipeline ทั้งหมด (sort + gen)
  /sort   — รัน sort_slips เท่านั้น
  /gen    — รัน gen_pdf เท่านั้น
  /status — เช็คสถานะ mount
"""

import time
import requests
import subprocess
import threading
from pathlib import Path
from datetime import datetime

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RAW_MOUNT, DATA_MOUNT

API_URL  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
OFFSET   = 0
RUNNING  = False  # ป้องกันรันซ้อนกัน
LOCK     = threading.Lock()


def send(text: str):
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        print(f"[send error] {e}")


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


def run_command(cmd: str):
    """รัน pipeline command ใน background thread"""
    global RUNNING
    with LOCK:
        if RUNNING:
            send("⚠️ กำลังรันอยู่แล้ว รอให้เสร็จก่อนนะครับ")
            return
        RUNNING = True

    try:
        import sort_slips
        import gen_pdf
        import notify

        if cmd == "/sort":
            send("🔄 เริ่ม sort slip...")
            result = sort_slips.run()
            send(notify.build_sort_message(result) if hasattr(notify, 'build_sort_message') else
                 f"✅ Sort เสร็จ\nใหม่: {result.get('new',0)}  ซ้ำ: {result.get('duplicate',0)}  จัดไม่ได้: {result.get('unclassified',0)}")
            if result.get("unclassified", 0) > 0:
                send(notify.build_unclassified_message(result))

        elif cmd == "/gen":
            send("🔄 เริ่ม gen PDF...")
            result = gen_pdf.run()
            send(notify.build_gen_message(result) if hasattr(notify, 'build_gen_message') else
                 f"✅ Gen PDF เสร็จ\ngen ใหม่: {result.get('new',0)}  ล้มเหลว: {result.get('failed',0)}")

        elif cmd == "/run":
            send("🔄 เริ่ม pipeline ทั้งหมด...")

            # sort
            sort_result = sort_slips.run()
            msg = [
                "📥 <b>Sort เสร็จแล้ว</b>",
                "─────────────────",
                f"✅ ใหม่      : {sort_result.get('new', 0)}",
                f"⚠️  ซ้ำ       : {sort_result.get('duplicate', 0)}",
                f"❓ จัดไม่ได้ : {sort_result.get('unclassified', 0)}",
                f"❌ ล้มเหลว  : {sort_result.get('failed', 0)}",
            ]
            send("\n".join(msg))
            if sort_result.get("unclassified", 0) > 0:
                send(notify.build_unclassified_message(sort_result))

            # clear raw
            from run_pipeline import clear_raw_files
            clear_raw_files()

            # gen
            gen_result = gen_pdf.run()
            msg2 = [
                "📄 <b>Gen PDF เสร็จแล้ว</b>",
                "─────────────────",
                f"✅ gen ใหม่  : {gen_result.get('new', 0)}",
                f"❌ ล้มเหลว  : {gen_result.get('failed', 0)}",
            ]
            monthly = gen_result.get("monthly", {})
            if monthly:
                msg2.append("─────────────────")
                msg2.append("💰 ยอดรายจ่ายรอบนี้:")
                for m in sorted(monthly.keys()):
                    msg2.append(f"  {m}: ฿{monthly[m]:,.0f}")
            send("\n".join(msg2))

    except Exception as e:
        send(f"❌ เกิดข้อผิดพลาด\n<code>{e}</code>")
        import traceback
        print(traceback.format_exc())
    finally:
        with LOCK:
            global RUNNING
            RUNNING = False


def handle_command(text: str):
    cmd = text.strip().split()[0].lower()
    if cmd == "/status":
        send(check_mounts())
    elif cmd in ("/run", "/sort", "/gen"):
        t = threading.Thread(target=run_command, args=(cmd,), daemon=True)
        t.start()
    elif cmd == "/help":
        send(
            "📋 <b>คำสั่งที่ใช้ได้</b>\n"
            "─────────────────\n"
            "/run    — รัน pipeline ทั้งหมด\n"
            "/sort   — อ่าน slip + แยก folder\n"
            "/gen    — gen PDF เท่านั้น\n"
            "/status — เช็คสถานะ mount\n"
            "/help   — แสดงคำสั่ง"
        )
    else:
        send(f"❓ ไม่รู้จักคำสั่ง <code>{cmd}</code>\nพิมพ์ /help เพื่อดูคำสั่งทั้งหมด")


def main():
    global OFFSET
    print(f"🤖 Telegram Bot เริ่มทำงาน — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    send("🤖 <b>Slip Processor Bot พร้อมแล้ว!</b>\nพิมพ์ /help เพื่อดูคำสั่ง")

    while True:
        updates = get_updates(OFFSET)
        for update in updates:
            OFFSET = update["update_id"] + 1
            msg = update.get("message") or update.get("channel_post")
            if not msg:
                continue
            # เช็คว่าเป็น chat ที่อนุญาต
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue
            text = msg.get("text", "")
            if text.startswith("/"):
                print(f"[cmd] {text}")
                handle_command(text)
        time.sleep(1)


if __name__ == "__main__":
    main()
