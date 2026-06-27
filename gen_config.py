"""
gen_config.py — ตั้งค่าการ routing และ gen PDF
แก้ที่นี่เพื่อเพิ่ม/ลด keyword หรือเปลี่ยน template
"""

# ── Note Routing ──────────────────────────────────────────────────────────────
# keyword ไม่ case sensitive และเจอที่ไหนใน note ก็ได้
# เพิ่ม entry ใหม่ได้เลย
NOTE_ROUTES = [
    {
        "keyword":   "uan",
        "subfolder": "uan",
        "template":  "ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx",
    },
    {
        "keyword":   "ceramic",
        "subfolder": "ceramic",
        "template":  "ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx",
    },
    {
        "keyword":   "อวน",
        "subfolder": "uan",
        "template":  "ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx",
    },
    # ตัวอย่างเพิ่ม keyword ใหม่:
    # {
    #     "keyword":   "farm",
    #     "subfolder": "farm",
    #     "template":  "ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx",
    # },
]

# ── Default (ถ้า note ไม่ match keyword ไหนเลย) ───────────────────────────────
NOTE_DEFAULT_SUBFOLDER = "บุคคล"
NOTE_DEFAULT_TEMPLATE  = "ใบรับรองแทนใบเสร็จรับเงิน.docx"
