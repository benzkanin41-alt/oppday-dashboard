from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
HTML = ROOT / "outputs" / "dashboard" / "index.html"


def clean_price_series(series: dict) -> None:
    for symbol, item in series.items():
        if not isinstance(item, dict):
            continue
        chart_symbol = item.get("chart_symbol") or item.get("symbol") or symbol
        item["note"] = f"Proxy {chart_symbol}; if the first date is after 1990, the source starts there."


def clean_eyg_rows(rows: list) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        row["status"] = (
            "Computed from Trailing P/E minus local 10Y yield"
            if row.get("gap_pp") is not None
            else "Valuation is available, but local 10Y yield or forward source is still missing"
        )


def clean_macro(payload: dict) -> None:
    if not isinstance(payload.get("macro_v04"), dict):
        return
    descriptions = {
        "Buffett Indicator (US equities / GDP)": "US equity market value versus GDP; high percentile means high valuation risk.",
        "Credit Risk Premium (Baa - 10Y)": "Low credit spread can indicate complacency and easy credit.",
        "High Yield OAS": "Low high-yield spread can indicate elevated risk appetite.",
        "VIX complacency": "Low VIX can indicate market complacency.",
        "Yield Curve 10Y-2Y": "Flat or inverted curve raises recession-cycle stress.",
        "Fed Assets YoY": "Faster balance-sheet growth can be a liquidity tailwind.",
        "Real Policy Proxy": "Fed Funds minus 10Y breakeven inflation.",
    }
    for indicator in payload["macro_v04"].get("indicators", []):
        name = indicator.get("name") or ""
        indicator["desc"] = descriptions.get(name, indicator.get("desc") or "")


def clean_payload(payload: dict) -> None:
    clean_price_series(payload.get("price_histories_v03") or {})
    clean_price_series(payload.get("price_histories_v04") or {})
    clean_eyg_rows(payload.get("earnings_yield_gap") or [])
    clean_macro(payload)


def clean_embedded_chart_data() -> bool:
    if not HTML.exists():
        return False
    html = HTML.read_text(encoding="utf-8")
    pattern = re.compile(r'(<script id="v03-data" type="application/json">)(.*?)(</script>)', re.S)

    def replace(match: re.Match[str]) -> str:
        chart_data = json.loads(match.group(2))
        clean_price_series(chart_data.get("priceSeries") or {})
        clean_eyg_rows(chart_data.get("eygRows") or [])
        clean_json = json.dumps(chart_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        return f"{match.group(1)}{clean_json}{match.group(3)}"

    new_html, count = pattern.subn(replace, html, count=1)
    if count:
        HTML.write_text(new_html, encoding="utf-8")
    return bool(count)


payload = json.loads(DATA.read_text(encoding="utf-8"))
clean_payload(payload)
embedded_cleaned = clean_embedded_chart_data()

DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"payload_text_cleaned": True, "embedded_chart_data_cleaned": embedded_cleaned}, ensure_ascii=False))
