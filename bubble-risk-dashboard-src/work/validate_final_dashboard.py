from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
JS_OUT = ROOT / "work" / "final_dashboard_inline.js"


html = HTML.read_text(encoding="utf-8")
data_text = DATA.read_text(encoding="utf-8")
payload = json.loads(data_text)
embedded = json.loads(re.search(r'<script id="v03-data" type="application/json">(.*?)</script>', html, re.S).group(1))
inline_scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
JS_OUT.write_text(inline_scripts[-1], encoding="utf-8")


def count_c1_controls(text: str) -> int:
    return sum(1 for ch in text if 0x80 <= ord(ch) <= 0x9F)


mojibake_counts = {
    "html_c1_controls": count_c1_controls(html),
    "data_c1_controls": count_c1_controls(data_text),
    "html_thai_euro": html.count("โ€") + html.count("เน€"),
    "data_thai_euro": data_text.count("โ€") + data_text.count("เน€"),
}

print("html_bytes", HTML.stat().st_size)
print("data_bytes", DATA.stat().st_size)
print("bad_token_counts", mojibake_counts)
if any(mojibake_counts.values()):
    raise SystemExit("mojibake tokens found in dashboard output")
print("pointer_fix", "createSVGPoint" in html and "getScreenCTM" in html)
print("price_symbols", len(embedded["priceSeries"]), ",".join(embedded["priceSeries"].keys()))
for symbol in ["SPY", "QQQ", "IWM", "FEZ", "VGK", "EWJ", "MCHI", "FXI", "INDA", "EWY", "SET", "mai"]:
    points = embedded["priceSeries"][symbol]["points"]
    first = points[0]["date"] if points else None
    last = points[-1]["date"] if points else None
    print("price", symbol, len(points), first, last)
for curve in embedded["yieldCurves"]:
    hist = curve.get("history") or []
    first = hist[0]["date"] if hist else None
    last = hist[-1]["date"] if hist else None
    print("yield", curve.get("country"), len(hist), first, last)
for row in embedded["eygRows"]:
    if row.get("symbol") in {"SPY", "QQQ", "FEZ", "SET", "mai"}:
        print("eyg", row.get("symbol"), row.get("trailing_pe"), row.get("forward_pe"), row.get("earnings_yield"), row.get("gap_pp"), row.get("status"))
print("source_failures", payload.get("source_failures", []))
