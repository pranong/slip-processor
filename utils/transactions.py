"""
utils/transactions.py — บันทึก transaction ลง Google Sheets
พร้อม link รูปและ PDF จาก Google Drive
"""

import gspread
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from pathlib import Path
from config.config import (
    GSHEET_CREDENTIALS, TRANSACTIONS_SHEET_ID, TRANSACTIONS_SHEET_NAME
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

HEADERS = [
    "date", "year", "month", "category", "vendor_name",
    "note", "amount", "has_receipt", "img_url", "cert_url", "receipt_url"
]


def _get_clients():
    """สร้าง gspread และ Drive client จาก service account"""
    creds = Credentials.from_service_account_file(GSHEET_CREDENTIALS, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    drive = build("drive", "v3", credentials=creds)
    return gc, drive


def _get_drive_link(drive_client, path_in_drive: str) -> str:
    """
    หา Google Drive link จาก path เช่น
    SlipProcessor/data/2026/JUN/24/images/IMG_7484.JPG
    """
    try:
        parts = Path(path_in_drive).parts
        filename = parts[-1]
        # ค้นหาไฟล์ใน Drive ด้วยชื่อ
        result = drive_client.files().list(
            q=f"name='{filename}' and trashed=false",
            fields="files(id, name, webViewLink)",
        ).execute()
        files = result.get("files", [])
        if files:
            return files[0].get("webViewLink", "")
    except Exception as e:
        print(f"    ⚠️  Drive link error: {e}")
    return ""


def ensure_header(ws):
    """สร้าง header row ถ้ายังไม่มี"""
    try:
        first_row = ws.row_values(1)
        if first_row != HEADERS:
            ws.insert_row(HEADERS, 1)
            # format header bold
            ws.format("A1:K1", {"textFormat": {"bold": True}})
    except Exception:
        ws.insert_row(HEADERS, 1)


def append_transactions(slips: list[dict], category: str,
                        cert_path: str = "", receipt_paths: dict[str, str] = None):
    """
    เพิ่ม transaction ลง Google Sheets
    
    slips: list ของ slip dict จาก metadata
    category: บุคคล / uan / ceramic
    cert_path: Drive path ของใบรับรองฯ PDF
    receipt_paths: dict {to_name: Drive path ของใบสำคัญฯ}
    """
    if receipt_paths is None:
        receipt_paths = {}

    try:
        gc, drive = _get_clients()
        sh = gc.open_by_key(TRANSACTIONS_SHEET_ID)
        ws = sh.worksheet(TRANSACTIONS_SHEET_NAME)
        ensure_header(ws)
    except Exception as e:
        print(f"    ❌ เปิด Transactions Sheet ไม่ได้: {e}")
        return

    # หา link ใบรับรองฯ ครั้งเดียว (ใช้ร่วมกันทุก slip ของวันนั้น)
    cert_url = _get_drive_link(drive, cert_path) if cert_path else ""

    rows = []
    for slip in slips:
        day   = slip.get("day", "")
        month = slip.get("month", "")
        year  = slip.get("year_ce", "")
        date_str = f"{day:02d}/{month:02d}/{year}" if day and month and year else ""

        to_name     = slip.get("to_name") or slip.get("to_account", "")
        vendor      = slip.get("vendor", {})
        vendor_name = vendor.get("ชื่อ", to_name)
        note        = slip.get("note", "")
        amount      = slip.get("amount", 0)

        # หา link รูป slip
        img_file = slip.get("source_file", "")
        img_path = f"SlipProcessor/data/{year}/JUN/{day:02d}/images/{img_file}" if img_file else ""
        img_url  = _get_drive_link(drive, img_path) if img_path else ""

        # หา link ใบสำคัญฯ ของคนนี้
        receipt_url = ""
        if to_name in receipt_paths:
            receipt_url = _get_drive_link(drive, receipt_paths[to_name])

        has_receipt = "TRUE" if receipt_url else "FALSE"

        rows.append([
            date_str,
            str(year),
            slip.get("month_name", ""),
            category,
            vendor_name,
            note,
            amount,
            has_receipt,
            img_url,
            cert_url,
            receipt_url,
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"    ✅ บันทึก {len(rows)} transactions ลง Sheets")
