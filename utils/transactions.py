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
    "date", "category", "vendor_name",
    "note", "amount", "has_receipt", "img_url", "cert_url", "receipt_url"
]


def _get_clients():
    """สร้าง gspread และ Drive client จาก service account"""
    creds = Credentials.from_service_account_file(GSHEET_CREDENTIALS, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    drive = build("drive", "v3", credentials=creds)
    return gc, drive


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
                        cert_filename: str = "", receipt_filenames: dict[str, str] = None):
    """
    เพิ่ม transaction ลง Google Sheets — เรียกหลัง sync ขึ้น Drive เสร็จแล้วเท่านั้น
    
    slips: list ของ slip dict จาก metadata
    category: บุคคล / uan / ceramic
    cert_filename: ชื่อไฟล์ใบรับรองฯ PDF เช่น 20260624-ใบรับรองแทนใบเสร็จรับเงิน.pdf
    receipt_filenames: dict {to_name: ชื่อไฟล์ใบสำคัญฯ}
    """
    if receipt_filenames is None:
        receipt_filenames = {}

    try:
        gc, drive = _get_clients()
        sh = gc.open_by_key(TRANSACTIONS_SHEET_ID)
        ws = sh.worksheet(TRANSACTIONS_SHEET_NAME)
        ensure_header(ws)
    except Exception as e:
        print(f"    ❌ เปิด Transactions Sheet ไม่ได้: {e}")
        return

    cert_url = _get_drive_link_by_name(drive, cert_filename) if cert_filename else ""

    rows = []
    for slip in slips:
        day   = slip.get("day", "")
        month = slip.get("month", "")
        year  = slip.get("year_ce", "")
        date_str = f"{year}-{month:02d}-{day:02d}" if (day and month and year) else ""

        to_name     = slip.get("to_name") or slip.get("to_account", "")
        vendor      = slip.get("vendor", {})
        vendor_name = vendor.get("ชื่อ", to_name)
        note        = slip.get("note", "")
        amount      = slip.get("amount", 0)

        img_file = slip.get("dest_file") or slip.get("source_file", "")
        img_url  = _get_drive_link_by_name(drive, img_file) if img_file else ""

        receipt_url = ""
        if to_name in receipt_filenames:
            receipt_url = _get_drive_link_by_name(drive, receipt_filenames[to_name])

        has_receipt = "TRUE" if receipt_url else "FALSE"

        rows.append([
            date_str, category, vendor_name,
            note, amount, has_receipt, img_url, cert_url, receipt_url,
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"    ✅ บันทึก {len(rows)} transactions ลง Sheets")


def _get_drive_link_by_name(drive_client, filename: str) -> str:
    """ค้นหาไฟล์ใน Drive จากชื่อไฟล์ตรงๆ"""
    if not filename:
        return ""
    try:
        result = drive_client.files().list(
            q=f"name='{filename}' and trashed=false",
            fields="files(id, name, webViewLink)",
        ).execute()
        files = result.get("files", [])
        if files:
            return files[0].get("webViewLink", "")
    except Exception as e:
        print(f"    ⚠️  Drive link error ({filename}): {e}")
    return ""
