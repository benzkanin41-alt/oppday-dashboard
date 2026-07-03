from pathlib import Path


p = Path("work/update_local_dashboard_full.py")
s = p.read_text(encoding="utf-8-sig")

if "STEP_TIMEOUTS" not in s:
    s = s.replace(
        'STEPS = [\n',
        'STEPS = [\n',
    )
    insert_after = ']\n\n\n'
    timeout_block = '''\nSTEP_TIMEOUTS = {\n    "work/enhance_dashboard_v04.py": 720,\n    "work/enhance_dashboard_interactive_v03.py": 420,\n    "work/patch_dashboard_full_price_universe.py": 420,\n}\n\n\n'''
    first_close = s.find(insert_after, s.find("STEPS = ["))
    if first_close != -1:
        s = s[: first_close + len(insert_after)] + timeout_block + s[first_close + len(insert_after) :]

s = s.replace("timeout=240,", "timeout=STEP_TIMEOUTS.get(script, 240),")
p.write_text(s, encoding="utf-8")
print("STEP_TIMEOUTS" in s and "timeout=STEP_TIMEOUTS.get(script, 240)" in s)
