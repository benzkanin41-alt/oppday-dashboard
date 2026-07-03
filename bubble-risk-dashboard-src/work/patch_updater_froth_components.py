from pathlib import Path


path = Path("work/update_local_dashboard_full.py")
text = path.read_text(encoding="utf-8")

if '"work/update_froth_components_fred.py"' not in text:
    text = text.replace(
        '    "work/enhance_dashboard_v04.py",\n'
        '    "work/clean_payload_user_text.py",\n',
        '    "work/enhance_dashboard_v04.py",\n'
        '    "work/update_froth_components_fred.py",\n'
        '    "work/clean_payload_user_text.py",\n',
    )

if '"work/validate_froth_components_populated.py"' not in text:
    text = text.replace(
        '    "work/validate_macro_v04_nonzero.py",\n'
        '    "work/validate_ai_direct_v08.py",\n',
        '    "work/validate_macro_v04_nonzero.py",\n'
        '    "work/validate_froth_components_populated.py",\n'
        '    "work/validate_ai_direct_v08.py",\n',
    )

if '"work/update_froth_components_fred.py": 180' not in text:
    text = text.replace(
        '    "work/enhance_dashboard_v04.py": 720,\n',
        '    "work/enhance_dashboard_v04.py": 720,\n'
        '    "work/update_froth_components_fred.py": 180,\n',
    )

path.write_text(text, encoding="utf-8")
print("patched_updater_froth_components")
