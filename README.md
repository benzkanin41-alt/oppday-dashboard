# OPPDAY Dashboard

Local dashboard สำหรับอ่าน Oppday แยกตามหุ้นและไตรมาส

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

## Refresh

- กดปุ่ม refresh ในหน้า dashboard เพื่อ rescan ทันที
- Server จะ rescan อัตโนมัติทุกวันเวลา 18:00 ขณะที่ `server.py` กำลังรันอยู่
- API `/api/index` จะ refresh cache เองถ้า cache เกิน 15 นาที
