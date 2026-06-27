#!/bin/bash
# run.sh — crontab รันไฟล์นี้ตอนตี 3
# crontab: 0 3 * * * /app/uan/slip-processor/run.sh >> /app/uan/slip-processor/data/logs/cron.log 2>&1

CODE="/app/uan/slip-processor"
MOUNT="/home/pi/slip-processor"
cd "$CODE"
export ANTHROPIC_API_KEY=$(python3 -c "from config.config import ANTHROPIC_API_KEY; print(ANTHROPIC_API_KEY)")

echo ""
echo "========================================"
echo "▶ $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# restart mount ทุกครั้งก่อนรัน ให้สะอาดเสมอ
echo "── restart mount ──"
sudo systemctl restart rclone-rawfile.service
sudo systemctl restart rclone-data.service
sleep 10

# เช็คว่า mount พร้อมไหม
if ! mountpoint -q "$MOUNT/rawFile"; then
    echo "❌ rawFile mount ไม่สำเร็จ — ยกเลิก"
    exit 1
fi

if ! mountpoint -q "$MOUNT/data"; then
    echo "❌ data mount ไม่สำเร็จ — ยกเลิก"
    exit 1
fi

echo "✅ mount พร้อม"

# รัน pipeline
cd "$CODE"
python3 run_pipeline.py

echo "✅ $(date '+%Y-%m-%d %H:%M:%S')"
