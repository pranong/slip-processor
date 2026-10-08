# CLAUDE.md

คู่มือสำหรับ Claude Code เมื่อทำงานกับ repo นี้ — รายละเอียดเต็มดูที่ [SKILL.md](SKILL.md)

## ⚠️ กฎที่ห้ามละเมิด

**ห้ามรัน/compile โค้ดนี้บนเครื่อง local เด็ดขาด** — ระบบนี้รันบน Raspberry Pi เท่านั้น
(hostname `pnkrwk`, user `punkrawk`, SSH port 2222) ต้องให้ผู้ใช้รันบน Pi แล้ว paste ผลลัพธ์
(journalctl, ps aux, ฯลฯ) กลับมาให้ดูเสมอ — อย่าสมมติ/เดาผลลัพธ์

## ภาพรวมระบบ

อ่านรูปสลิปโอนเงินธนาคาร → Claude Vision ดึงข้อมูล → แยกหมวดหมู่ → gen เอกสารบัญชี (PDF) →
บันทึก Google Sheets ควบคุมผ่าน Telegram Bot (polling) รัน manual ผ่าน Telegram (ไม่มี cron แล้ว)

Stack: Python 3.11, Claude Sonnet (Vision), Google Drive ผ่าน rclone mount (ไม่ใช่ local disk),
Google Sheets ผ่าน gspread, python-docx + LibreOffice (docx→PDF), Telegram Bot polling

## กฎเหล็ก: Performance Pattern

rclone mount อ่าน/เขียนทีละไฟล์ช้ามาก (~2 วิ/ไฟล์) และ Google Drive/Sheets API มี quota จำกัด
(เคยชน 403 rateLimitExceeded จาก mount poll ถี่เกินไปมาแล้ว — ตอนนี้ตั้ง `--poll-interval` ยาวขึ้นแล้ว)

**ทุก process ที่แตะ Drive หลายไฟล์ ต้อง**: `rclone copy` มา local temp ก่อน (1 ครั้ง) →
ทำงานทั้งหมดใน local → `rclone copy` กลับขึ้น Drive ทีเดียว (1 ครั้ง) — ห้ามอ่าน/เขียนในลูปทีละไฟล์

หลักการเดียวกันใช้กับ Google Sheets: `utils/transactions.py`'s `append_transactions()` เขียน
ข้อมูลหลัก (date/amount/note/ref) ลง Sheet **ก่อน** โดยเว้น URL ว่างไว้ (phase 1, ไม่มี Drive API
call) แล้วค่อยหา `webViewLink` มาเติม G/H/I ทีหลัง (phase 2) — กันข้อมูลเงินช้าเพราะรอ Drive lookup

## Dedup Logic — สำคัญมาก

เช็คซ้ำด้วย **`ref`** (bank transaction reference, unique 100%) เท่านั้น เทียบกับ
`data/processed_refs.json` **ห้ามเอา phash (perceptual hash) กลับมาใช้** — เคย false-positive
กับสลิปธนาคารเดียวกันที่ layout เหมือนกันมาก (ดู SKILL.md § Dedup Logic)

**ข้อควรระวัง**: `processed_refs.json` เก็บแยกจากไฟล์ metadata จริงบน Drive — ถ้า metadata ถูกลบ
แต่ ref ยังอยู่ในไฟล์นี้ การโยนรูปสลิปตัวเดิมเข้า `rawFile` ใหม่จะถูกมองว่าซ้ำและข้ามไปเฉยๆ (ไม่ error,
ไม่เขียนใหม่) ต้องลบ ref ออกจาก `processed_refs.json` ก่อนถ้าต้องการบังคับประมวลผลใหม่

## Note Routing → Category

`category` (uan/ceramic/บุคคล) **ไม่ได้ถูกเก็บลง metadata JSON** — คำนวณสดใหม่ทุกครั้งจาก field
`note` ของสลิปผ่าน `get_route(note)` ใน [gen_pdf.py](gen_pdf.py) เทียบกับ `NOTE_ROUTES` ใน
[config/gen_config.py](config/gen_config.py) (เจอ keyword ที่ไหนก็ได้ในข้อความ, ไม่ case-sensitive)

แก้ category ของสลิปที่ผิดหมวดได้โดยแก้ `note` ใน metadata JSON ตรงๆ แล้ว regen ใหม่
(`/genDoc` + `/genTransaction` scope เดียวกัน) — แต่ไฟล์ PDF เก่าใน category เดิมจะไม่ถูกลบอัตโนมัติ
(path เปลี่ยน folder ไปเลย) ต้องลบไฟล์เก่าด้วยมือ

## Google Sheets Schema (transactions)

คอลัมน์ A-K: `date, category, vendor_name, note, amount, has_receipt, img_url, cert_url,
receipt_url, ref, comment` — `ref` (J) ใช้จับคู่แถวเดิมตอนเขียนซ้ำ, `comment` (K) ไม่ว่าง =
แถวนี้ถูก void แล้ว (ดู `/genTransaction`)

## Telegram Bot Commands ที่ใช้บ่อย

| คำสั่ง | ทำอะไร |
|--------|--------|
| `/run` | sort + gen + sync + บันทึก transactions ทั้งหมด |
| `/genDoc [ปี] [เดือน] [วัน]` | regen เอกสาร (PDF) เท่านั้น — **ไม่บันทึก Sheet** |
| `/genTransaction [ปี] [เดือน] [วัน]` | void แถวเดิมที่ live (zero amount + comment + ไฮไลต์แดง) แล้ว insert ใหม่จาก metadata — **ไม่ gen PDF** |

ทั้ง `/genDoc`/`/genTransaction` ใช้ wizard เดียวกัน (ปี 0=ทุกปี→เดือน 0=ทั้งปี→วัน 0=ทั้งเดือน)
implement เป็น flow กลาง `"scope_cmd"` ใน [telegram_bot.py](telegram_bot.py) — เพิ่มคำสั่ง
scope-wizard ใหม่ให้ reuse flow นี้ ไม่ต้องเขียนใหม่

แก้ `telegram_bot.py`/`gen_pdf.py`/`utils/transactions.py` แล้วต้อง deploy ขึ้น Pi + restart เสมอ
โค้ด local ไม่มีผลกับ bot ที่รันจริงจนกว่าจะ `git pull` + `sudo systemctl restart slip-bot.service`
บน Pi

## คำสั่ง debug บน Pi (รันตรงบน Pi ไม่ต้อง wrap ssh ถ้า SSH อยู่แล้ว)

```bash
sudo journalctl -u slip-bot.service -n 200 --no-pager   # log ย้อนหลัง
sudo journalctl -u slip-bot.service -f                   # log real-time
sudo systemctl restart slip-bot.service
mountpoint /home/pi/slip-processor/data
mountpoint /home/pi/slip-processor/rawFile
```

## ข้อผิดพลาดที่เคยเกิด (ดูละเอียดใน SKILL.md § ข้อผิดพลาดที่เคยเกิด)

- `shutil.copy2()` พังบน rclone mount (ไม่ support xattr) → ใช้ `shutil.copy()` เท่านั้น
- Telegram group chat Privacy Mode บล็อก plain-text reply ของ wizard → ต้อง `/setprivacy` Disable ผ่าน @BotFather
- Drive API 403 quota exceeded จาก mount poll ถี่เกินไป → ปรับ `--poll-interval` ให้ยาวขึ้น/ปิด
- sync ขึ้น Drive fail กลางทาง → `rawFile` ปลอดภัยเสมอ (ไม่ลบจนกว่า sync สำเร็จ) แต่ local temp
  (`/tmp/tmpXXXXXXXX/{data,output}`) ที่ sort/gen เสร็จแล้วไม่ถูกลบตอน sync fail — sync ไฟล์เดิม
  ขึ้น Drive ตรงๆ ได้โดยไม่ต้องอ่านสลิปใหม่ (ประหยัด API)
