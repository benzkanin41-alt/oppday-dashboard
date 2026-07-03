from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, path: Path) -> str:
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old!r}")
    return text.replace(old, new, 1)


def main() -> None:
    runner = ROOT / "work" / "update_local_dashboard_full.py"
    text = runner.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    "work/update_froth_components_fred.py",\n    "work/clean_payload_user_text.py",\n    "work/rebuild_clean_macro.py",',
        '    "work/update_froth_components_fred.py",\n    "work/clean_payload_user_text.py",\n    "work/update_current_market_indicators.py",\n    "work/rebuild_clean_macro.py",',
        runner,
    )
    text = replace_once(
        text,
        '    "work/update_froth_components_fred.py": 180,\n',
        '    "work/update_froth_components_fred.py": 180,\n    "work/update_current_market_indicators.py": 180,\n',
        runner,
    )
    text = replace_once(
        text,
        '    "work/validate_froth_components_populated.py",\n    "work/validate_thailand_heat_mai_treasury.py",',
        '    "work/validate_froth_components_populated.py",\n    "work/validate_current_market_indicators.py",\n    "work/validate_thailand_heat_mai_treasury.py",',
        runner,
    )
    runner.write_text(text, encoding="utf-8")

    macro = ROOT / "work" / "rebuild_clean_macro.py"
    text = macro.read_text(encoding="utf-8")
    replacements = {
        '"VIX complacency": "FRED VIXCLS / Cboe VIX",': '"VIX complacency": "Cboe VIX historical price data",',
        '"Yield Curve 10Y-2Y": "FRED DGS10 minus DGS2",': '"Yield Curve 10Y-2Y": "U.S. Treasury daily XML latest + FRED history",',
        '"Real Policy Proxy": "FRED FEDFUNDS minus T10YIE",': '"Real Policy Proxy": "NY Fed EFFR + FRED T10YIE",',
        '"Fed Assets YoY": "FRED WALCL YoY",': '"Fed Assets YoY": "FRED WALCL YoY (weekly Wednesday series)",',
    }
    for old, new in replacements.items():
        text = replace_once(text, old, new, macro)
    macro.write_text(text, encoding="utf-8")
    print("patched runner and macro source labels")


if __name__ == "__main__":
    main()
