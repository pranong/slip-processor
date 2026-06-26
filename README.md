# Slip Processor — คู่มือติดตั้งและใช้งาน

## สิ่งที่ต้องเตรียม

| # | รายการ | วิธี |
|---|--------|------|
| 1 | Anthropic API Key | console.anthropic.com → API Keys |
| 2 | Telegram Bot Token | คุยกับ @BotFather → /newbot |
| 3 | Telegram Chat ID | เปิด api.telegram.org/bot<TOKEN>/getUpdates |
| 4 | Google Account | มี Gmail ก็พอ |
| 5 | Raspberry Pi | Pi 4 (2GB+) แนะนำ |

---

## ติดตั้งบน Pi

```bash
# 1. ลง dependencies
sudo apt update
sudo apt install rclone libreoffice-writer fuse3 fonts-thai-tlwg
pip3 install -r requirements.txt --break-system-packages

# 2. ตั้ง timezone
sudo timedatectl set-timezone Asia/Bangkok

# 3. ตั้งค่า rclone (ดูรายละเอียดใน RCLONE_SETUP.md)
rclone config

# 4. วาง files
cp -r slip-processor/ /app/uan/slip-processor/
cp ใบรับรองแทนใบเสร็จรับเงิน.docx /app/uan/slip-processor/template/

# 5. ใส่ API keys ใน config.py
nano /app/uan/slip-processor/config.py

# 6. chmod
chmod +x /app/uan/slip-processor/*.sh

# 7. setup mount (รันครั้งเดียว)
bash /app/uan/slip-processor/setup_mount.sh

# 8. setup telegram bot service
bash /app/uan/slip-processor/setup_bot.sh

# 9. ตั้ง crontab
crontab -e
# เพิ่ม:
# 0 3 * * * /app/uan/slip-processor/run.sh >> /app/uan/slip-processor/logs/cron.log 2>&1
# */5 * * * * /app/uan/slip-processor/health_check.sh
```

---

## โครงสร้าง Google Drive

```
SlipProcessor/
  rawFile/           ← โยนรูป slip ที่นี่
  data/
    2026/
      summary.json   ← Cowork อ่านไฟล์นี้
      JUN/
        24/
          images/    ← รูป slip
          metadata/  ← ข้อมูล JSON (ซ่อนไว้)
          docs/
            บุคคล/ใบรับรองแทนใบเสร็จรับเงิน.pdf
            uan/ใบรับรองแทนใบเสร็จรับเงิน.pdf
    unclassified/    ← รูปที่ไม่มี note (จัดการ manual)
```

---

## วิธีใช้งาน — Command Line

```bash
cd /app/uan/slip-processor

# sort รูปจาก rawFile แยกตามเดือน/วัน
python3 sort_slips.py

# gen PDF (เฉพาะที่ยังไม่เคย gen)
python3 gen_pdf.py

# regen ทั้งปี (bypass ตัวเช็ค)
python3 gen_pdf.py --regen year 2026

# regen ทั้งเดือน
python3 gen_pdf.py --regen month 2026/JUN

# regen วันเดียว
python3 gen_pdf.py --regen day 2026/JUN/24

# รัน pipeline ทั้งหมด (sort + gen + notify)
python3 run_pipeline.py
```

---

## วิธีใช้งาน — Telegram Bot

พิมพ์คำสั่งในห้อง Telegram ที่ bot อยู่:

| คำสั่ง | ทำอะไร |
|--------|--------|
| `/help` | แสดงคำสั่งทั้งหมด |
| `/status` | เช็คสถานะ mount ของ Pi |
| `/run` | รัน pipeline ทั้งหมด (sort + gen + notify) |
| `/sort` | อ่าน slip + แยก folder เท่านั้น |
| `/gen` | gen PDF เท่านั้น |
| `/genYear -2026` | regen ทั้งปี 2026 |
| `/genMonth -2026/JUN` | regen ทั้งเดือนมิถุนายน |
| `/genDay -2026/JUN/24` | regen วันที่ 24 มิ.ย. |

---

## Routing ตาม Note

| Note บน slip | subfolder | template |
|-------------|-----------|---------|
| ขึ้นต้น "uan" | `docs/uan/` | ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx |
| ขึ้นต้น "ceramic" | `docs/ceramic/` | ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx |
| note อื่นๆ | `docs/บุคคล/` | ใบรับรองแทนใบเสร็จรับเงิน.docx |
| ไม่มี note | → unclassified/ | ไม่ gen PDF |

เพิ่ม keyword ใหม่ได้ที่ `NOTE_ROUTES` ใน `gen_pdf.py`

---

## ค่าใช้จ่ายโดยประมาณ

| รายการ | ราคา |
|--------|------|
| Claude API (~2000 รูป/เดือน) | ~$6/เดือน (~฿210) |
| Google Drive 15GB | ฟรี |
| Telegram Bot | ฟรี |
| Pi ค่าไฟ | ~฿30/เดือน |
| **รวม** | **~฿240/เดือน** |
