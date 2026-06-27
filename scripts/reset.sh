#!/bin/bash
# reset.sh — clear ทุกอย่างแล้วเริ่มใหม่
# usage: bash scripts/reset.sh

RCLONE_CONF="/home/punkrawk/.config/rclone/rclone.conf"
CODE="/app/uan/slip-processor"

echo "========================================"
echo "  Slip Processor — Reset"
echo "========================================"
echo ""
echo "⚠️  คำเตือน: การ reset จะลบ"
echo "   - data ทั้งหมดบน Google Drive"
echo "   - processed_hashes.json"
echo "   - generated_log.json"
echo "   - log files ทั้งหมด"
echo ""
read -p "แน่ใจไหม? (y/N): " confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "❌ ยกเลิก"
    exit 0
fi

echo ""
echo "── ลบ data บน Google Drive ──"
rclone purge gdrive:SlipProcessor/data --config "$RCLONE_CONF" && \
rclone mkdir gdrive:SlipProcessor/data --config "$RCLONE_CONF"
echo "✅ Drive data cleared"

echo ""
echo "── ลบ local state files ──"
rm -f "$CODE/data/processed_hashes.json"
rm -f "$CODE/data/generated_log.json"
rm -f "$CODE/data/logs/"*.log
echo "✅ local state cleared"

echo ""
echo "========================================"
echo "  Reset เสร็จ! พร้อมรัน sort + gen ใหม่"
echo "  cd $CODE && python3 sort_slips.py && python3 gen_pdf.py"
echo "========================================"
