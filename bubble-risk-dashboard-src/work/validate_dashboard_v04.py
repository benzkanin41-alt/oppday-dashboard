from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
JS_OUT = ROOT / "work" / "dashboard_v04_inline.js"


def first_last(series: list[dict]) -> tuple[str | None, str | None]:
    if not series:
        return None, None
    return series[0].get("date"), series[-1].get("date")


text = HTML.read_text(encoding="utf-8")
data = json.loads(DATA.read_text(encoding="utf-8"))

embedded_match = re.search(
    r'<script id="v03-data" type="application/json">(.*?)</script>',
    text,
    re.S,
)
if not embedded_match:
    raise SystemExit("missing v03-data script")
embedded = json.loads(embedded_match.group(1))

inline_scripts = re.findall(r"<script>(.*?)</script>", text, re.S)
if not inline_scripts:
    raise SystemExit("missing inline script")
JS_OUT.write_text(inline_scripts[-1], encoding="utf-8")

print("HTML size", HTML.stat().st_size)
print("data.json size", DATA.stat().st_size)
print("embedded keys", len(embedded.get("priceSeries", {})), len(embedded.get("yieldCurves", {})), len(embedded.get("valuations", {})))
print("data keys", len(data.get("priceSeries", {})), len(data.get("yieldCurves", {})), len(data.get("valuations", {})))
print("thai markers", text.find("แสดง"), text.find("คำนวณจาก"), text.find("ปรับน้ำหนัก"))
print("pointer fix markers", "createSVGPoint" in text, "getScreenCTM" in text)

for symbol in ["SPY", "QQQ", "IWM", "FEZ", "EWJ", "EWY", "SET", "mai", "ACWI"]:
    series = embedded.get("priceSeries", {}).get(symbol, [])
    start, end = first_last(series)
    print("price", symbol, len(series), start, end)

for country in ["United States", "Thailand"]:
    series = embedded.get("yieldCurves", {}).get(country, [])
    start, end = first_last(series)
    print("yield", country, len(series), start, end)

for symbol in ["SPY", "QQQ", "IWM", "FEZ", "VGK", "EWJ", "MCHI", "FXI", "INDA", "EWY", "ACWI", "SET", "mai"]:
    valuation = embedded.get("valuations", {}).get(symbol, {})
    print(
        "valuation",
        symbol,
        valuation.get("trailing_pe"),
        valuation.get("forward_pe"),
        valuation.get("trailing_source"),
        valuation.get("forward_source"),
    )
