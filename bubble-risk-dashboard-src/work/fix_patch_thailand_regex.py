from pathlib import Path


target = Path(__file__).resolve().parent / "patch_thailand_heat_mai_treasury.py"
text = target.read_text(encoding="utf-8")
old = '        r"\\\\1" + data_json + r"\\\\3",\n'
new = "        lambda m: m.group(1) + data_json + m.group(3),\n"
if old not in text:
    raise SystemExit("target replacement line not found")
target.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched JSON regex replacement")
