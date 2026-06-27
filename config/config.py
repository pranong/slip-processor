"""
config.py — ตั้งค่าทั้งหมดที่นี่ที่เดียว
สำหรับ routing ของ gen PDF ดูที่ gen_config.py
"""

# ── Google Drive (rclone remote name) ─────────────────────────────────────────
RCLONE_REMOTE     = "gdrive"
DRIVE_RAW_FOLDER  = "gdrive:SlipProcessor/rawFile"
DRIVE_DATA_FOLDER = "gdrive:SlipProcessor/data"

# ── Path ──────────────────────────────────────────────────────────────────────
CODE_DIR       = "/app/uan/slip-processor"
MOUNT_DIR      = "/home/pi/slip-processor"
RAW_MOUNT      = f"{MOUNT_DIR}/rawFile"
DATA_MOUNT     = f"{MOUNT_DIR}/data"
TEMPLATE_DIR   = f"{CODE_DIR}/template"
TEMPLATE_PATH  = f"{TEMPLATE_DIR}/ใบรับรองแทนใบเสร็จรับเงิน.docx"
HASH_DB_PATH   = f"{CODE_DIR}/data/processed_hashes.json"
LOG_DIR        = f"{CODE_DIR}/data/logs"

# ── Claude API ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY"
CLAUDE_MODEL      = "claude-sonnet-4-6"
HASH_THRESHOLD    = 8

# ── Telegram Bot ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID"

# ── อื่นๆ ─────────────────────────────────────────────────────────────────────
IMAGE_EXTS     = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MONTH_MAP      = {
    1: "JAN", 2: "FEB",  3: "MAR",  4: "APR",
    5: "MAY", 6: "JUN",  7: "JUL",  8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}