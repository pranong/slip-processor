#!/bin/bash
# setup_mount.sh — ตั้งค่า mount Google Drive ครั้งแรก

set -e

# ── Auto detect ──────────────────────────────────────────────────────────────
CURRENT_USER=$(whoami)
CODE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)   # path ของ script นี้เอง
MOUNT="/home/pi/slip-processor"                       # mount point (เปลี่ยนได้)
REMOTE="gdrive"
RCLONE_CONF="$HOME/.config/rclone/rclone.conf"
CACHE_DIR="$HOME/.cache/rclone"

echo "========================================"
echo "  Slip Processor — Setup Mount"
echo "  User : $CURRENT_USER"
echo "  Code : $CODE"
echo "  Mount: $MOUNT"
echo "  Conf : $RCLONE_CONF"
echo "========================================"

# ── 1. เช็ค rclone ──
if ! command -v rclone &> /dev/null; then
    echo "❌ rclone ไม่พบ — ลงด้วย: sudo apt install rclone"
    exit 1
fi
echo "✅ rclone พร้อม"

# ── 2. เช็ค config ──
if [ ! -f "$RCLONE_CONF" ]; then
    echo "❌ ไม่พบ rclone config: $RCLONE_CONF"
    echo "   รัน: rclone config"
    exit 1
fi
echo "✅ rclone config พร้อม"

# ── 3. เช็ค remote ──
if ! rclone listremotes --config "$RCLONE_CONF" | grep -q "${REMOTE}:"; then
    echo "❌ ไม่พบ remote '${REMOTE}' — รัน: rclone config"
    exit 1
fi
echo "✅ remote '${REMOTE}' พร้อม"

# ── 4. สร้าง folders ──
echo ""
echo "── สร้าง folders ──"
mkdir -p "$MOUNT/rawFile"
mkdir -p "$MOUNT/data"
mkdir -p "$CODE/template"
mkdir -p "$CODE/logs"
mkdir -p "$CACHE_DIR"
chown -R "$CURRENT_USER":"$CURRENT_USER" "$MOUNT"
chown -R "$CURRENT_USER":"$CURRENT_USER" "$CODE/logs"
echo "✅ folders พร้อม"

# ── 5. สร้าง folders บน Drive ──
echo ""
echo "── สร้าง folders บน Drive ──"
rclone mkdir "${REMOTE}:SlipProcessor/rawFile" --config "$RCLONE_CONF"
rclone mkdir "${REMOTE}:SlipProcessor/data" --config "$RCLONE_CONF"
echo "✅ Drive folders พร้อม"

# ── 6. สร้าง systemd services ──
echo ""
echo "── สร้าง systemd services ──"

sudo tee /etc/systemd/system/rclone-rawfile.service > /dev/null << UNIT
[Unit]
Description=rclone mount Google Drive rawFile
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
ExecStart=/usr/bin/rclone mount ${REMOTE}:SlipProcessor/rawFile ${MOUNT}/rawFile \
  --config ${RCLONE_CONF} \
  --vfs-cache-mode full \
  --vfs-cache-max-age 1h \
  --dir-cache-time 5m \
  --poll-interval 1m \
  --cache-dir ${CACHE_DIR} \
  --log-file ${CODE}/logs/mount_rawfile.log \
  --log-level INFO
ExecStop=/bin/fusermount -uz ${MOUNT}/rawFile
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
UNIT

sudo tee /etc/systemd/system/rclone-data.service > /dev/null << UNIT
[Unit]
Description=rclone mount Google Drive data
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
ExecStart=/usr/bin/rclone mount ${REMOTE}:SlipProcessor/data ${MOUNT}/data \
  --config ${RCLONE_CONF} \
  --vfs-cache-mode full \
  --vfs-cache-max-age 24h \
  --vfs-write-back 5s \
  --dir-cache-time 5m \
  --poll-interval 1m \
  --cache-dir ${CACHE_DIR} \
  --log-file ${CODE}/logs/mount_data.log \
  --log-level INFO
ExecStop=/bin/fusermount -uz ${MOUNT}/data
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
echo "✅ services เริ่มทำงาน"

# ── 7. เช็คสถานะ ──
echo ""
echo "── สถานะ mount ──"
sleep 5
mountpoint -q "$MOUNT/rawFile" && echo "✅ rawFile mounted" || echo "❌ rawFile ไม่ mount"
mountpoint -q "$MOUNT/data"    && echo "✅ data mounted"    || echo "❌ data ไม่ mount"

echo ""
echo "========================================"
echo "  Setup เสร็จ!"
echo ""
echo "  ขั้นตอนต่อไป:"
echo "  1. วาง template ที่ $CODE/template/"
echo "  2. ใส่ keys ใน $CODE/config.py"
echo "  3. crontab -e"
echo "     0 3 * * * $CODE/run.sh"
echo "     */5 * * * * $CODE/health_check.sh"
echo "========================================"
