"""
notify.py — ส่งแจ้งเตือนผ่าน Telegram Bot
วิธีสร้าง Bot:
  1. คุยกับ @BotFather ใน Telegram
  2. พิมพ์ /newbot → ตั้งชื่อ → ได้ BOT_TOKEN
  3. คุยกับ bot ของคุณก่อน 1 ครั้ง แล้วเปิด
     https://api.telegram.org/bot<TOKEN>/getUpdates
     → เอา "id" ใน chat มาใส่ CHAT_ID
"""

import requests
from config.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def send(message: str):
    """ส่งข้อความเข้า Telegram"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print(f"[Telegram] (token ยังไม่ตั้ง)\n{message}")
        return False
    try:
        r = requests.post(
            API_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[Telegram] error: {e}")
        return False


def build_summary_message(sort_result: dict, gen_result: dict) -> str:
    lines = [
        "✅ <b>Slip Processor เสร็จแล้ว</b>",
        "─────────────────",
        f"📥 รูปใหม่      : {sort_result.get('new', 0)}",
        f"⚠️  ซ้ำ          : {sort_result.get('duplicate', 0)}",
        f"❓ จัดไม่ได้    : {sort_result.get('unclassified', 0)}",
        f"📄 gen PDF     : {gen_result.get('new', 0)}",
    ]
    if gen_result.get("failed", 0):
        lines.append(f"❌ gen ล้มเหลว : {gen_result['failed']}")

    monthly = gen_result.get("monthly", {})
    if monthly:
        lines.append("─────────────────")
        lines.append("💰 ยอดรายจ่ายรอบนี้:")
        for m in sorted(monthly.keys()):
            lines.append(f"  {m}: ฿{monthly[m]:,.0f}")

    return "\n".join(lines)


def build_unclassified_message(sort_result: dict) -> str:
    unclass = [d for d in sort_result.get("details", []) if d.get("status") == "unclassified"]
    if not unclass:
        return ""
    lines = [
        f"⚠️ <b>มี {len(unclass)} รูปที่อ่านไม่ได้</b>",
        "กรุณาจัดการ manual ใน folder <code>unclassified/</code>",
        "─────────────────",
    ]
    for u in unclass[:10]:
        lines.append(f"  - {u['file']}")
    if len(unclass) > 10:
        lines.append(f"  ... อีก {len(unclass) - 10} ไฟล์")
    return "\n".join(lines)


def send_mount_alert(mount_point: str, status: str):
    send(f"🔴 <b>Mount Alert</b>\n<code>{mount_point}</code>\nสถานะ: {status}\nกำลัง remount...")
