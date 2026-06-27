#!/bin/bash
# setup_bot.sh — ติดตั้ง Telegram Bot เป็น systemd service

CODE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CURRENT_USER=$(whoami)

echo "── ติดตั้ง Telegram Bot service ──"

sudo tee /etc/systemd/system/slip-bot.service > /dev/null << UNIT
[Unit]
Description=Slip Processor Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CODE}
ExecStart=/usr/bin/python3 ${CODE}/telegram_bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable slip-bot.service
sudo systemctl start slip-bot.service

sleep 3
sudo systemctl status slip-bot.service --no-pager | head -5
echo ""
echo "✅ Bot เริ่มทำงานแล้ว!"
echo "   ลองพิมพ์ /help ใน Telegram ได้เลยครับ"
