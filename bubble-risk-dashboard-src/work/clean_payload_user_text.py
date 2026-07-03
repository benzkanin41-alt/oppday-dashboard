from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"


payload = json.loads(DATA.read_text(encoding="utf-8"))

for symbol, item in (payload.get("price_histories_v04") or {}).items():
    chart_symbol = item.get("chart_symbol") or symbol
    item["note"] = f"Proxy {chart_symbol}; if the first date is after 1990, the source starts there."

for row in payload.get("earnings_yield_gap", []):
    row["status"] = (
        "Computed from Trailing P/E minus local 10Y yield"
        if row.get("gap_pp") is not None
        else "Valuation is available, but local 10Y yield or forward source is still missing"
    )

if isinstance(payload.get("macro_v04"), dict):
    for indicator in payload["macro_v04"].get("indicators", []):
        name = indicator.get("name") or ""
        indicator["desc"] = {
            "Buffett Indicator (US equities / GDP)": "US equity market value versus GDP; high percentile means high valuation risk.",
            "Credit Risk Premium (Baa - 10Y)": "Low credit spread can indicate complacency and easy credit.",
            "High Yield OAS": "Low high-yield spread can indicate elevated risk appetite.",
            "VIX complacency": "Low VIX can indicate market complacency.",
            "Yield Curve 10Y-2Y": "Flat or inverted curve raises recession-cycle stress.",
            "Fed Assets YoY": "Faster balance-sheet growth can be a liquidity tailwind.",
            "Real Policy Proxy": "Fed Funds minus 10Y breakeven inflation.",
        }.get(name, indicator.get("desc") or "")

DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("payload text cleaned")
