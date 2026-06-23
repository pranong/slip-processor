# rclone Setup — คู่มือตั้งค่าละเอียด (Raspberry Pi + Google Drive)

## ก่อนเริ่ม
- Pi ต้องต่อ internet แล้ว
- มี Google Account พร้อมใช้
- ต้องมี Mac/PC อีกเครื่องสำหรับ login Google (เพราะ Pi ไม่มี browser)

---

## ขั้นที่ 1 — ลง rclone

```bash
sudo apt update
sudo apt install rclone fuse3
```

เช็คว่าลงสำเร็จ:
```bash
rclone version
# ต้องเห็น rclone vX.XX.X
```

---

## ขั้นที่ 2 — ตั้งค่า remote

```bash
rclone config
```

จะเห็น:
```
No remotes found, make a new one?
n) New remote
q) Quit config
n/s/q> _
```

### 2.1 — พิมพ์ `n` แล้ว Enter
```
Enter name for new remote.
name> gdrive
```
⚠️ ชื่อต้องตรงกับใน config.py (default = `gdrive`)

### 2.2 — เลือก Storage type
จะเห็นรายการยาวมาก หา Google Drive:
```
Storage> drive
```
หรือพิมพ์เลขที่อยู่ข้างหน้า `Google Drive` ก็ได้

### 2.3 — Client ID
```
client_id>
```
กด **Enter เฉยๆ** (ใช้ค่า default ของ rclone)

### 2.4 — Client Secret
```
client_secret>
```
กด **Enter เฉยๆ**

### 2.5 — Scope
```
scope>
```
พิมพ์ `1` แล้ว Enter (= Full access)
```
1 / Full access all files, excluding Application Data Folder.
  \ (drive)
```

### 2.6 — Service Account File
```
service_account_file>
```
กด **Enter เฉยๆ**

### 2.7 — Advanced config
```
Edit advanced config?
y/n> n
```

### 2.8 — Auto config ⚠️ จุดสำคัญ!
```
Use auto config?
y/n> n
```
⚠️ **ต้องเลือก `n`** เพราะ Pi ไม่มี browser!

จะเห็น:
```
Option config_token.
For this to work, you will need rclone available on a machine that has
a web browser available.

For more help and alternate methods see: https://rclone.org/remote_setup/

Execute the following on the machine with the web browser (same rclone
version recommended):

    rclone authorize "drive"

Then paste the result.
config_token> _
```

### 2.9 — ไปทำบน Mac/PC ตอนนี้!

เปิด Terminal บน **Mac/PC** (ไม่ใช่ Pi):
```bash
# ลง rclone บน Mac ก่อน (ถ้ายังไม่มี)
brew install rclone

# หรือ Windows: ดาวน์โหลดจาก https://rclone.org/downloads/

# แล้วรัน:
rclone authorize "drive"
```

จะเปิด browser อัตโนมัติ:
```
1. เลือก Google Account ของคุณ
2. กด "Allow" อนุญาตให้ rclone เข้าถึง Drive
3. เห็นหน้า "Success!" ปิด browser ได้เลย
```

กลับมาที่ Terminal บน Mac/PC จะเห็น:
```
Paste the following into your remote machine --->
{"access_token":"ya29.xxxxx","token_type":"Bearer"...}
<---End paste
```

### 2.10 — copy token กลับไปวางใน Pi

copy ข้อความ `{"access_token":...}` ทั้งก้อน
กลับไปที่ Terminal ของ Pi แล้ว **วางลงไป**:
```
config_token> {"access_token":"ya29.xxxxx","token_type":"Bearer"...}
```
กด Enter

### 2.11 — Shared Drive
```
Configure this as a Shared Drive (Team Drive)?
y/n> n
```

### 2.12 — ยืนยัน
```
Keep this "gdrive" remote?
y) Yes this is OK
e) Edit this remote
d) Delete this remote
y/e/d> y
```

### 2.13 — ออก
```
q) Quit config
q
```

---

## ขั้นที่ 3 — ทดสอบ

```bash
# ดู files บน Drive
rclone ls gdrive:

# สร้าง folder ทดสอบ
rclone mkdir gdrive:test-folder

# ดูว่ามีไหม
rclone lsd gdrive:

# ลบ folder ทดสอบ
rclone rmdir gdrive:test-folder
```

ถ้าเห็นไฟล์ใน Drive = **สำเร็จ!** ✅

---

## ขั้นที่ 4 — รัน setup_mount.sh

```bash
chmod +x /home/pi/slip-processor/setup_mount.sh
bash /home/pi/slip-processor/setup_mount.sh
```

script จะทำให้อัตโนมัติ:
- สร้าง folders บน Drive (SlipProcessor/rawFile, SlipProcessor/data)
- สร้าง systemd service สำหรับ mount
- เปิด auto-start ตอนบูท
- mount ทั้ง rawFile และ data

---

## เช็คสถานะ mount

```bash
# เช็คว่า mount อยู่
mountpoint -q /home/pi/slip-processor/rawFile && echo "✅ rawFile OK" || echo "❌ rawFile ไม่ mount"
mountpoint -q /home/pi/slip-processor/data && echo "✅ data OK" || echo "❌ data ไม่ mount"

# ดู service status
sudo systemctl status rclone-rawfile.service
sudo systemctl status rclone-data.service

# ถ้ามีปัญหา ดู log
cat /home/pi/slip-processor/logs/mount_rawfile.log
cat /home/pi/slip-processor/logs/mount_data.log

# restart mount
sudo systemctl restart rclone-rawfile.service
sudo systemctl restart rclone-data.service
```

---

## Troubleshooting

| ปัญหา | วิธีแก้ |
|--------|---------|
| `FUSE not found` | `sudo apt install fuse3` |
| `mount failed` | `sudo modprobe fuse` แล้วลอง mount ใหม่ |
| `transport: oauth2: token expired` | `rclone config reconnect gdrive:` แล้วทำ authorize ใหม่ |
| mount หลุดบ่อย | health_check.sh จะ remount + แจ้ง Telegram ให้อัตโนมัติ |
| Pi reboot แล้ว mount หาย | ไม่หาย! systemd จะ mount ให้อัตโนมัติ |
