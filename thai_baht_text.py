"""
thai_baht_text.py — แปลงตัวเลขเป็นข้อความภาษาไทย (บาท/สตางค์)
เช่น 1250.50 → "หนึ่งพันสองร้อยห้าสิบบาทห้าสิบสตางค์"
"""

DIGITS = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
PLACES = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน"]


def _chunk_to_text(n: int) -> str:
    """แปลงจำนวนเต็ม 1-999999 เป็นข้อความไทย"""
    if n == 0:
        return ""
    text = ""
    s = str(n)
    length = len(s)
    for i, ch in enumerate(s):
        digit = int(ch)
        place = length - i - 1
        if digit == 0:
            continue
        if place == 1 and digit == 1:
            text += "สิบ"
        elif place == 1 and digit == 2:
            text += "ยี่สิบ"
        elif place == 0 and digit == 1 and length > 1:
            text += "เอ็ด"
        else:
            text += DIGITS[digit] + PLACES[place]
    return text


def baht_text(amount: float) -> str:
    """แปลงจำนวนเงินเป็นข้อความไทย เช่น 125 → 'หนึ่งร้อยยี่สิบห้าบาทถ้วน'"""
    if amount == 0:
        return "ศูนย์บาทถ้วน"

    amount = round(amount, 2)
    baht_part = int(amount)
    satang_part = round((amount - baht_part) * 100)

    result = ""

    # จัดการหลักล้าน
    if baht_part >= 1_000_000:
        millions = baht_part // 1_000_000
        remainder = baht_part % 1_000_000
        result += _chunk_to_text(millions) + "ล้าน"
        if remainder > 0:
            result += _chunk_to_text(remainder)
    else:
        result += _chunk_to_text(baht_part)

    result += "บาท"

    if satang_part == 0:
        result += "ถ้วน"
    else:
        result += _chunk_to_text(satang_part) + "สตางค์"

    return result


if __name__ == "__main__":
    tests = [0, 1, 11, 21, 100, 101, 125, 1000, 12345, 100000, 1000000, 1234567.50, 350.75]
    for t in tests:
        print(f"  {t:>12,.2f} → {baht_text(t)}")
