#!/bin/bash
# health_check.sh — เช็ค mount ทุก 5 นาที
# crontab: */5 * * * * /app/uan/slip-processor/health_check.sh

CODE="/app/uan/slip-processor"
MOUNT="/home/pi/slip-processor"
TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"     # ← จาก @BotFather
TELEGRAM_CHAT_ID="YOUR_CHAT_ID"         # ← จาก getUpdates API
LOG="$CODE/data/logs/health.log"

send_telegram() {
    if [ "$TELEGRAM_BOT_TOKEN" != "YOUR_BOT_TOKEN" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=$1" > /dev/null 2>&1
    fi
}

check_mount() {
    local name=$1
    local path=$2
    local service=$3

    if mountpoint -q "$path"; then
        return 0
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ $name หลุด — remounting..." >> "$LOG"
    send_telegram "🔴 Mount Alert
$name หลุดแล้ว
กำลัง remount..."

    sudo systemctl restart "$service"
    sleep 15

    if mountpoint -q "$path"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ $name remount สำเร็จ" >> "$LOG"
        send_telegram "✅ $name remount สำเร็จ"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ $name remount ล้มเหลว!" >> "$LOG"
        send_telegram "🔴🔴 $name remount ล้มเหลว!
ต้องเข้าไปจัดการ manual"
    fi
}

check_disk() {
    local usage=$(df "$CODE" | awk 'NR==2 {print $5}' | tr -d '%')
    if [ "$usage" -gt 80 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ disk usage ${usage}%" >> "$LOG"
        send_telegram "⚠️ Disk Alert
ใช้ไป ${usage}% แล้ว
กรุณาเคลียร์พื้นที่"
    fi
}

# ── Run checks ──
mkdir -p "$CODE/logs"
check_mount "rawFile" "$MOUNT/rawFile" "rclone-rawfile.service"
check_mount "data"    "$MOUNT/data"    "rclone-data.service"
check_disk
