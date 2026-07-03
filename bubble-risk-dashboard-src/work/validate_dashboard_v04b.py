from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
JS_OUT = ROOT / "work" / "dashboard_v04_inline.js"


def point_list(value) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("history", "points", "data"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def first_last(value) -> tuple[int, str | None, str | None]:
    series = point_list(value)
    if not series:
        return 0, None, None
    return len(series), series[0].get("date"), series[-1].get("date")


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
print("embedded top keys", sorted(embedded.keys()))
print("data top keys", sorted(data.keys()) if isinstance(data, dict) else type(data).__name__)
print("thai markers", text.find("แสดง"), text.find("คำนวณจาก"), text.find("ปรับน้ำหนัก"))
print("pointer fix markers", "createSVGPoint" in text, "getScreenCTM" in text)

for symbol in ["SPY", "QQQ", "IWM", "FEZ", "EWJ", "EWY", "SET", "mai", "ACWI"]:
    count, start, end = first_last(embedded.get("priceSeries", {}).get(symbol, []))
    print("price", symbol, count, start, end)

curves = embedded.get("yieldCurves", {})
for country in ["United States", "Thailand"]:
    if isinstance(curves, list):
        curve = next((item for item in curves if item.get("country") == country), {})
    else:
        curve = curves.get(country, {})
    count, start, end = first_last(curve)
    print("yield", country, count, start, end)

valuations = embedded.get("valuations", {})
if not valuations and isinstance(embedded.get("earningsYieldGap"), list):
    valuations = {
        item.get("symbol"): {
            "trailing_pe": item.get("trailing_pe"),
            "forward_pe": item.get("forward_pe"),
            "trailing_source": item.get("trailing_source"),
            "forward_source": item.get("forward_source"),
        }
        for item in embedded["earningsYieldGap"]
    }

for symbol in ["SPY", "QQQ", "IWM", "FEZ", "VGK", "EWJ", "MCHI", "FXI", "INDA", "EWY", "ACWI", "SET", "mai"]:
    valuation = valuations.get(symbol, {})
    print(
        "valuation",
        symbol,
        valuation.get("trailing_pe"),
        valuation.get("forward_pe"),
        valuation.get("trailing_source"),
        valuation.get("forward_source"),
    )
