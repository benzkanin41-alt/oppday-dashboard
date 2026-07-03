from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().with_name("fix_macro_thai_text.py")
text = path.read_text(encoding="utf-8")
old = '''    if not changed:
        raise RuntimeError("No macro Thai text replacements were applied")
    MACRO.write_text(text, encoding="utf-8")
'''
new = '''    if not changed:
        print("macro Thai text already clean")
        return
    MACRO.write_text(text, encoding="utf-8")
'''
if old in text:
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
print("helper patched or already clean")
