#!/bin/bash
# run_safe.sh — รัน run_pipeline.py แบบ detach จาก SSH session เต็มที่ ปิด SSH ก็ไม่ตาย
# ใช้ setsid (ตัด controlling terminal ทิ้งเลย) + nohup (กัน SIGHUP ซ้ำ) + redirect stdout/stderr
# ไปไฟล์ log ตรงๆ (ครบทุกบรรทัด รวม log() แบบ print() ที่ data/logs/run_*.log ปกติจับไม่ได้)
#
# usage: bash scripts/run_safe.sh
# เช็ค progress ระหว่างรัน: tail -f <log ที่ script บอก>

CODE="/app/uan/slip-processor"
cd "$CODE" || exit 1

LOG="/tmp/run_$(date +%Y%m%d_%H%M%S).log"

export SLIP_PIPELINE_DETACHED=1  # กัน run_pipeline.py re-exec กลับมาเรียกสคริปต์นี้ซ้ำเป็นวงไม่รู้จบ
setsid nohup python3 run_pipeline.py > "$LOG" 2>&1 < /dev/null &
PID=$!
disown

echo "▶ รันแล้ว (PID $PID) — ปิด SSH ได้เลย ไม่ตาย"
echo "   log: $LOG"
echo "   เช็ค progress: tail -f $LOG"
echo "   เช็คว่ายังรันอยู่ไหม: ps -p $PID"
