"""
notify.py — ส่งสรุปผลเข้า Line Notify
"""

import requests
from config import LINE_TOKEN


def send(message: str):
    """ส่งข้อความเข้า Line Notify"""
    if not LINE_TOKEN or LINE_TOKEN == "YOUR_LINE_NOTIFY_TOKEN":
        print(f"[Line] (token ยังไม่ตั้ง)\n{message}")
        return False
    try:
        r = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_TOKEN}"},
            data={"message": message},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[Line] error: {e}")
        return False


def build_summary_message(sort_result: dict, gen_result: dict) -> str:
    """สร้างข้อความสรุปสำหรับ Line"""
    lines = [
        "",
        "✅ Slip Processor เสร็จแล้ว",
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
    """แจ้งเตือนรูปที่จัดไม่ได้ ให้ไปจัดการ manual"""
    unclass = [d for d in sort_result.get("details", []) if d.get("status") == "unclassified"]
    if not unclass:
        return ""
    lines = [
        "",
        f"⚠️ มี {len(unclass)} รูปที่อ่านไม่ได้",
        "กรุณาจัดการ manual ใน folder unclassified/",
        "─────────────────",
    ]
    for u in unclass[:10]:  # แสดงแค่ 10 รายการแรก
        lines.append(f"  - {u['file']}")
    if len(unclass) > 10:
        lines.append(f"  ... อีก {len(unclass) - 10} ไฟล์")
    return "\n".join(lines)


def send_mount_alert(mount_point: str, status: str):
    """แจ้งเตือน mount หลุด"""
    send(f"\n🔴 Mount Alert\n{mount_point}\nสถานะ: {status}\nกำลัง remount...")
