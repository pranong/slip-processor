"""
config.py — ตั้งค่าทั้งหมดที่นี่ที่เดียว
แก้ค่าข้างล่างให้ตรงกับระบบของคุณ
"""

# ── Google Drive (rclone remote name) ─────────────────────────────────────────
RCLONE_REMOTE     = "gdrive"                           # ชื่อ remote ที่ตั้งใน rclone config
DRIVE_RAW_FOLDER  = "gdrive:SlipProcessor/rawFile"     # folder รับรูปจากมือถือ
DRIVE_DATA_FOLDER = "gdrive:SlipProcessor/data"        # folder ผลลัพธ์ทั้งหมด

# ── Path บน Pi (mount points) ─────────────────────────────────────────────────
BASE_DIR       = "/home/pi/slip-processor"
RAW_MOUNT      = f"{BASE_DIR}/rawFile"                 # mount Drive:rawFile มาที่นี่
DATA_MOUNT     = f"{BASE_DIR}/data"                    # mount Drive:data มาที่นี่ (read/write)
TEMPLATE_DIR   = f"{BASE_DIR}/template"
TEMPLATE_PATH  = f"{TEMPLATE_DIR}/ใบรับรองแทนใบเสร็จรับเงิน.docx"
HASH_DB_PATH   = f"{BASE_DIR}/processed_hashes.json"
LOG_DIR        = f"{BASE_DIR}/logs"

# ── Claude API ────────────────────────────────────────────────────────────────
CLAUDE_MODEL   = "claude-sonnet-4-6"
HASH_THRESHOLD = 8                                     # phash ≤ 8 ถือว่าซ้ำ

# ── Line Notify ───────────────────────────────────────────────────────────────
LINE_TOKEN     = "YOUR_LINE_NOTIFY_TOKEN"              # ← ใส่ token ของคุณ

# ── อื่นๆ ─────────────────────────────────────────────────────────────────────
IMAGE_EXTS     = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MONTH_MAP      = {
    1: "JAN", 2: "FEB",  3: "MAR",  4: "APR",
    5: "MAY", 6: "JUN",  7: "JUL",  8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}
