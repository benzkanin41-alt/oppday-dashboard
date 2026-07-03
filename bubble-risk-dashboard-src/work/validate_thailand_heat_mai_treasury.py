from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    html = HTML.read_text(encoding="utf-8")

    index_symbols = {item.get("symbol") for item in payload.get("indices", [])}
    assert {"SET", "mai"} <= index_symbols, f"SET/mai missing from indices: {index_symbols}"

    heat_match = re.search(r'<div id="indices" class="tile-grid">(.*?)<div id="sectors"', html, re.S)
    assert heat_match, "Market heat index grid missing"
    heat_html = heat_match.group(1)
    assert "SET Index" in heat_html, "SET Index missing from Market heat index grid"
    assert "mai Index" in heat_html, "mai Index missing from Market heat index grid"

    price = payload.get("price_histories_v04", {})
    assert "mai" in price, "mai missing from price_histories_v04"
    assert len(price["mai"].get("points") or []) >= 1, "mai has no source-backed price point"
    assert "value='mai'" in html or 'value="mai"' in html, "mai missing from Top Watchlist selector"
    assert "source-backed snapshot" in html, "single-point price chart renderer not patched"

    us = next((c for c in payload.get("yield_curves", []) if c.get("country") == "United States"), None)
    assert us, "United States yield curve missing"
    assert "Treasury" in (us.get("label") or "") or "Treasury" in (us.get("source") or ""), us.get("source")
    assert us.get("as_of") and us.get("as_of") >= "2026-07-02", f"US Treasury curve not current enough: {us.get('as_of')}"
    latest = us.get("latest") or {}
    for tenor in ("2Y", "5Y", "10Y", "30Y"):
        assert latest.get(tenor) is not None, f"US latest {tenor} missing"

    print(
        json.dumps(
            {
                "status": "ok",
                "indices": sorted(index_symbols & {"SET", "mai"}),
                "mai_points": len(price["mai"].get("points") or []),
                "us_yield_as_of": us.get("as_of"),
                "us_latest": latest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
