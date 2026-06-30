"""
utils/transactions.py — บันทึก transaction ลง Google Sheets
พร้อม link รูปและ PDF จาก Google Drive
"""

import gspread
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
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
            ws.format("A1:I1", {"textFormat": {"bold": True}})
    except Exception:
        ws.insert_row(HEADERS, 1)


def clear_transactions():
    """ลบข้อมูลทั้งหมดใน Transactions Sheet (เก็บ header ไว้) พร้อมล้าง filter/named range เก่า"""
    try:
        gc, drive = _get_clients()
        sh = gc.open_by_key(TRANSACTIONS_SHEET_ID)
        ws = sh.worksheet(TRANSACTIONS_SHEET_NAME)

        # ลบ basic filter (ถ้ามี) ก่อน clear เนื้อหา
        try:
            ws.clear_basic_filter()
        except Exception:
            pass

        ws.clear()

        # ลบ format/border เก่าทั้งหมด (กันกรอบเขียวค้าง)
        try:
            sh.batch_update({
                "requests": [{
                    "updateCells": {
                        "range": {"sheetId": ws.id},
                        "fields": "userEnteredFormat",
                    }
                }]
            })
        except Exception:
            pass

        # ลบ filter views ที่ค้างอยู่ (ถ้ามี) ผ่าน batchUpdate
        try:
            sheet_id = ws.id
            spreadsheet_meta = sh.fetch_sheet_metadata()
            for sheet in spreadsheet_meta.get("sheets", []):
                if sheet["properties"]["sheetId"] != sheet_id:
                    continue
                filter_views = sheet.get("filterViews", [])
                requests = [
                    {"deleteFilterView": {"filterId": fv["filterViewId"]}}
                    for fv in filter_views
                ]
                if requests:
                    sh.batch_update({"requests": requests})
        except Exception as e:
            print(f"    ⚠️  ลบ filter views ไม่ได้: {e}")

        ensure_header(ws)
        print("✅ Clear Transactions Sheet เสร็จแล้ว (รวม filter/format)")
    except Exception as e:
        print(f"❌ Clear Transactions Sheet ไม่ได้: {e}")


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
            url = files[0].get("webViewLink", "")
            print(f"      🔗 พบไฟล์ '{filename}' → {url}")
            return url
        else:
            print(f"      ❌ ไม่พบไฟล์ '{filename}' บน Drive")
    except Exception as e:
        print(f"      ⚠️  Drive link error ({filename}): {e}")
    return ""


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

    cert_url_raw = _get_drive_link_by_name(drive, cert_filename) if cert_filename else ""
    cert_url = f'=HYPERLINK("{cert_url_raw}","{cert_filename}")' if cert_url_raw else ""

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
        img_url_raw  = _get_drive_link_by_name(drive, img_file) if img_file else ""
        img_url  = f'=HYPERLINK("{img_url_raw}","{img_file}")' if img_url_raw else ""

        receipt_url_raw = ""
        if to_name in receipt_filenames:
            receipt_url_raw = _get_drive_link_by_name(drive, receipt_filenames[to_name])
        receipt_url = (
            f'=HYPERLINK("{receipt_url_raw}","{receipt_filenames.get(to_name, "")}")'
            if receipt_url_raw else ""
        )

        has_receipt = "TRUE" if receipt_url_raw else "FALSE"

        rows.append([
            date_str, category, vendor_name,
            note, amount, has_receipt, img_url, cert_url, receipt_url,
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"    ✅ บันทึก {len(rows)} transactions ลง Sheets")
