# Slip Processor — คู่มือติดตั้ง

## สิ่งที่ต้องเตรียม

| # | รายการ | วิธี |
|---|--------|------|
| 1 | Anthropic API Key | สมัครที่ console.anthropic.com → API Keys |
| 2 | Line Notify Token | สมัครที่ notify-bot.line.me → Generate Token |
| 3 | Google Account | มี Gmail ก็พอ |
| 4 | Raspberry Pi | Pi 4 (2GB+) แนะนำ |

## ติดตั้งบน Pi

```bash
# 1. ลง dependencies
sudo apt update
sudo apt install rclone libreoffice-writer fuse3
pip3 install -r requirements.txt --break-system-packages

# 2. ตั้ง timezone
sudo timedatectl set-timezone Asia/Bangkok

# 3. ตั้งค่า rclone (ทำครั้งเดียว)
rclone config
# → New remote → ชื่อ: gdrive → Type: Google Drive → ทำตาม wizard

# 4. วาง files
cp -r slip-processor/ /home/pi/slip-processor/
cp ใบรับรองแทนใบเสร็จรับเงิน.docx /home/pi/slip-processor/template/

# 5. ใส่ API keys
nano /home/pi/slip-processor/config.py     # LINE_TOKEN
nano /home/pi/slip-processor/run.sh        # ANTHROPIC_API_KEY
nano /home/pi/slip-processor/health_check.sh  # LINE_TOKEN

# 6. ให้สิทธิ์ script
chmod +x /home/pi/slip-processor/*.sh

# 7. Setup mount (รันครั้งเดียว)
bash /home/pi/slip-processor/setup_mount.sh

# 8. ตั้ง crontab
crontab -e
# เพิ่มบรรทัด:
# 0 3 * * * /home/pi/slip-processor/run.sh >> /home/pi/slip-processor/logs/cron.log 2>&1
# */5 * * * * /home/pi/slip-processor/health_check.sh
```

## วิธีใช้งาน

1. **มือถือ**: screenshot slip → เปิด Google Drive app → วางไฟล์ใน `SlipProcessor/rawFile/`
2. **Pi**: รัน pipeline อัตโนมัติตอนตี 3
3. **Mac/PC**: เปิด Google Drive → folder `SlipProcessor/data/` → ดูผลลัพธ์ + ใช้ Cowork วิเคราะห์

## โครงสร้าง Google Drive

```
SlipProcessor/
  rawFile/                ← โยนรูป slip ที่นี่
  data/
    2569/
      summary.json        ← Cowork อ่านไฟล์นี้
      backups/            ← backup summary อัตโนมัติ
      JAN/
        01/
          images/          ← รูป slip + JSON ข้อมูล
          docs/
            ใบรับรองแทนใบเสร็จรับเงิน_001.pdf
        02/
        ...
      FEB/
      ...
    unclassified/          ← รูปที่อ่านไม่ได้ (จัดการ manual)
```

## โครงสร้างบน Pi

```
/home/pi/slip-processor/
  config.py               ← ตั้งค่าทั้งหมด
  sort_slips.py            ← อ่าน slip + แยก folder
  gen_pdf.py               ← gen PDF ใบรับรองฯ
  thai_baht_text.py        ← แปลงตัวเลข → ภาษาไทย
  notify.py                ← Line Notify
  run_pipeline.py          ← orchestrator
  run.sh                   ← crontab เรียกไฟล์นี้
  setup_mount.sh           ← ตั้ง mount ครั้งแรก
  health_check.sh          ← เช็ค mount ทุก 5 นาที
  requirements.txt
  template/
    ใบรับรองแทนใบเสร็จรับเงิน.docx
  rawFile/                 ← mount จาก Drive
  data/                    ← mount ไป Drive
  processed_hashes.json    ← เช็ครูปซ้ำ
  logs/                    ← log ทุกรอบ
```

## ค่าใช้จ่ายโดยประมาณ

| รายการ | ราคา |
|--------|------|
| Claude API (~2000 รูป/เดือน) | ~$6/เดือน (~฿210) |
| Google Drive 15GB | ฟรี |
| Line Notify | ฟรี |
| Pi ค่าไฟ | ~฿30/เดือน |
| **รวม** | **~฿240/เดือน** |
