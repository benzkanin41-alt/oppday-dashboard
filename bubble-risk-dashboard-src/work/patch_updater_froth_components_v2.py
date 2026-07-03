from pathlib import Path


path = Path("work/update_local_dashboard_full.py")
lines = path.read_text(encoding="utf-8").splitlines()

if not any("work/update_froth_components_fred.py" in line for line in lines):
    for idx, line in enumerate(lines):
        if line.strip() == '"work/enhance_dashboard_v04.py",':
            lines.insert(idx + 1, '    "work/update_froth_components_fred.py",')
            break

if not any("work/validate_froth_components_populated.py" in line for line in lines):
    for idx, line in enumerate(lines):
        if line.strip() == '"work/validate_macro_v04_nonzero.py",':
            lines.insert(idx + 1, '    "work/validate_froth_components_populated.py",')
            break

if not any('"work/update_froth_components_fred.py": 180' in line for line in lines):
    for idx, line in enumerate(lines):
        if line.strip() == '"work/enhance_dashboard_v04.py": 720,':
            lines.insert(idx + 1, '    "work/update_froth_components_fred.py": 180,')
            break

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("patched_updater_froth_components_v2")
