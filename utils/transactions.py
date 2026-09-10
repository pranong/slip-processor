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
    "note", "amount", "has_receipt", "img_url", "cert_url", "receipt_url", "ref", "comment"
]

MONTH_NUM = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


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
            ws.format("A1:K1", {"textFormat": {"bold": True}})
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


def _open_sheet():
    """เปิด Sheet + client คืน (gc, drive, sh, ws) — retry 1 ครั้งกรณี Google API ชั่วคราวล่ม"""
    try:
        gc, drive = _get_clients()
        sh = gc.open_by_key(TRANSACTIONS_SHEET_ID)
        ws = sh.worksheet(TRANSACTIONS_SHEET_NAME)
        ensure_header(ws)
        return gc, drive, sh, ws
    except Exception as e:
        import time
        log(f"    ⚠️  เปิด Sheet ไม่สำเร็จ ({e}) — retry ใน 5 วิ...")
        time.sleep(5)
        gc, drive = _get_clients()
        sh = gc.open_by_key(TRANSACTIONS_SHEET_ID)
        ws = sh.worksheet(TRANSACTIONS_SHEET_NAME)
        ensure_header(ws)
        return gc, drive, sh, ws


def append_transactions(slips: list[dict], category: str,
                        cert_filename: str = "", receipt_filenames: dict[str, str] = None):
    """
    เพิ่ม transaction ลง Google Sheets — เรียกหลัง sync ขึ้น Drive เสร็จแล้วเท่านั้น

    ทำ 2 phase: (1) เขียนแถว (date/amount/note/ref ฯลฯ) ลง Sheet ก่อนทันที โดย**ไม่หา URL
    Drive เลย** (เร็วมาก ไม่มี Drive API call) (2) ค่อยหา URL (img/cert/receipt) แล้วกลับมา
    update เติมทีหลัง — กันปัญหาที่ Drive search ช้าแล้วทำให้ข้อมูลหลักช้าตามไปด้วย ข้อมูลเงิน/
    วันที่ปลอดภัยอยู่ใน Sheet ตั้งแต่ phase 1 แล้วต่อให้ phase 2 (หา URL) ช้าหรือพังก็ไม่กระทบ

    slips: list ของ slip dict จาก metadata
    category: บุคคล / uan / ceramic
    cert_filename: ชื่อไฟล์ใบรับรองฯ PDF เช่น 20260624-ใบรับรองแทนใบเสร็จรับเงิน.pdf
    receipt_filenames: dict {to_name: ชื่อไฟล์ใบสำคัญฯ}
    """
    if receipt_filenames is None:
        receipt_filenames = {}

    try:
        gc, drive, sh, ws = _open_sheet()
    except Exception as e2:
        log(f"    ❌ เปิด Transactions Sheet ไม่ได้ (retry แล้ว): {e2}")
        return

    # ── โหลด row ที่มีอยู่แล้ว จับคู่ด้วย ref (เลข transaction reference จากธนาคาร ไม่ซ้ำกัน
    # แน่นอน 100%) → เลข row จริงบน Sheet — เจอ ref เดิม = update ทับแถวนั้น ไม่ใช่ append ใหม่ ──
    try:
        all_values = ws.get_all_values()
    except Exception as e:
        log(f"    ❌ อ่าน Sheet ไม่ได้: {e}")
        return
    existing_rows = {}
    for row_num, row in enumerate(all_values[1:], start=2):  # แถว 1 = header, sheet เริ่ม index 2
        if len(row) >= 10 and row[9]:
            existing_rows[row[9]] = row_num

    # ── Phase 1: เขียนแถวก่อนเลย ไม่หา URL (has_receipt รู้ได้จาก dict receipt_filenames
    # ตรงๆ อยู่แล้ว ไม่ต้องเรียก Drive API เพื่อรู้ว่ามี receipt ไหม) ──
    updates  = []  # (row_num, values)
    new_rows = []  # values เฉยๆ ตามลำดับ
    url_jobs = []  # เก็บไว้ทำ phase 2: {row_num?, img_file, cert_filename, receipt_file}
    next_new_row = len(all_values) + 1  # แถวถัดไปที่ append_rows จะไปลง (append ต่อท้ายเสมอ)

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
        ref         = slip.get("ref") or ""

        img_file     = slip.get("dest_file") or slip.get("source_file", "")
        receipt_file = receipt_filenames.get(to_name, "")
        has_receipt  = "TRUE" if receipt_file else "FALSE"

        row = [date_str, category, vendor_name,
               note, amount, has_receipt, "", "", "", ref, ""]  # G/H/I (url) เว้นว่างไว้ก่อน

        if ref and ref in existing_rows:
            row_num = existing_rows[ref]
            updates.append((row_num, row))
        else:
            row_num = next_new_row + len(new_rows)
            new_rows.append(row)

        url_jobs.append({
            "row_num": row_num, "img_file": img_file,
            "cert_filename": cert_filename, "receipt_file": receipt_file,
        })

    if updates:
        try:
            batch = [{"range": f"A{row_num}:K{row_num}", "values": [row]} for row_num, row in updates]
            ws.batch_update(batch, value_input_option="USER_ENTERED")
            log(f"    🔄 update {len(updates)} rows เดิม")
        except Exception as e:
            log(f"    ❌ update rows ไม่สำเร็จ: {e}")
            return

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        log(f"    ✅ เพิ่ม {len(new_rows)} rows ใหม่ (ยังไม่มี URL — จะตามมาเติมต่อ)")

    if not updates and not new_rows:
        log("    ℹ️  ไม่มี transaction ให้บันทึก")
        return

    # ── Phase 2: หา URL จริงจาก Drive แล้วย้อนกลับมา update ทีละแถว ──
    cert_url_raw = _get_drive_link_by_name(drive, cert_filename) if cert_filename else ""
    cert_url = f'=HYPERLINK("{cert_url_raw}","{cert_filename}")' if cert_url_raw else ""

    url_updates = []
    for job in url_jobs:
        img_url = ""
        if job["img_file"]:
            img_url_raw = _get_drive_link_by_name(drive, job["img_file"])
            if img_url_raw:
                img_url = f'=HYPERLINK("{img_url_raw}","{job["img_file"]}")'
        receipt_url = ""
        if job["receipt_file"]:
            receipt_url_raw = _get_drive_link_by_name(drive, job["receipt_file"])
            if receipt_url_raw:
                receipt_url = f'=HYPERLINK("{receipt_url_raw}","{job["receipt_file"]}")'
        url_updates.append({
            "range": f"G{job['row_num']}:I{job['row_num']}",
            "values": [[img_url, cert_url, receipt_url]],
        })

    if url_updates:
        try:
            ws.batch_update(url_updates, value_input_option="USER_ENTERED")
            log(f"    🔗 เติม URL ให้ {len(url_updates)} rows เสร็จแล้ว")
        except Exception as e:
            log(f"    ⚠️  เติม URL ไม่สำเร็จ (ข้อมูลหลักลงแล้วปลอดภัย แค่ไม่มีลิงก์): {e}")


def _scope_to_date_prefix(scope_value: str) -> str:
    """'' -> '' (match ทุกวัน), '2026' -> '2026', '2026/JAN' -> '2026-01', '2026/JAN/07' -> '2026-01-07'"""
    if not scope_value:
        return ""
    parts = scope_value.strip("/").split("/")
    year = parts[0]
    if len(parts) == 1:
        return year
    month = MONTH_NUM.get(parts[1], parts[1])
    if len(parts) == 2:
        return f"{year}-{month}"
    day = parts[2].zfill(2)
    return f"{year}-{month}-{day}"


def void_rows_for_scope(scope_value: str) -> int:
    """
    Void แถวเดิมที่ date อยู่ใน scope และยัง "live" อยู่ (column comment ยังว่าง — ถ้ามี comment
    แล้วแปลว่าเคย void ไปแล้วรอบก่อน ข้ามไม่ void ซ้ำ กัน void วนไม่จบเวลา /genTransaction ถูก
    รันซ้ำ scope เดิม): zero amount (column E), ใส่ comment (column K) บอกยอดเดิม + เวลา,
    ไฮไลต์ทั้งแถวเป็นสีแดงอ่อน — ใช้ก่อน insert ชุดใหม่เข้าไปแทนของเดิม (ไม่ลบ ไม่ overwrite เงียบๆ)
    """
    from datetime import datetime

    try:
        gc, drive, sh, ws = _open_sheet()
    except Exception as e:
        log(f"    ❌ เปิด Transactions Sheet ไม่ได้: {e}")
        return 0

    try:
        all_values = ws.get_all_values()
    except Exception as e:
        log(f"    ❌ อ่าน Sheet ไม่ได้: {e}")
        return 0

    prefix = _scope_to_date_prefix(scope_value)
    to_void = []  # (row_num, old_amount)
    for row_num, row in enumerate(all_values[1:], start=2):
        if not row or not row[0].startswith(prefix):
            continue
        comment = row[10] if len(row) > 10 else ""
        if comment:
            continue  # void ไปแล้วรอบก่อน ข้าม
        old_amount = row[4] if len(row) > 4 else ""
        to_void.append((row_num, old_amount))

    if not to_void:
        log(f"    ℹ️  ไม่มีแถว live ให้ void ใน scope นี้")
        return 0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    value_updates = []
    for row_num, old_amount in to_void:
        value_updates.append({"range": f"E{row_num}", "values": [[0]]})
        value_updates.append({"range": f"K{row_num}", "values": [[f"({old_amount}) by /genTransaction @ {ts}"]]})
    ws.batch_update(value_updates, value_input_option="USER_ENTERED")

    format_requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": row_num - 1, "endRowIndex": row_num,
                    "startColumnIndex": 0, "endColumnIndex": 11,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8}}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        }
        for row_num, _ in to_void
    ]
    sh.batch_update({"requests": format_requests})

    log(f"    🔴 void {len(to_void)} rows (scope: {scope_value or 'ทั้งหมด'})")
    return len(to_void)
