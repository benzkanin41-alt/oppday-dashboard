from pathlib import Path


p = Path("work/update_local_dashboard_full.py")
s = p.read_text(encoding="utf-8-sig")

v04_step = '    "work/enhance_dashboard_v04.py",\n'
if v04_step not in s:
    s = s.replace(
        '    "work/enhance_dashboard_interactive_v03.py",\n',
        '    "work/enhance_dashboard_interactive_v03.py",\n' + v04_step,
    )

macro_validation = '    "work/validate_macro_v04_nonzero.py",\n'
if macro_validation not in s:
    s = s.replace(
        '    "work/validate_ai_direct_v08.py",\n',
        macro_validation + '    "work/validate_ai_direct_v08.py",\n',
    )

p.write_text(s, encoding="utf-8")
print("enhance_dashboard_v04.py" in s, "validate_macro_v04_nonzero.py" in s)
