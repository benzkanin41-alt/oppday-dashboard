from pathlib import Path


target = Path(__file__).resolve().parent / "patch_thailand_heat_mai_treasury.py"
lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
changed = False
for i, line in enumerate(lines):
    if "data_json" in line and "+ r" in line and "\\1" in line and "\\3" in line:
        lines[i] = "        lambda m: m.group(1) + data_json + m.group(3),\n"
        changed = True
        break
if not changed:
    raise SystemExit("target JSON replacement line not found")
target.write_text("".join(lines), encoding="utf-8")
print("patched JSON regex replacement")
