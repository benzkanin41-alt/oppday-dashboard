from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "work" / "rebuild_clean_macro.py"


def main() -> None:
    text = MACRO.read_text(encoding="utf-8")
    replacements = {
        "เธ\xa0เธฒเธฉเธฒเนเธ—เธข/English mix. Data rows below are calculated from actual source series where available; qualitative checklists are labelled separately.":
            "ภาษาไทย/English mix. Data rows below are calculated from actual source series where available; qualitative checklists are labelled separately.",
        "เธเธฐเนเธเธเธฃเธงเธกเธขเธฑเธเธญเธขเธนเนเนเธเธเธฃเนเธญเธ เธเธงเธฃเน€เธเธดเนเธก margin of safety, เนเธกเนเนเธฅเนเธฃเธฒเธเธฒ, เนเธฅเธฐเน€เธ•เธฃเธตเธขเธก cash buffer เธชเธณเธซเธฃเธฑเธเธเธฑเธเธซเธงเธฐ forced selling.":
            "คะแนนรวมยังอยู่โซนร้อน ควรเพิ่ม margin of safety, ไม่ไล่ราคา, และเตรียม cash buffer สำหรับจังหวะ forced selling.",
    }
    changed = False
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
            changed = True
    if not changed:
        print("macro Thai text already clean")
        return
    MACRO.write_text(text, encoding="utf-8")
    print("fixed macro Thai text")


if __name__ == "__main__":
    main()
