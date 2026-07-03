from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "work" / "update_local_dashboard_full.py"


def insert_once(text: str, needle: str, insert: str) -> str:
    if insert.strip() in text:
        return text
    if needle not in text:
        raise RuntimeError(f"Needle not found: {needle!r}")
    return text.replace(needle, needle + insert, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    text = insert_once(
        text,
        '    "work/rebuild_clean_interactive.py",\n',
        '    "work/patch_thailand_heat_mai_treasury.py",\n',
    )
    text = insert_once(
        text,
        '    "work/validate_froth_components_populated.py",\n',
        '    "work/validate_thailand_heat_mai_treasury.py",\n',
    )
    text = insert_once(
        text,
        '    "work/patch_dashboard_full_price_universe.py": 420,\n',
        '    "work/patch_thailand_heat_mai_treasury.py": 180,\n',
    )
    TARGET.write_text(text, encoding="utf-8")
    print("update_local_dashboard_full.py patched")


if __name__ == "__main__":
    main()
