"""
utils/vendor.py — โหลด vendor data จาก Google Sheets + fuzzy match
"""

import gspread
from rapidfuzz import fuzz, process
from config.config import (
    GSHEET_CREDENTIALS, GSHEET_ID,
    VENDOR_SHEET_NAME, FUZZY_THRESHOLD
)

_vendor_cache: list[dict] | None = None


def load_vendors(force_reload: bool = False) -> list[dict]:
    """โหลด vendor list จาก GSheet — cache ไว้ใน memory"""
    global _vendor_cache
    if _vendor_cache is not None and not force_reload:
        return _vendor_cache
    try:
        gc      = gspread.service_account(filename=GSHEET_CREDENTIALS)
        sh      = gc.open_by_key(GSHEET_ID)
        ws      = sh.worksheet(VENDOR_SHEET_NAME)
        records = ws.get_all_records()
        _vendor_cache = records
        print(f"✅ โหลด vendor {len(records)} รายการจาก GSheet")
        return records
    except Exception as e:
        print(f"❌ โหลด GSheet ไม่ได้: {e}")
        return []


def find_vendor(to_account: str, vendors: list[dict] | None = None) -> dict | None:
    """หา vendor จากชื่อผู้รับใน slip — 3 ชั้น"""
    if vendors is None:
        vendors = load_vendors()
    if not vendors or not to_account:
        return None

    name_lower = to_account.lower().strip()

    # ชั้น 1: exact
    for v in vendors:
        if v.get("ชื่อ", "").lower().strip() == name_lower:
            return v

    # ชั้น 2: substring
    for v in vendors:
        vname = v.get("ชื่อ", "").lower().strip()
        if vname in name_lower or name_lower in vname:
            return v

    # ชั้น 3: fuzzy
    names  = [v.get("ชื่อ", "") for v in vendors]
    result = process.extractOne(
        to_account, names,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )
    if result:
        for v in vendors:
            if v.get("ชื่อ") == result[0]:
                print(f"    🔍 fuzzy match: '{to_account}' → '{result[0]}' ({result[1]:.0f}%)")
                return v
    return None


def auto_add_vendor(name: str) -> bool:
    """
    เพิ่มชื่อ vendor ใหม่เข้า GSheet (ชื่ออย่างเดียว รอกรอกรายละเอียดทีหลัง)
    ถ้ามีชื่อนี้อยู่แล้วจะไม่เพิ่มซ้ำ
    """
    try:
        vendors  = load_vendors(force_reload=True)
        existing = [v.get("ชื่อ", "").strip().lower() for v in vendors]
        if name.strip().lower() in existing:
            print(f"    ℹ️  '{name}' มีอยู่แล้วใน GSheet")
            return False

        gc = gspread.service_account(filename=GSHEET_CREDENTIALS)
        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(VENDOR_SHEET_NAME)
        ws.append_row([name, "", "", "", "", "", "", "", "", ""])
        print(f"    ✅ เพิ่ม '{name}' เข้า GSheet แล้ว")

        global _vendor_cache
        _vendor_cache = None
        return True
    except Exception as e:
        print(f"    ❌ เพิ่ม vendor ไม่ได้: {e}")
        return False


def reload_vendors():
    """force reload vendor cache จาก GSheet"""
    global _vendor_cache
    _vendor_cache = None
    return load_vendors()
