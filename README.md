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

## Run (registry-bound)

Do not run `server.py` directly and do not select a numeric port manually. Resolve stable ID `oppday-dashboard`, then use the registered launcher:

```powershell
python -X utf8 "C:\Users\USER\Documents\Codex\LocalDashboardPorts\dashboard_ports.py" resolve --id oppday-dashboard --json
& "C:\Users\USER\Documents\Codex\LocalDashboardPorts\Start Oppday Dashboard.ps1"
```

The launcher injects `OPPDAY_DASHBOARD_PORT`, refuses a conflicting fingerprint, and never falls back to another port. Use the URL returned by the registry.

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

ถ้าต้องการแปลง PDF ของ `1Q69` ในโฟลเดอร์วันที่ใดวันที่หนึ่งเป็น Markdown ให้รัน:

```powershell
python -X utf8 .\scripts\convert_current_pdfs_to_markdown.py --folder "D:\OneDrive\stock\OPPDAY\1Q69\Oppday\สรุป oppday\2026-05-25"
```

script จะสร้าง `.md` ไว้ข้าง PDF ต้นฉบับใน OneDrive เช่นเดียวกัน

## Refresh

- กดปุ่ม refresh ในหน้า dashboard เพื่อ rescan ทันที
- Server จะ rescan อัตโนมัติทุกวันเวลา 18:00 ขณะที่ `server.py` กำลังรันอยู่
- API `/api/index` จะ refresh cache เองถ้า cache เกิน 15 นาที
- Codex automation `Update OPPDAY dashboard data` จะ build/push static GitHub Pages data ทุกวันเวลา 18:00
