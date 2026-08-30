from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
HTML = OUT / "index.html"
DATA = OUT / "data.json"

PRESERVED_PRICE_ROWS = (
    {
        "symbol": "ARKK",
        "name": "Speculative growth proxy",
        "region": "US",
        "bucket": "Nasdaq Theme Proxy",
    },
)


def load_v04():
    spec = importlib.util.spec_from_file_location("bubble_v04", ROOT / "work" / "enhance_dashboard_v04.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def strip_marker(text: str, marker: str) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    while start in text and end in text:
        a = text.index(start)
        b = text.index(end, a) + len(end)
        text = text[:a] + text[b:]
    return text


def recover_utf8_mojibake(segment: str) -> str:
    if "เน" not in segment and "โ€" not in segment and "เธ" not in segment:
        return segment
    try:
        return segment.encode("cp874").decode("utf-8")
    except UnicodeError:
        return segment


def recover_marker(text: str, marker: str) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    if start not in text or end not in text:
        return text
    a = text.index(start)
    b = text.index(end, a) + len(end)
    return text[:a] + recover_utf8_mojibake(text[a:b]) + text[b:]


def main() -> None:
    v04 = load_v04()
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    rows, seen = [], set()
    for bucket in (payload.get("top_watchlist_v03", []), payload.get("earnings_yield_gap", [])):
        for row in bucket:
            symbol = row.get("symbol")
            if symbol and symbol not in seen:
                seen.add(symbol)
                rows.append(row)
    # Keep benchmark histories available even when a dynamic watchlist rank changes.
    for row in PRESERVED_PRICE_ROWS:
        if row["symbol"] not in seen:
            seen.add(row["symbol"])
            rows.append(row)
    existing = payload.get("price_histories_v04") or payload.get("price_histories_v03") or {}
    price_series = v04.build_price_series(rows, existing)
    payload["price_histories_v04"] = price_series

    chart_data = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M local"),
        "ranges": {k: v for k, v in v04.RANGES},
        "yieldCurves": payload.get("yield_curves", []),
        "priceSeries": price_series,
        "eygRows": payload.get("earnings_yield_gap", []),
    }
    interactive = recover_utf8_mojibake(v04.render_interactive(chart_data, payload.get("earnings_yield_gap", [])))

    html = HTML.read_text(encoding="utf-8")
    html = strip_marker(html, "v03-interactive-section")
    anchor = '<section class="section">\n      <div class="section-title">\n        <h2>Source Gaps'
    if anchor in html:
        html = html.replace(anchor, interactive + "\n" + anchor, 1)
    else:
        html = html.replace("</main>", interactive + "\n</main>", 1)
    html = recover_marker(html, "v04-macro-section")
    html = recover_marker(html, "v03-interactive-section")

    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    HTML.write_text(html, encoding="utf-8")
    print(json.dumps({k: len(v.get("points") or []) for k, v in price_series.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
