"""
gen_pdf.py — gen PDF ใบรับรองแทนใบเสร็จรับเงิน จาก template .docx
- อ่าน slip_data JSON ที่ sort_slips.py สร้างไว้ (ไม่ call Claude API ซ้ำ)
- clone row ในตาราง + เติมข้อมูล
- gen 1 PDF ต่อ batch ใหม่แต่ละวัน
- merge summary.json
"""

import json
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn

from config.config import DATA_MOUNT, TEMPLATE_DIR, TEMPLATE_PATH, MONTH_MAP
from config.gen_config import NOTE_ROUTES, NOTE_DEFAULT_SUBFOLDER, NOTE_DEFAULT_TEMPLATE
from utils.thai_baht_text import baht_text
from utils.state import load_state, save_state, mark_generated, is_generated
from utils.vendor import find_vendor, load_vendors

MONTH_MAP_NUM = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

# ── Routing ───────────────────────────────────────────────────────────────────
# ย้ายไปอยู่ที่ config.py แล้ว — เพิ่ม/ลด keyword ได้ที่นั่น


def get_route(note: str) -> dict:
    """หา subfolder และ template จาก note — เจอ keyword ที่ไหนก็ได้ ไม่ case sensitive"""
    note_lower = (note or "").lower()
    for route in NOTE_ROUTES:
        if route["keyword"].lower() in note_lower:
            return {
                "subfolder": route["subfolder"],
                "template":  Path(TEMPLATE_DIR) / route["template"],
            }
    return {
        "subfolder": NOTE_DEFAULT_SUBFOLDER,
        "template":  Path(TEMPLATE_DIR) / NOTE_DEFAULT_TEMPLATE,
    }

# ── Summary ───────────────────────────────────────────────────────────────────

def _summary_path(year_dir: Path) -> Path:
    return year_dir / "summary.json"


def load_summary(year_dir: Path) -> dict:
    p = _summary_path(year_dir)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_summary(year_dir: Path, summary: dict):
    # backup ก่อน
    p = _summary_path(year_dir)
    if p.exists():
        bak_dir = year_dir / "backups"
        bak_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(p, bak_dir / f"summary_{ts}.json")

    p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_to_summary(summary: dict, month_key: str, day_str: str,
                     slips: list[dict], pdf_name: str):
    """เพิ่ม transaction เข้า summary แบบ merge"""
    if month_key not in summary:
        summary[month_key] = {"total": 0, "count": 0, "transactions": []}

    for s in slips:
        amt = s.get("amount") or 0
        summary[month_key]["total"] += amt
        summary[month_key]["count"] += 1
        summary[month_key]["transactions"].append({
            "date":        f"{s.get('day',''):02d}/{month_key}/{s.get('year_ce','')}",
            "amount":      amt,
            "description": s.get("description"),
            "from":        s.get("from_account"),
            "to":          s.get("to_account"),
            "bank":        s.get("bank"),
            "ref":         s.get("ref"),
            "pdf":         pdf_name,
        })

# ── DOCX template fill ────────────────────────────────────────────────────────

def _clone_row(table, row_idx: int):
    """clone row ในตาราง (XML level) แล้ว insert หลัง row เดิม"""
    src_tr = table.rows[row_idx]._tr
    new_tr = deepcopy(src_tr)
    src_tr.addnext(new_tr)
    return new_tr


def _set_cell_text(row_element, col_idx: int, text: str):
    """เขียนข้อความลง cell โดยรักษา format เดิม"""
    cells = row_element.findall(qn("w:tc"))
    if col_idx >= len(cells):
        return
    cell = cells[col_idx]
    # หา paragraph แรก
    para = cell.find(qn("w:p"))
    if para is None:
        return
    # หา run แรก (ถ้ามี) เพื่อเอา format
    runs = para.findall(qn("w:r"))
    if runs:
        # ลบ run เดิมทั้งหมด
        for r in runs:
            para.remove(r)
        # สร้าง run ใหม่ด้วย format เดิม
        new_run = deepcopy(runs[0])
        # เปลี่ยนข้อความ
        t_elem = new_run.find(qn("w:t"))
        if t_elem is not None:
            t_elem.text = text
            t_elem.set(qn("xml:space"), "preserve")
        para.append(new_run)
    else:
        # ไม่มี run — สร้างใหม่
        from docx.oxml import OxmlElement
        run = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        run.append(t)
        para.append(run)


def _replace_across_runs(paragraph, placeholder: str, value: str):
    """แทน placeholder ที่อาจกระจายหลาย runs — merge เฉพาะ runs ที่มี placeholder"""
    runs = paragraph.runs
    if not runs:
        return
    full_text = "".join(r.text for r in runs)
    if placeholder not in full_text:
        return

    # หาว่า placeholder เริ่มและจบที่ run ไหน
    pos = full_text.index(placeholder)
    end_pos = pos + len(placeholder)

    char_count = 0
    start_run = None
    end_run = None
    for i, r in enumerate(runs):
        run_start = char_count
        run_end = char_count + len(r.text)
        if start_run is None and run_end > pos:
            start_run = i
        if run_end >= end_pos:
            end_run = i
            break
        char_count = run_end

    if start_run is None or end_run is None:
        return

    # รวมข้อความเฉพาะ runs ที่มี placeholder
    merged = "".join(runs[i].text for i in range(start_run, end_run + 1))
    merged = merged.replace(placeholder, value)

    # ใส่กลับใน run แรกของกลุ่ม ลบ run ที่เหลือในกลุ่ม
    runs[start_run].text = merged
    for i in range(start_run + 1, end_run + 1):
        runs[i].text = ""


def _replace_text_in_doc(doc: DocxDocument, placeholder: str, value: str):
    """แทน placeholder ทั่วทั้ง document (paragraphs + table cells)"""
    for para in doc.paragraphs:
        if placeholder in para.text:
            _replace_across_runs(para, placeholder, value)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    if placeholder in para.text:
                        _replace_across_runs(para, placeholder, value)


def fill_template(slips: list[dict], day_str: str, month_name: str,
                  year_thai: str, template_path: Path | None = None) -> Path | None:
    """เติมข้อมูลลง template, return path ของ docx ที่ fill แล้ว"""
    template = template_path if template_path else Path(TEMPLATE_PATH)
    if not template.exists():
        print(f"    ⚠️  ไม่พบ template: {template}")
        return None

    doc = DocxDocument(str(template))

    # หาตารางแรก
    if not doc.tables:
        print("    ⚠️  ไม่พบตารางใน template")
        return None
    table = doc.tables[0]

    # หา row ที่มี $date[0] (template row)
    template_row_idx = None
    total_row_idx = None
    for idx, row in enumerate(table.rows):
        row_text = "".join(cell.text for cell in row.cells)
        if "$date[0]" in row_text:
            template_row_idx = idx
        if "$intSumTotal" in row_text:
            total_row_idx = idx

    if template_row_idx is None:
        print("    ⚠️  ไม่พบ $date[0] ใน template")
        return None

    # ── เติมข้อมูล ──
    # ถ้ามีมากกว่า 1 slip ต้อง clone row เพิ่ม
    # clone ก่อน (จาก row template) แล้วค่อยเติม
    if len(slips) > 1:
        for _ in range(len(slips) - 1):
            _clone_row(table, template_row_idx)

    # เติมข้อมูลแต่ละ row
    total = 0
    for i, slip in enumerate(slips):
        row_idx = template_row_idx + i
        tr = table.rows[row_idx]._tr

        day_val  = slip.get("day", "")
        mon_val  = slip.get("month", "")
        year_val = slip.get("year_ce", "")
        # แปลงเป็น พ.ศ.
        year_be  = year_val + 543 if isinstance(year_val, int) else ""
        date_str = f"{day_val}/{mon_val}/{year_be}" if day_val else ""
        desc_str = slip.get("note") or slip.get("description") or "-"
        amt      = slip.get("amount") or 0
        amt_str  = f"{amt:,.2f}"
        total   += amt

        _set_cell_text(tr, 0, date_str)    # วัน เดือน ปี
        _set_cell_text(tr, 1, desc_str)    # รายละเอียดการจ่าย
        _set_cell_text(tr, 2, amt_str)     # จำนวนเงิน
        # col 3 (หมายเหตุ) — ว่าง

    # เติม total row
    total_str    = f"{total:,.2f}"
    total_th_str = baht_text(total)

    # วันที่ของเอกสาร (fromDate = toDate = วันนี้ เพราะ gen ต่อวัน)
    # ดึงจาก slip แรกใน list
    first = slips[0] if slips else {}
    day_v  = first.get("day", "")
    mon_v  = first.get("month", "")
    yr_v   = first.get("year_ce", "")
    yr_be  = yr_v + 543 if isinstance(yr_v, int) else ""
    doc_date = f"{day_v}/{mon_v}/{yr_be}" if day_v else ""

    # แทน placeholders ทั้งหมด (รองรับ split across runs)
    _replace_text_in_doc(doc, "$intSumTotal", total_str)
    _replace_text_in_doc(doc, "$thSumTotal", total_th_str)
    _replace_text_in_doc(doc, "$fromDate", doc_date)
    _replace_text_in_doc(doc, "$toDate", doc_date)

    # บันทึก docx ชั่วคราว
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / f"filled_{month_name}_{day_str}.docx"
    doc.save(str(tmp))
    return tmp


def fill_template_receipt(slips: list[dict], day_str: str, month_name: str,
                          year_thai: str) -> Path | None:
    """
    เติมข้อมูลลง template ใบสำคัญรับเงิน
    placeholder ต่างจากใบรับรองฯ:
    - vendor info: $vndName, $vndId, $vndAddress, $vndM, $vndSt, $vndZone, $vndCity, $vndProv
    - ตาราง: $desc[0], $amountF[0], $amountSt[0]
    - รวม: $intSumFTotal, $intSumStTotal, $thSumTotal
    """
    template_path = Path(TEMPLATE_DIR) / "ใบสำคัญรับเงิน.docx"
    if not template_path.exists():
        print(f"    ⚠️  ไม่พบ template: {template_path}")
        return None

    doc = DocxDocument(str(template_path))

    if not doc.tables:
        print("    ⚠️  ไม่พบตารางใน template ใบสำคัญรับเงิน")
        return None

    # ── vendor info (จาก slip แรก — vendor เดียวกันทั้งวัน) ──
    first   = slips[0] if slips else {}
    vendor  = first.get("vendor") or {}
    day_v   = first.get("day", "")
    mon_v   = first.get("month", "")
    yr_v    = first.get("year_ce", "")
    yr_be   = yr_v + 543 if isinstance(yr_v, int) else ""
    doc_date = f"{day_v}/{mon_v}/{yr_be}" if day_v else ""

    # แทน vendor placeholders
    _replace_text_in_doc(doc, "$fromDate",   doc_date)
    _replace_text_in_doc(doc, "$vndName",    vendor.get("ชื่อ", "-"))
    _replace_text_in_doc(doc, "$vndId",      str(vendor.get("เลขผู้เสียภาษี", "-")))
    _replace_text_in_doc(doc, "$vndAddress", str(vendor.get("บ้านเลขที่", "-")))
    _replace_text_in_doc(doc, "$vndM",       str(vendor.get("หมู่", "-")))
    _replace_text_in_doc(doc, "$vndSt",      str(vendor.get("ถนน", "-")))
    _replace_text_in_doc(doc, "$vndZone",    str(vendor.get("แขวง/ตำบล", "-")))
    _replace_text_in_doc(doc, "$vndCity",    str(vendor.get("เขต/อำเภอ", "-")))
    _replace_text_in_doc(doc, "$vndProv",    str(vendor.get("จังหวัด", "-")))

    # ── หาตาราง item (ที่มี $desc[0]) ──
    item_table = None
    for t in doc.tables:
        text = "".join(cell.text for row in t.rows for cell in row.cells)
        if "$desc[0]" in text:
            item_table = t
            break

    if item_table is None:
        print("    ⚠️  ไม่พบตาราง item ใน template ใบสำคัญรับเงิน")
        return None

    # หา template row
    template_row_idx = None
    for idx, row in enumerate(item_table.rows):
        if "$desc[0]" in "".join(cell.text for cell in row.cells):
            template_row_idx = idx
            break

    if template_row_idx is None:
        return None

    # clone rows
    if len(slips) > 1:
        for _ in range(len(slips) - 1):
            _clone_row(item_table, template_row_idx)

    # เติมข้อมูลแต่ละ row
    total = 0
    for i, slip in enumerate(slips):
        tr      = item_table.rows[template_row_idx + i]._tr
        amt     = slip.get("amount") or 0
        amt_f   = int(amt)                              # บาท
        amt_st  = round((amt - amt_f) * 100)           # สตางค์
        desc    = slip.get("note") or slip.get("description") or "-"
        total  += amt

        _set_cell_text(tr, 0, desc)                    # รายการ
        _set_cell_text(tr, 1, f"{amt_f:,}")            # บาท
        _set_cell_text(tr, 2, f"{amt_st:02d}")         # สตางค์

    # รวม
    total_f  = int(total)
    total_st = round((total - total_f) * 100)

    _replace_text_in_doc(doc, "$intSumFTotal",  f"{total_f:,}")
    _replace_text_in_doc(doc, "$intSumStTotal", f"{total_st:02d}")
    _replace_text_in_doc(doc, "$thSumTotal",    baht_text(total))

    import tempfile
    tmp = Path(tempfile.mkdtemp()) / f"receipt_{month_name}_{day_str}.docx"
    doc.save(str(tmp))
    return tmp


def convert_to_pdf(docx_path: Path, output_dir: Path) -> Path | None:
    """แปลง docx เป็น PDF ด้วย LibreOffice"""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf",
             "--outdir", str(output_dir), str(docx_path)],
            capture_output=True, text=True, timeout=120
        )
        pdf_name = docx_path.stem + ".pdf"
        pdf_path = output_dir / pdf_name
        if pdf_path.exists():
            return pdf_path
        print(f"    ⚠️  LibreOffice error: {result.stderr[:200]}")
    except Exception as e:
        print(f"    ⚠️  Convert error: {e}")
    return None

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    data_root = Path(DATA_MOUNT)
    results   = {"new": 0, "skip": 0, "failed": 0, "monthly": {}}
    state     = load_state()

    # โหลด vendor list ครั้งเดียว
    vendors = load_vendors(force_reload=True)

    # วน loop ปี/เดือน/วัน
    for year_dir in sorted(data_root.iterdir()):
        if not year_dir.is_dir() or year_dir.name in ("unclassified", "backups", "logs"):
            continue

        summary = load_summary(year_dir)

        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue

            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue

                images_dir   = day_dir / "images"
                metadata_dir = day_dir / "metadata"

                if not images_dir.exists():
                    continue

                # ── copy metadata มา local temp ก่อนอ่าน (เร็วกว่าอ่านจาก mount ทีละไฟล์) ──
                import tempfile, shutil as _shutil
                json_dir  = metadata_dir if metadata_dir.exists() else images_dir
                local_tmp = Path(tempfile.mkdtemp())
                try:
                    for jf in sorted(json_dir.glob("*.json")):
                        _shutil.copy(str(jf), str(local_tmp / jf.name))
                except Exception as e:
                    print(f"    ⚠️  copy metadata error: {e}")

                # หา slip JSON ทั้งหมดจาก local temp
                all_slips = []
                for jf in sorted(local_tmp.glob("*.json")):
                    data = json.loads(jf.read_text(encoding="utf-8"))
                    data["_json_path"] = str(json_dir / jf.name)  # path จริงบน mount
                    data["_local_json_path"] = str(jf)             # path local
                    all_slips.append(data)

                if not all_slips:
                    continue

                # ── แบ่ง slip ตาม route (note prefix) ──
                groups: dict[str, dict] = {}
                for s in all_slips:
                    note  = s.get("note") or ""
                    route = get_route(note)
                    sf    = route["subfolder"]
                    if sf not in groups:
                        groups[sf] = {"slips": [], "template": route["template"]}
                    groups[sf]["slips"].append(s)

                for sf, group in groups.items():
                    group_slips = group["slips"]
                    tmpl_path   = group["template"]
                    sub_docs    = day_dir / "docs" / sf
                    # local temp สำหรับ gen PDF ก่อน copy ขึ้น mount
                    local_docs  = local_tmp / "docs" / sf

                    # เช็ค state local ว่า group นี้มี slip ใหม่ไหม
                    new_slips = [
                        s for s in group_slips
                        if not is_generated(state, year_dir.name, month_dir.name,
                                            day_dir.name, sf, s)
                    ]

                    if not new_slips:
                        continue

                    print(f"  📄 {year_dir.name}/{month_dir.name}/{day_dir.name}/{sf} "
                          f"— slip ใหม่ {len(new_slips)} ใบ (รวม {len(group_slips)} ใบ)")

                    # ลบ PDF เก่าผ่าน rclone
                    import subprocess as _sp
                    _sp.run([
                        "rclone", "delete",
                        f"gdrive:SlipProcessor/data/{year_dir.name}/{month_dir.name}/{day_dir.name}/docs/{sf}",
                        "--include", "*.pdf",
                        "--config", str(Path.home() / ".config/rclone/rclone.conf"),
                    ], capture_output=True)

                    # gen PDF ใน local temp
                    local_docs.mkdir(parents=True, exist_ok=True)

                    # gen ใบรับรองแทนใบเสร็จรับเงิน
                    docx_path = fill_template(
                        group_slips,
                        day_dir.name,
                        month_dir.name,
                        year_dir.name,
                        template_path=tmpl_path,
                    )

                    if docx_path is None:
                        results["failed"] += 1
                        continue

                    date_prefix  = f"{year_dir.name}{MONTH_MAP_NUM.get(month_dir.name, '00')}{day_dir.name}"
                    final_name   = f"{date_prefix}-ใบรับรองแทนใบเสร็จรับเงิน"
                    renamed_docx = local_docs / f"{final_name}.docx"
                    shutil.move(str(docx_path), str(renamed_docx))

                    pdf_path = convert_to_pdf(renamed_docx, local_docs)
                    renamed_docx.unlink(missing_ok=True)

                    if pdf_path is None:
                        print(f"    ❌ [{sf}] ใบรับรองฯ convert ล้มเหลว")
                        results["failed"] += 1
                        continue

                    print(f"    ✅ {date_prefix}-ใบรับรองแทนใบเสร็จรับเงิน.pdf")

                    # gen ใบสำคัญรับเงิน แยกตาม vendor
                    from collections import defaultdict
                    slips_by_vendor: dict[str, list] = defaultdict(list)
                    for s in group_slips:
                        to_name = s.get("to_name") or s.get("to_account", "")
                        slips_by_vendor[to_name].append(s)

                    local_receipt_dir = local_docs / "ใบสำคัญรับเงิน"
                    for to_name, vendor_slips in slips_by_vendor.items():
                        vendor = find_vendor(to_name, vendors)
                        if vendor is None:
                            print(f"    ℹ️  ไม่เจอ vendor '{to_name}' — ข้ามใบสำคัญฯ")
                            continue
                        for s in vendor_slips:
                            s["vendor"] = vendor
                        safe_name = to_name.replace("/", "-").replace("\\", "-")
                        file_name = f"{date_prefix}-{safe_name}"
                        local_receipt_dir.mkdir(parents=True, exist_ok=True)
                        receipt_docx = fill_template_receipt(
                            vendor_slips, day_dir.name, month_dir.name, year_dir.name,
                        )
                        if receipt_docx:
                            renamed_receipt = local_receipt_dir / f"{file_name}.docx"
                            shutil.move(str(receipt_docx), str(renamed_receipt))
                            receipt_pdf = convert_to_pdf(renamed_receipt, local_receipt_dir)
                            renamed_receipt.unlink(missing_ok=True)
                            if receipt_pdf:
                                print(f"    ✅ ใบสำคัญรับเงิน/{file_name}.pdf")

                    # ── copy ทุกอย่างจาก local_docs ขึ้น mount ทีเดียว ──
                    sub_docs.mkdir(parents=True, exist_ok=True)
                    _sp.run([
                        "rclone", "copy", str(local_docs),
                        f"gdrive:SlipProcessor/data/{year_dir.name}/{month_dir.name}/{day_dir.name}/docs/{sf}",
                        "--config", str(Path.home() / ".config/rclone/rclone.conf"),
                    ], capture_output=True)

                    # บันทึก state local (เร็ว ไม่ต้องแตะ Drive)
                    mark_generated(state, year_dir.name, month_dir.name,
                                   day_dir.name, sf, group_slips, str(pdf_path))
                    save_state(state)

                    # merge summary
                    new_slip_paths = {s["_json_path"] for s in new_slips}
                    group_new = [s for s in group_slips if s["_json_path"] in new_slip_paths]
                    merge_to_summary(summary, month_dir.name, day_dir.name,
                                     group_new, pdf_path.name)

                    total_amt = sum(s.get("amount") or 0 for s in group_new)
                    results["monthly"][month_dir.name] = (
                        results["monthly"].get(month_dir.name, 0) + total_amt
                    )
                    print(f"    ✅ [{sf}] {pdf_path.name} (฿{total_amt:,.0f})")
                    results["new"] += 1

        save_summary(year_dir, summary)

    print(f"\n✅ gen ใหม่: {results['new']}  ❌ ล้มเหลว: {results['failed']}")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gen PDF ใบรับรองแทนใบเสร็จรับเงิน")
    parser.add_argument(
        "--regen",
        nargs=2,
        metavar=("SCOPE", "VALUE"),
        help="regen โดย bypass ตัวเช็ค เช่น --regen year 2026 | --regen month 2026/JUN | --regen day 2026/JUN/24"
    )
    args = parser.parse_args()

    if args.regen:
        scope_type, scope_value = args.regen
        print(f"♻️  Regen mode: {scope_type} = {scope_value}")

        from state import load_state, save_state, reset_state
        state = load_state()
        count = reset_state(state, scope_value)
        save_state(state)
        print(f"   Reset {count} groups — กำลัง gen...\n")

    run()
