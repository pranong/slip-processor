# SlipProcessor — Skill Reference

## ภาพรวมระบบ

SlipProcessor เป็นระบบอัตโนมัติสำหรับประมวลผลสลิปโอนเงินธนาคาร รันบน Raspberry Pi
ใช้สำหรับงานบัญชีรายจ่ายของบริษัท โดยอ่านรูปสลิป → ดึงข้อมูลด้วย Claude Vision API →
แยกหมวดหมู่ → สร้างเอกสารบัญชี (PDF) → บันทึกลง Google Sheets เพื่อใช้ทำ dashboard และยื่นภาษี

ใช้สำหรับ: ผู้ดูแลระบบหรือ AI ที่ต้อง debug, แก้ไข, หรือต่อยอด feature ของระบบนี้

---

## Stack ที่ใช้

| ส่วน | เทคโนโลยี |
|------|-----------|
| Hardware | Raspberry Pi (hostname `pnkrwk`, user `punkrawk`, SSH port 2222) |
| ภาษา | Python 3.11 |
| AI | Claude Sonnet 4.6 (Anthropic API) — อ่าน slip ด้วย Vision |
| Storage | Google Drive (mount ผ่าน rclone, ไม่ใช่ local disk) |
| Database (ข้อมูล vendor + transactions) | Google Sheets ผ่าน gspread + Google Sheets/Drive API |
| Document generation | python-docx + LibreOffice (convert docx → PDF) |
| Control interface | Telegram Bot (python polling, ไม่ใช่ webhook) |
| Scheduler | crontab (รันตี 3 ทุกวัน) |

---

## โครงสร้างไฟล์ (โครงสร้างปัจจุบัน)

```
/app/uan/slip-processor/
├── README.md                  ← คู่มือ setup + rclone config
├── .gitignore
├── requirements.txt
│
├── run_pipeline.py            ← orchestrator หลัก (เรียก sort → gen → sync)
├── sort_slips.py               ← entry point: อ่าน slip + แยก folder + เช็คซ้ำ
├── gen_pdf.py                  ← entry point: gen เอกสาร PDF
├── telegram_bot.py             ← Telegram bot service (polling loop)
│
├── config/
│   ├── __init__.py
│   ├── config.py               ← system config: path, API key, Telegram, Sheets ID
│   └── gen_config.py           ← routing config: keyword → subfolder → template
│
├── utils/
│   ├── __init__.py
│   ├── notify.py                ← Telegram message helpers
│   ├── state.py                 ← local state (generated_log.json) แทนการเขียนลง Drive
│   ├── vendor.py                 ← โหลด vendor จาก GSheet + fuzzy match
│   ├── transactions.py           ← บันทึก transaction ลง Google Sheets พร้อม Drive link
│   ├── thai_baht_text.py        ← แปลงตัวเลขเป็นข้อความภาษาไทย (บาทถ้วน)
│   └── logger.py                ← log() = print() พร้อม timestamp
│
├── scripts/
│   ├── run.sh                   ← cron entry point (restart mount + รัน pipeline)
│   ├── reset.sh                 ← clear ข้อมูลทั้งหมดเพื่อเริ่มใหม่ (มี confirm prompt)
│   ├── setup_mount.sh           ← ติดตั้ง rclone mount เป็น systemd service
│   ├── setup_bot.sh             ← ติดตั้ง telegram bot เป็น systemd service
│   └── health_check.sh          ← เช็ค mount ทุก 5 นาที (cron)
│
├── data/                        ← runtime files, .gitignore, ไม่ commit
│   ├── processed_refs.json      ← ref ของสลิปที่เคย sort แล้ว (กันซ้ำ)
│   ├── generated_log.json       ← state ว่า PDF ไหน gen ไปแล้ว (local, ไม่ใช่บน Drive)
│   └── logs/
│
└── template/                     ← .gitignore (มีข้อมูลบริษัท)
    ├── ใบรับรองแทนใบเสร็จรับเงิน.docx           ← template บุคคลทั่วไป
    ├── ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx      ← template สำหรับ uan/ceramic
    └── ใบสำคัญรับเงิน.docx                       ← template เอกสารที่ 2 (ต้องมี vendor)
```

---

## Google Drive Structure

```
SlipProcessor/                  (root บน Google Drive)
├── rawFile/                    ← โยนรูป slip ที่นี่ (มือถือ/ผู้ใช้)
├── data/
│   ├── 2026/
│   │   ├── summary.json        ← สรุปยอดรายเดือน (สำหรับ dashboard)
│   │   └── JUN/
│   │       └── 24/
│   │           ├── images/     ← รูป slip ที่ sort แล้ว
│   │           ├── metadata/   ← JSON ข้อมูลที่ Claude อ่านได้ (1 ไฟล์ต่อ 1 slip)
│   │           └── docs/
│   │               ├── บุคคล/
│   │               │   ├── 20260624-ใบรับรองแทนใบเสร็จรับเงิน.pdf
│   │               │   └── ใบสำคัญรับเงิน/
│   │               │       └── 20260624-<ชื่อ vendor>.pdf
│   │               ├── uan/
│   │               └── ceramic/
│   └── unclassified/
│       ├── no_note/            ← slip ที่ไม่มี note
│       └── invalid/            ← อ่านไม่ได้ / ไม่ใช่ slip โอนเงิน
```

Mount point บน Pi: `/home/pi/slip-processor/{rawFile,data}` ผ่าน rclone (`--vfs-cache-mode full`)

**สำคัญ**: rclone mount อ่าน/เขียนทีละไฟล์ช้ามาก (~2 วิ/ไฟล์) ดังนั้นทุก process
ทำงานใน **local temp ก่อน แล้ว rclone copy ขึ้น Drive ทีเดียวตอนจบ** (ดู Performance Pattern ด้านล่าง)

---

## Google Sheets ที่ใช้ (2 sheets แยกกัน)

### 1. masterMapping (vendor reference data)
- Sheet ID: เก็บใน `config.py` → `GSHEET_ID`
- Tab `vendor_detail`: คอลัมน์ ชื่อ, เลขผู้เสียภาษี, บ้านเลขที่, หมู่, ถนน, แขวง/ตำบล, เขต/อำเภอ, จังหวัด, รหัสไปรษณีย์, หมายเหตุ
- ใช้สำหรับ map ชื่อผู้รับเงินใน slip → ข้อมูล vendor (สำหรับ gen ใบสำคัญรับเงิน)
- รองรับหลาย tab ในอนาคต (เช่น stock_detail)

### 2. transactions (transaction log / "database")
- Sheet ID: เก็บใน `config.py` → `TRANSACTIONS_SHEET_ID`
- Tab `transactions`: คอลัมน์ `date, category, vendor_name, note, amount, has_receipt, img_url, cert_url, receipt_url`
- `date` format: `YYYY-MM-DD` (ISO) เพื่อให้ Sheets/Looker Studio detect เป็น date type จริง ไม่ใช่ text
- เขียนหลัง sync ขึ้น Drive เสร็จแล้วเท่านั้น (ต้องมีไฟล์บน Drive ก่อนถึงจะหา webViewLink ได้)
- ใช้สำหรับต่อ Looker Studio ทำ dashboard และ export

ทั้งสอง Sheet share ให้ Service Account เดียวกัน (ดู Credentials ด้านล่าง)

---

## Pipeline หลัก (run_pipeline.py)

แบ่งเป็น 2 phase แยกกันชัดเจน เพื่อความเร็ว:

```
Phase 1 — Process (ทำงาน local ทั้งหมด เร็ว ไม่แตะ Drive ระหว่างทาง)
  1. รอ rawFile mount sync (sleep 10s)
  2. sort_slips.run()
     - rclone copy rawFile → local temp
     - Claude Vision อ่านแต่ละรูป (parallel 5 threads)
     - เช็คซ้ำ (ref เท่านั้น, ดู Dedup Logic ด้านล่าง)
     - แยกตาม note: มี note + มีวันที่ → local_data/YYYY/MMM/DD/
                     ไม่มี note → unclassified/no_note/
                     อ่านไม่ได้ → unclassified/invalid/
     - คืน local_data path (ยังไม่ upload)
  3. gen_pdf.run(local_data_path=...)
     - อ่าน metadata จาก local (ไม่ใช่ mount)
     - gen ใบรับรองแทนใบเสร็จรับเงิน (ทุก slip)
     - gen ใบสำคัญรับเงิน แยกตาม vendor (เฉพาะที่ match ใน GSheet)
     - คืน local_output path + _pending_transactions (ยังไม่ upload, ยังไม่บันทึก Sheets)

Phase 2 — Sync (ช้า แต่ไม่ block process)
  4. rclone copy local_data  → Drive (รูป + metadata)
  5. rclone copy local_output → Drive (PDF)
  6. clear_raw_files() — rclone delete rawFile (filter รองรับ uppercase/lowercase ext)
  7. append_transactions() — เขียนลง transactions Sheet (ทำหลัง sync เพราะต้องหา Drive link)
```

แต่ละ phase แจ้ง Telegram พร้อม timing (`fmt_duration()`) และ log มี timestamp ทุกบรรทัด (`utils/logger.py`)

---

## Note Routing (gen_config.py)

ระบบจัดกลุ่มเอกสารตาม keyword ใน field `note` ของ slip:

```python
NOTE_ROUTES = [
    {"keyword": "uan",     "subfolder": "uan",     "template": "ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx"},
    {"keyword": "ceramic", "subfolder": "ceramic", "template": "ใบรับรองแทนใบเสร็จรับเงินบริษัท.docx"},
]
NOTE_DEFAULT_SUBFOLDER = "บุคคล"
NOTE_DEFAULT_TEMPLATE  = "ใบรับรองแทนใบเสร็จรับเงิน.docx"
```

- เจอ keyword **ที่ไหนก็ได้** ใน note (ไม่ต้องขึ้นต้น), ไม่ case-sensitive
- เพิ่ม/ลด keyword แก้ที่ไฟล์นี้ที่เดียว ไม่ต้องแตะ `gen_pdf.py`

---

## Dedup Logic (sort_slips.py)

ปัญหาเดิม: เคยใช้ perceptual hash (phash) เช็คซ้ำก่อนเรียก API เพื่อประหยัด cost
แต่ slip จากธนาคารเดียวกัน (เช่น K+) มี layout เหมือนกันมาก ทำให้ phash diff = 0 เป๊ะ
แม้เนื้อหาต่างกันโดยสิ้นเชิง (คนละจำนวนเงิน คนละผู้รับ) เพราะ phash จับ low-frequency structure
ของภาพ ไม่ใช่ตัวอักษร/ตัวเลข — จุดที่พังคือ diff==0 เป็น fast-path ที่ข้ามการเช็ค ref ไปเลย
ลด threshold ของ range 1-8 เท่าไหร่ก็ไม่ช่วย เพราะ bug อยู่ที่ path diff==0 ต่างหาก

วิธีแก้ปัจจุบัน (2026-07-19, ตัดสินใจร่วมกับ user แล้วว่ายอมเสีย API cost):
**เอา phash ออกทั้งหมด เรียก Claude Vision อ่านทุกรูปเสมอ แล้วเช็คซ้ำด้วย `ref` เท่านั้น**

```
1. เรียก Claude Vision อ่านทุกรูป (ไม่มี phash pre-filter, ไม่มี fast-path ข้าม API)
2. ได้ ref มาแล้ว → เทียบกับ ref_db (data/processed_refs.json) ถ้าตรง = ซ้ำ
3. หลัง parallel เสร็จทั้งหมด → เช็ค ref ซ้ำอีกรอบจาก metadata ที่ sort ออกมา
   (กัน race condition กรณีสองรูปซ้ำกันเข้ามาพร้อมกันใน thread คนละตัว)
```

`ref` คือเลข transaction reference ที่ Claude ดึงจาก slip (field `ref` ใน prompt) — unique 100%
รองรับทุกธนาคารเพราะ prompt บอกให้ดึงจาก "เลขที่รายการ" / "Bank reference no." / "รหัสอ้างอิง" ฯลฯ

**ห้ามเอา phash กลับมาใช้เช็คซ้ำอีก** ต้นทุนที่เพิ่มจากการยิง API ทุกรูปมีน้อย (เดิมก็เรียก API
เกือบทุกกรณีอยู่แล้วเพื่อเอา ref ยกเว้นเคส diff==0 ที่ดันเป็นตัวบั๊กเอง) แลกกับความถูกต้อง 100%
ผู้ใช้จะระวังไม่โยนรูปไฟล์เดิมซ้ำเข้า rawFile เอง (ถ้าซ้ำ byte เดิมเป๊ะจะเสีย API 1 ครั้งแทนที่จะฟรี)

**Thread safety**: ทุกการเขียน `hash_db` หรือ `results` dict ต้องอยู่ใน `with lock:` block
ห้าม nest `with lock:` ซ้อนกัน (เคยทำให้ deadlock มาแล้ว — ดึง record มาเก็บตัวแปรก่อน ออกจาก lock แล้วค่อยเข้า lock ใหม่)

---

## Vendor Matching (utils/vendor.py)

3 ชั้น เรียงตามความแม่นยำ:

```
1. exact match       — ชื่อใน Sheet == to_name เป๊ะ
2. substring match    — ชื่อใน Sheet อยู่ใน to_name หรือกลับกัน
3. fuzzy match        — rapidfuzz token_sort_ratio > FUZZY_THRESHOLD (80%)
```

`to_name` มาจาก Claude prompt ที่แยก "ชื่อ-นามสกุลสะอาดๆ" ออกจากเลขบัญชี/ธนาคาร
(field แยกจาก `to_account` ที่เก็บข้อมูลเต็ม) — สำคัญเพราะชื่อดิบจาก slip มักมีขยะติดมา
เช่น `"นาย วิชา คงรอด xxx-x-x4799-x"` ต้อง clean ก่อนเอาไป match

ถ้าไม่เจอ vendor: ไม่ error, ไม่ unclassified — slip ยัง sort เข้า data ปกติ
แค่ **ไม่ gen ใบสำคัญรับเงิน** (gen แค่ใบรับรองแทนใบเสร็จฯ อย่างเดียว)

---

## State Management — สำคัญมาก

**อย่าใช้ field `pdf_generated` ใน metadata JSON บน Drive แบบเดิม** (deprecated)
เพราะการเขียนทับ JSON บน Drive mount ทีละไฟล์ช้ามาก (~2 วิ/ไฟล์)

ใช้ `utils/state.py` แทน:
- เก็บใน `data/generated_log.json` **บน local Pi เท่านั้น** ไม่ sync ขึ้น Drive
- key format: `{year}/{month}/{day}/{subfolder}` → `{slip_stem: {pdf_file, amount}}`
- `is_generated()`, `mark_generated()`, `reset_state()`, `load_state()`, `save_state()`

Regen แบบ bypass:
```bash
python3 gen_pdf.py --regen year 2026
python3 gen_pdf.py --regen month 2026/JUN
python3 gen_pdf.py --regen day 2026/JUN/24
```
หรือผ่าน Telegram: `/genYear -2026`, `/genMonth -2026/JUN`, `/genDay -2026/JUN/24`

---

## Performance Pattern — กฎเหล็กของระบบนี้

**ห้าม** อ่าน/เขียนไฟล์ผ่าน rclone mount ทีละไฟล์ในลูป (ช้ามาก ~2 วิ/operation)

**ต้อง** ทำแบบนี้เสมอเมื่อมี process ที่แตะ Drive หลายไฟล์:
```
1. rclone copy <remote> <local_temp>     ← ดึงข้อมูลที่ต้องใช้ทั้งหมดมาก่อน (1 ครั้ง)
2. ทำงานทั้งหมดใน local_temp              ← เร็ว ไม่จำกัด
3. rclone copy <local_temp> <remote>     ← อัปโหลดผลลัพธ์ทั้งหมดทีเดียว (1 ครั้ง)
```

ผลจากการ refactor ตาม pattern นี้: 7 นาที 54 วิ → 2 นาที 25 วิ (เร็วขึ้น ~3 เท่า) สำหรับ 16 รูป

ลบไฟล์บน Drive: ใช้ `rclone delete --include "*.pdf"` ไม่ใช่ `Path.unlink()` ผ่าน mount
`shutil.copy2()` ใช้ไม่ได้กับ rclone mount (ไม่ support xattr, จะ error `OSError: [Errno 5]`)
ต้องใช้ `shutil.copy()` (ไม่มี `2`) เท่านั้น

---

## Credentials & Config

`config/config.py` เก็บ (ห้าม commit ขึ้น git จริง ใส่ค่า production เฉพาะบน Pi):
```python
ANTHROPIC_API_KEY        = "..."
TELEGRAM_BOT_TOKEN       = "..."
TELEGRAM_CHAT_ID         = "..."
GSHEET_ID                = "..."   # masterMapping
TRANSACTIONS_SHEET_ID    = "..."   # transactions
GSHEET_CREDENTIALS       = f"{CODE_DIR}/config/gsheet_credentials.json"
```

`config/gsheet_credentials.json` = Google Service Account JSON key
ต้อง share ทั้ง 2 Google Sheets ให้ email ของ service account (รูปแบบ `xxx@project-id.iam.gserviceaccount.com`) สิทธิ์ Editor

APIs ที่ต้อง enable บน Google Cloud Console: **Google Sheets API** + **Google Drive API**
(Drive API จำเป็นสำหรับหา `webViewLink` ของไฟล์ใน `utils/transactions.py`)

---

## Telegram Bot Commands

| คำสั่ง | ทำอะไร |
|--------|--------|
| `/run` | sort + gen + sync ทั้งหมด |
| `/sort` | sort เท่านั้น |
| `/gen` | gen PDF เท่านั้น (เฉพาะที่ยังไม่ gen) |
| `/genYear -2026` | regen ทั้งปี (bypass state) |
| `/genMonth -2026/JUN` | regen ทั้งเดือน |
| `/genDay -2026/JUN/24` | regen วันเดียว |
| `/reloadvendor` | โหลด vendor list จาก GSheet ใหม่ (ปกติ auto reload ทุกครั้งที่ sort อยู่แล้ว) |
| `/status` | เช็ค mount Pi |
| `/help` | แสดงคำสั่งทั้งหมด |

Bot รันเป็น systemd service (`slip-bot.service`) ใช้ polling ไม่ใช่ webhook
แก้ `telegram_bot.py` แล้วต้อง `sudo systemctl restart slip-bot.service` เสมอ

---

## คำสั่งที่ใช้บ่อยตอน debug บน Pi

```bash
# เช็ค service
sudo systemctl status rclone-rawfile.service
sudo systemctl status rclone-data.service
sudo systemctl status slip-bot.service

# restart mount (ถ้า I/O error หรือ rawFile sync ช้า)
sudo systemctl restart rclone-data.service
sleep 10
mountpoint /home/pi/slip-processor/data

# รัน pipeline แบบ manual
cd /app/uan/slip-processor
python3 run_pipeline.py

# reset ทุกอย่าง (มี confirm prompt, ลบ Drive data + local state + transactions sheet)
bash scripts/reset.sh

# เช็คว่า service account เห็น Sheet ไหม
python3 -c "from utils.vendor import load_vendors; print(load_vendors(force_reload=True))"
```

---

## ข้อผิดพลาดที่เคยเกิดและวิธีแก้ (อย่าทำซ้ำ)

| ปัญหา | สาเหตุ | วิธีแก้ |
|-------|--------|---------|
| `OSError: [Errno 5]` ตอน copy | `shutil.copy2()` ใช้ xattr ที่ rclone ไม่ support | ใช้ `shutil.copy()` |
| sort/gen ช้ามาก (นาทีถึงหลักสิบนาที) | อ่าน/เขียนผ่าน rclone mount ทีละไฟล์ | local staging pattern (ดูด้านบน) |
| Telegram ส่ง 2 ครั้ง / เนื้อหาผิด | route เก่ายังไม่ลบหลัง refactor | ดู `send_sort_summary`/`send_gen_summary` ให้ตรงกับ field ปัจจุบัน |
| `RuntimeError`/deadlock ใน threading | `with lock:` ซ้อนกัน | ดึง record ออกมาก่อน ปิด lock แล้วค่อยเปิดใหม่ |
| phash false positive (K+ slip ต่างกันแต่ถูกจับว่าซ้ำ) | phash diff==0 เป็น fast-path ที่ข้ามการเช็ค ref ไปเลย ลด threshold ไม่ช่วย | เอา phash ออกทั้งหมด เช็คซ้ำด้วย ref อย่างเดียว (ดู Dedup Logic ด้านบน) |
| `processed_refs.json` ทำให้ sort ซ้ำไม่ได้ตอน test | ref ค้างจากรอบก่อน | `bash scripts/reset.sh` ก่อน test ใหม่เสมอ |
| Transactions Sheet ไม่มี URL | เรียก `append_transactions()` ก่อน sync ไฟล์ขึ้น Drive จริง | ต้องเรียกหลัง Phase 2 (sync) เสร็จเท่านั้น |
| `rclone delete` หาไฟล์ไม่เจอ | filter `--include "*.jpg"` ไม่ match `.JPG` (case-sensitive) | ใส่ทั้ง lowercase และ UPPERCASE ใน `--include` หรือใช้ `--filter` |
| Pi เห็นรูปใหม่ใน rawFile ช้า | `--dir-cache-time 5m` ของ rclone mount | รอ หรือลด cache time ใน service file |

---

## หลักการเวลาขอความช่วยเหลือจาก AI ตัวอื่น (Claude Code, ChatGPT, ฯลฯ)

ถ้าจะให้ AI ตัวอื่นช่วยต่อยอดระบบนี้ ให้ context เพิ่มเติมเหล่านี้เสมอ:

1. ระบบรันบน Raspberry Pi, ผ่าน SSH เท่านั้น ไม่มี GUI
2. Google Drive mount ผ่าน rclone ไม่ใช่ local filesystem — I/O ช้ามากถ้าไม่ทำตาม Performance Pattern
3. ภาษาที่ใช้ในระบบ (variable, log message, comment) เป็นภาษาไทยปนอังกฤษ ให้คงรูปแบบเดิม
4. ห้ามแก้ field name ใน Google Sheets header โดยไม่ migrate ข้อมูลเก่า
5. การเปลี่ยน dedup logic หรือ vendor matching logic ต้องระวัง false positive/negative สูง เพราะกระทบเรื่องเงินจริง
