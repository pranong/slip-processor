"""
utils/transactions.py — บันทึก transaction ลง Google Sheets
พร้อม link รูปและ PDF จาก Google Drive
"""

import gspread
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from utils.logger import log
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
            log(f"    ⚠️  ลบ filter views ไม่ได้: {e}")

        ensure_header(ws)
        log("✅ Clear Transactions Sheet เสร็จแล้ว (รวม filter/format)")
    except Exception as e:
        log(f"❌ Clear Transactions Sheet ไม่ได้: {e}")


SLIP_PROCESSOR_FOLDER = None  # cache folder ID


def _get_folder_id(drive_client, folder_name: str, parent_id: str = None) -> str:
    """หา folder ID จากชื่อ"""
    q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    result = drive_client.files().list(q=q, fields="files(id)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else ""


def _get_root_folder_id(drive_client) -> str:
    """หา SlipProcessor folder ID (cache ไว้)"""
    global SLIP_PROCESSOR_FOLDER
    if SLIP_PROCESSOR_FOLDER:
        return SLIP_PROCESSOR_FOLDER
    SLIP_PROCESSOR_FOLDER = _get_folder_id(drive_client, "SlipProcessor")
    return SLIP_PROCESSOR_FOLDER


def _get_drive_link_by_name(drive_client, filename: str) -> str:
    """ค้นหาไฟล์ใน Drive ภายใน SlipProcessor folder"""
    if not filename:
        return ""
    try:
        root_id = _get_root_folder_id(drive_client)
        # search ภายใน SlipProcessor subtree
        q = f"name='{filename}' and trashed=false"
        if root_id:
            # ใช้ corpora=allDrives ไม่ได้กับ service account ธรรมดา
            # แต่ถ้า search ทั้ง Drive แล้วเจอหลายไฟล์ จะเลือกผิด
            # ดังนั้น search ทั้งหมดแล้ว filter ด้วย parents chain
            pass
        result = drive_client.files().list(
            q=q,
            fields="files(id, name, webViewLink, parents)",
        ).execute()
        files = result.get("files", [])
        if len(files) == 1:
            url = files[0].get("webViewLink", "")
            log(f"      🔗 พบไฟล์ '{filename}' → {url}")
            return url
        elif len(files) > 1 and root_id:
            # หลายไฟล์ชื่อเดียวกัน — เลือกอันที่อยู่ใน SlipProcessor
            for f in files:
                if _is_in_folder(drive_client, f.get("id", ""), root_id):
                    url = f.get("webViewLink", "")
                    log(f"      🔗 พบไฟล์ '{filename}' (filtered) → {url}")
                    return url
            # ถ้าหาไม่เจอใน folder ก็ return ตัวแรก
            url = files[0].get("webViewLink", "")
            log(f"      🔗 พบไฟล์ '{filename}' (fallback) → {url}")
            return url
        else:
            log(f"      ❌ ไม่พบไฟล์ '{filename}' บน Drive")
    except Exception as e:
        log(f"      ⚠️  Drive link error ({filename}): {e}")
    return ""


def _is_in_folder(drive_client, file_id: str, target_folder_id: str, depth: int = 5) -> bool:
    """เช็คว่าไฟล์อยู่ภายใน folder (traverse parents ขึ้นไป)"""
    current = file_id
    for _ in range(depth):
        try:
            f = drive_client.files().get(fileId=current, fields="parents").execute()
            parents = f.get("parents", [])
            if not parents:
                return False
            if target_folder_id in parents:
                return True
            current = parents[0]
        except Exception:
            return False
    return False


def _norm_amount(val) -> float | None:
    """แปลงเป็นตัวเลขมาตรฐานสำหรับเทียบ key — กัน '11,155' (ที่ Sheets แสดงมีลูกน้ำ) ไม่ match กับ 11155"""
    try:
        return round(float(str(val).replace(",", "")), 2)
    except (ValueError, TypeError):
        return None


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
        # retry 1 ครั้งกรณี Google API ชั่วคราวล่ม (503)
        import time
        log(f"    ⚠️  เปิด Sheet ไม่สำเร็จ ({e}) — retry ใน 5 วิ...")
        time.sleep(5)
        try:
            gc, drive = _get_clients()
            sh = gc.open_by_key(TRANSACTIONS_SHEET_ID)
            ws = sh.worksheet(TRANSACTIONS_SHEET_NAME)
            ensure_header(ws)
        except Exception as e2:
            log(f"    ❌ เปิด Transactions Sheet ไม่ได้ (retry แล้ว): {e2}")
            return

    cert_url_raw = _get_drive_link_by_name(drive, cert_filename) if cert_filename else ""
    cert_url = f'=HYPERLINK("{cert_url_raw}","{cert_filename}")' if cert_url_raw else ""

    # ── โหลด row ที่มีอยู่แล้ว จับคู่ (date, category, vendor_name, note, amount) → เลข row จริงบน Sheet ──
    # เจอ key เดิม = update ทับแถวนั้น ไม่ใช่ลบทั้ง bucket แล้ว append ใหม่
    try:
        all_values = ws.get_all_values()
    except Exception as e:
        log(f"    ❌ อ่าน Sheet ไม่ได้: {e}")
        return
    existing_rows = {}
    for row_num, row in enumerate(all_values[1:], start=2):  # แถว 1 = header, sheet เริ่ม index 2
        if len(row) >= 5:
            amt = _norm_amount(row[4])
            if amt is not None:
                existing_rows[(row[0], row[1], row[2], row[3], amt)] = row_num

    updates  = []  # (row_num, values)
    new_rows = []
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

        row = [date_str, category, vendor_name,
               note, amount, has_receipt, img_url, cert_url, receipt_url]

        key = (date_str, category, vendor_name, note, _norm_amount(amount))
        if key in existing_rows:
            updates.append((existing_rows[key], row))
        else:
            new_rows.append(row)

    if updates:
        try:
            batch = [{"range": f"A{row_num}:I{row_num}", "values": [row]} for row_num, row in updates]
            ws.batch_update(batch, value_input_option="USER_ENTERED")
            log(f"    🔄 update {len(updates)} rows เดิม")
        except Exception as e:
            log(f"    ❌ update rows ไม่สำเร็จ: {e}")
            return

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        log(f"    ✅ เพิ่ม {len(new_rows)} rows ใหม่")

    if not updates and not new_rows:
        log("    ℹ️  ไม่มี transaction ให้บันทึก")
