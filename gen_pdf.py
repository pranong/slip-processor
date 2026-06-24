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

from config import DATA_MOUNT, TEMPLATE_PATH, MONTH_MAP
from thai_baht_text import baht_text

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
        shutil.copy2(p, bak_dir / f"summary_{ts}.json")

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
                  year_thai: str) -> Path | None:
    """เติมข้อมูลลง template, return path ของ docx ที่ fill แล้ว"""
    template = Path(TEMPLATE_PATH)
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
        desc_str = slip.get("description") or "-"
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

    # แทน placeholders ทั้งหมด (รองรับ split across runs)
    _replace_text_in_doc(doc, "$intSumTotal", total_str)
    _replace_text_in_doc(doc, "$thSumTotal", total_th_str)

    # บันทึก docx ชั่วคราว
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / f"filled_{month_name}_{day_str}.docx"
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

                images_dir = day_dir / "images"
                docs_dir   = day_dir / "docs"

                if not images_dir.exists():
                    continue

                # หา slip JSON ทั้งหมดของวันนี้
                all_slips = []
                new_slips = []
                for jf in sorted(images_dir.glob("*.json")):
                    data = json.loads(jf.read_text(encoding="utf-8"))
                    data["_json_path"] = str(jf)
                    all_slips.append(data)
                    if not data.get("pdf_generated", False):
                        new_slips.append(data)

                # ถ้าไม่มี slip ใหม่เลย ข้ามไป
                if not new_slips:
                    continue

                print(f"  📄 {year_dir.name}/{month_dir.name}/{day_dir.name} "
                      f"— slip ใหม่ {len(new_slips)} ใบ (รวมทั้งหมด {len(all_slips)} ใบ)", end=" ... ")

                # ลบ PDF เก่าของวันนี้ก่อน แล้ว re-gen ใหม่รวมทั้งหมด
                docs_dir.mkdir(parents=True, exist_ok=True)
                for old_pdf in docs_dir.glob("*.pdf"):
                    old_pdf.unlink()

                # gen PDF ใหม่จาก slip ทั้งหมดของวันนี้
                docx_path = fill_template(
                    all_slips,
                    day_dir.name,
                    month_dir.name,
                    year_dir.name
                )

                if docx_path is None:
                    results["failed"] += len(new_slips)
                    continue

                # PDF ชื่อคงที่ (ไม่ใช้ running number แล้ว เพราะ re-gen ทับเสมอ)
                docs_dir.mkdir(parents=True, exist_ok=True)
                final_name   = f"ใบรับรองแทนใบเสร็จรับเงิน"
                renamed_docx = docx_path.parent / f"{final_name}.docx"
                docx_path.rename(renamed_docx)

                pdf_path = convert_to_pdf(renamed_docx, docs_dir)
                renamed_docx.unlink(missing_ok=True)

                if pdf_path is None:
                    print("❌ convert PDF ล้มเหลว")
                    results["failed"] += len(new_slips)
                    continue

                # mark ทุก slip ของวันนี้ว่า generated แล้ว
                for s in all_slips:
                    jf = Path(s["_json_path"])
                    d = json.loads(jf.read_text(encoding="utf-8"))
                    d["pdf_generated"] = True
                    d["pdf_file"] = str(pdf_path)
                    jf.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

                # merge summary (เฉพาะ slip ใหม่)
                merge_to_summary(summary, month_dir.name, day_dir.name,
                                 new_slips, pdf_path.name)

                total_amt = sum(s.get("amount") or 0 for s in new_slips)
                results["monthly"][month_dir.name] = (
                    results["monthly"].get(month_dir.name, 0) + total_amt
                )

                print(f"✅ {pdf_path.name} (฿{total_amt:,.0f})")
                results["new"] += 1

        save_summary(year_dir, summary)

    print(f"\n✅ gen ใหม่: {results['new']}  ❌ ล้มเหลว: {results['failed']}")
    return results


if __name__ == "__main__":
    run()
