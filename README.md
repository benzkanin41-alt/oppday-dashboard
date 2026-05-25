# OPPDAY Dashboard

Local dashboard สำหรับอ่าน Oppday แยกตามหุ้นและไตรมาส

## Online

GitHub Pages:

```text
https://benzkanin41-alt.github.io/oppday-dashboard/
```

Repository:

```text
https://github.com/benzkanin41-alt/oppday-dashboard
```

## Run

```powershell
python .\server.py
```

เปิดเบราว์เซอร์ที่:

```text
http://127.0.0.1:8766
```

## Data Sources

- Past quarters: `D:\OneDrive\stock\OPPDAY\PAST`
- Current quarter: `D:\OneDrive\stock\OPPDAY\1Q69\Oppday\สรุป oppday`

Dashboard จะสแกนไฟล์ `.docx`, `.md`, `.pdf`, `.txt` และจับคู่ไฟล์สรุป/PDF ที่เป็นหุ้นเดียวกันในไตรมาสเดียวกัน

บน GitHub Pages จะ publish เฉพาะ static JSON/text เพื่อให้เปิดบน iPhone/iPad/Desktop ได้เร็ว ไม่ upload PDF ต้นฉบับก้อนใหญ่ขึ้น GitHub

สำหรับ `1Q69` ให้ใช้ Markdown summary เป็นหลัก และถ้าบางรายการยังไม่มี Markdown แต่มี PDF เท่านั้น ระบบจะ extract ข้อความจาก PDF เป็น Markdown text สำหรับอ่าน online แทน ส่วน PDF historical สามารถ upload เพิ่มเป็นรอบๆ ภายหลังถ้าต้องการเปิดไฟล์ presentation ต้นฉบับบน online dashboard

ถ้าเจอ PDF historical ที่ยังไม่มี Markdown ให้รัน:

```powershell
python -X utf8 .\scripts\convert_historical_pdfs_to_markdown.py
```

script จะสร้าง `.md` ไว้ใน OneDrive folder เดียวกับ PDF ต้นฉบับ และ dashboard จะใช้ Markdown นั้นในการ deploy ขึ้น GitHub Pages

## Refresh

- กดปุ่ม refresh ในหน้า dashboard เพื่อ rescan ทันที
- Server จะ rescan อัตโนมัติทุกวันเวลา 18:00 ขณะที่ `server.py` กำลังรันอยู่
- API `/api/index` จะ refresh cache เองถ้า cache เกิน 15 นาที
- Codex automation `Update OPPDAY dashboard data` จะ build/push static GitHub Pages data ทุกวันเวลา 18:00
