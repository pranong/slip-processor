#!/bin/bash
# setup_mount.sh — ตั้งค่า mount Google Drive ครั้งแรก
# รันครั้งเดียวตอนติดตั้ง: bash setup_mount.sh

set -e
BASE="/home/pi/slip-processor"
REMOTE="gdrive"
CACHE_DIR="/home/pi/.cache/rclone"

echo "========================================"
echo "  Slip Processor — Setup Mount"
echo "========================================"

# ── 1. เช็ค rclone ──
if ! command -v rclone &> /dev/null; then
    echo "❌ rclone ไม่พบ — ลงด้วย: sudo apt install rclone"
    exit 1
fi

# ── 2. เช็ค rclone remote ──
if ! rclone listremotes | grep -q "^${REMOTE}:"; then
    echo ""
    echo "⚠️  ยังไม่มี remote '${REMOTE}'"
    echo "รัน: rclone config"
    echo "  → New remote"
    echo "  → ชื่อ: gdrive"
    echo "  → Type: Google Drive"
    echo "  → ทำตาม wizard (จะเปิด browser ให้ login)"
    echo ""
    exit 1
fi

# ── 3. สร้าง folders ──
echo ""
echo "── สร้าง folders ──"
mkdir -p "$BASE/rawFile"
mkdir -p "$BASE/data"
mkdir -p "$BASE/template"
mkdir -p "$BASE/logs"
mkdir -p "$CACHE_DIR"
echo "✅ folders พร้อม"

# ── 4. สร้าง folders บน Drive (ถ้ายังไม่มี) ──
echo ""
echo "── สร้าง folders บน Drive ──"
rclone mkdir "${REMOTE}:SlipProcessor/rawFile"
rclone mkdir "${REMOTE}:SlipProcessor/data"
echo "✅ Drive folders พร้อม"

# ── 5. สร้าง systemd service สำหรับ mount ──
echo ""
echo "── สร้าง systemd services ──"

# rawFile mount (read-only)
sudo tee /etc/systemd/system/rclone-rawfile.service > /dev/null << 'UNIT'
[Unit]
Description=rclone mount Google Drive rawFile
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=pi
ExecStart=/usr/bin/rclone mount gdrive:SlipProcessor/rawFile /home/pi/slip-processor/rawFile \
  --vfs-cache-mode full \
  --vfs-cache-max-age 1h \
  --dir-cache-time 5m \
  --poll-interval 1m \
  --cache-dir /home/pi/.cache/rclone \
  --log-file /home/pi/slip-processor/logs/mount_rawfile.log \
  --log-level INFO
ExecStop=/bin/fusermount -uz /home/pi/slip-processor/rawFile
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
UNIT

# data mount (read-write)
sudo tee /etc/systemd/system/rclone-data.service > /dev/null << 'UNIT'
[Unit]
Description=rclone mount Google Drive data
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=pi
ExecStart=/usr/bin/rclone mount gdrive:SlipProcessor/data /home/pi/slip-processor/data \
  --vfs-cache-mode full \
  --vfs-cache-max-age 24h \
  --vfs-write-back 5s \
  --dir-cache-time 5m \
  --poll-interval 1m \
  --cache-dir /home/pi/.cache/rclone \
  --log-file /home/pi/slip-processor/logs/mount_data.log \
  --log-level INFO
ExecStop=/bin/fusermount -uz /home/pi/slip-processor/data
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable rclone-rawfile.service
sudo systemctl enable rclone-data.service
sudo systemctl start rclone-rawfile.service
sudo systemctl start rclone-data.service

echo "✅ systemd services เริ่มทำงาน"

# ── 6. เช็คสถานะ ──
echo ""
echo "── สถานะ mount ──"
sleep 3
mountpoint -q "$BASE/rawFile" && echo "✅ rawFile mounted" || echo "❌ rawFile ยังไม่ mount"
mountpoint -q "$BASE/data"    && echo "✅ data mounted"    || echo "❌ data ยังไม่ mount"

echo ""
echo "========================================"
echo "  Setup เสร็จ!"
echo ""
echo "  ขั้นตอนต่อไป:"
echo "  1. วาง template ที่ $BASE/template/"
echo "  2. ใส่ API keys ใน $BASE/config.py"
echo "  3. ตั้ง crontab: crontab -e"
echo "     0 3 * * * $BASE/run.sh"
echo "     */5 * * * * $BASE/health_check.sh"
echo "========================================"
