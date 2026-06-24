#!/bin/bash
# run.sh — crontab รันไฟล์นี้ตอนตี 3
# crontab: 0 3 * * * /app/uan/slip-processor/run.sh >> /app/uan/slip-processor/logs/cron.log 2>&1

CODE="/app/uan/slip-processor"
MOUNT="/home/pi/slip-processor"
export ANTHROPIC_API_KEY=$(python3 -c "from config import ANTHROPIC_API_KEY; print(ANTHROPIC_API_KEY)")

echo ""
echo "========================================"
echo "▶ $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# เช็ค mount ก่อน
if ! mountpoint -q "$MOUNT/rawFile"; then
    echo "❌ rawFile ยัง mount ไม่ได้ — ลอง restart"
    sudo systemctl restart rclone-rawfile.service
    sleep 10
    if ! mountpoint -q "$MOUNT/rawFile"; then
        echo "❌ mount ไม่สำเร็จ — ยกเลิก"
        exit 1
    fi
fi

if ! mountpoint -q "$MOUNT/data"; then
    echo "❌ data ยัง mount ไม่ได้ — ลอง restart"
    sudo systemctl restart rclone-data.service
    sleep 10
    if ! mountpoint -q "$MOUNT/data"; then
        echo "❌ mount ไม่สำเร็จ — ยกเลิก"
        exit 1
    fi
fi

# รัน pipeline
cd "$CODE"
python3 run_pipeline.py

echo "✅ $(date '+%Y-%m-%d %H:%M:%S')"
