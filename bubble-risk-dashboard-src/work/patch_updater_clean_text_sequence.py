from pathlib import Path


p = Path("work/update_local_dashboard_full.py")
s = p.read_text(encoding="utf-8-sig")
clean = '    "work/clean_payload_user_text.py",\n'
if clean not in s:
    s = s.replace(
        '    "work/enhance_dashboard_v04.py",\n',
        '    "work/enhance_dashboard_v04.py",\n' + clean,
    )
p.write_text(s, encoding="utf-8")
print("clean_payload_user_text.py" in s)
