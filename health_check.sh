#!/bin/bash
# health_check.sh — เช็ค mount ทุก 5 นาที
# crontab: */5 * * * * /home/pi/slip-processor/health_check.sh

BASE="/home/pi/slip-processor"
LINE_TOKEN="YOUR_LINE_NOTIFY_TOKEN"   # ← ใส่ token ของคุณ
LOG="$BASE/logs/health.log"

send_line() {
    if [ "$LINE_TOKEN" != "YOUR_LINE_NOTIFY_TOKEN" ]; then
        curl -s -X POST https://notify-api.line.me/api/notify \
            -H "Authorization: Bearer $LINE_TOKEN" \
            -d "message=$1" > /dev/null 2>&1
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
    send_line "
🔴 Mount Alert
$name หลุดแล้ว
กำลัง remount..."

    sudo systemctl restart "$service"
    sleep 15

    if mountpoint -q "$path"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ $name remount สำเร็จ" >> "$LOG"
        send_line "
✅ $name remount สำเร็จ"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ $name remount ล้มเหลว!" >> "$LOG"
        send_line "
🔴🔴 $name remount ล้มเหลว!
ต้องเข้าไปจัดการ manual"
    fi
}

# เช็ค disk space ด้วย
check_disk() {
    local usage=$(df "$BASE" | awk 'NR==2 {print $5}' | tr -d '%')
    if [ "$usage" -gt 80 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ disk usage ${usage}%" >> "$LOG"
        send_line "
⚠️ Disk Alert
ใช้ไป ${usage}% แล้ว
กรุณาเคลียร์พื้นที่"
    fi
}

# ── Run checks ──
mkdir -p "$BASE/logs"
check_mount "rawFile" "$BASE/rawFile" "rclone-rawfile.service"
check_mount "data"    "$BASE/data"    "rclone-data.service"
check_disk
