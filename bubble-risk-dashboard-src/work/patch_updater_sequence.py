from pathlib import Path

p = Path("work/update_local_dashboard_full.py")
s = p.read_text(encoding="utf-8-sig")
needle = '    "work/rebuild_clean_macro.py",\n'
insert = '    "work/patch_dashboard_full_price_universe.py",\n'
if insert not in s:
    s = s.replace(needle, needle + insert)
p.write_text(s, encoding="utf-8")
print(insert in s)
