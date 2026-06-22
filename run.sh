#!/bin/bash
# run.sh — crontab รันไฟล์นี้ตอนตี 3
# crontab: 0 3 * * * /home/pi/slip-processor/run.sh >> /home/pi/slip-processor/logs/cron.log 2>&1

BASE="/home/pi/slip-processor"
export ANTHROPIC_API_KEY="YOUR_ANTHROPIC_API_KEY"   # ← ใส่ key ของคุณ

echo ""
echo "========================================"
echo "▶ $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# เช็ค mount ก่อน
if ! mountpoint -q "$BASE/rawFile"; then
    echo "❌ rawFile ยัง mount ไม่ได้ — ลอง restart service"
    sudo systemctl restart rclone-rawfile.service
    sleep 10
    if ! mountpoint -q "$BASE/rawFile"; then
        echo "❌ mount ไม่สำเร็จ — ยกเลิก"
        exit 1
    fi
fi

if ! mountpoint -q "$BASE/data"; then
    echo "❌ data ยัง mount ไม่ได้ — ลอง restart service"
    sudo systemctl restart rclone-data.service
    sleep 10
    if ! mountpoint -q "$BASE/data"; then
        echo "❌ mount ไม่สำเร็จ — ยกเลิก"
        exit 1
    fi
fi

# รัน pipeline
cd "$BASE"
python3 run_pipeline.py

echo "✅ $(date '+%Y-%m-%d %H:%M:%S')"
