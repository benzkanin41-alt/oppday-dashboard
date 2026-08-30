from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
REQUIRED_SYMBOLS = [
    "SPY", "QQQ", "IWM", "FEZ", "VGK", "EWJ", "MCHI",
    "FXI", "INDA", "EWY", "ACWI", "SET", "mai",
]
PRESERVED_PRICE_SYMBOLS = ["ARKK"]


def point_list(value: object) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("history", "points", "data"):
            points = value.get(key)
            if isinstance(points, list):
                return points
    return []


def first_last(value: object) -> tuple[int, str | None, str | None]:
    points = point_list(value)
    if not points:
        return 0, None, None
    return len(points), points[0].get("date"), points[-1].get("date")


def valuation_rows(embedded: dict) -> dict[str, dict]:
    values = embedded.get("valuations", {})
    if isinstance(values, dict) and values:
        return values
    return {
        row["symbol"]: {
            "trailing_pe": row.get("trailing_pe"),
            "forward_pe": row.get("forward_pe"),
            "source": row.get("source"),
            "forward_source": row.get("forward_source"),
        }
        for row in embedded.get("eygRows", [])
        if row.get("symbol")
    }


def country_curve(curves: object, country: str) -> object:
    if isinstance(curves, dict):
        return curves.get(country, {})
    if isinstance(curves, list):
        return next((item for item in curves if item.get("country") == country), {})
    return {}


def main() -> None:
    text = HTML.read_text(encoding="utf-8")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    match = re.search(r'<script id="v03-data" type="application/json">(.*?)</script>', text, re.S)
    if not match:
        raise SystemExit("missing v03-data script")
    embedded = json.loads(match.group(1))

    data_price_series = data.get("price_histories_v04", {})
    embedded_price_series = embedded.get("priceSeries", {})
    if len(data_price_series) < 20:
        raise SystemExit("data.json is missing v04 price series")
    if len(embedded_price_series) < 20:
        raise SystemExit("embedded dashboard is missing price series")

    valuations = valuation_rows(embedded)
    if len(valuations) < len(REQUIRED_SYMBOLS):
        raise SystemExit("embedded dashboard is missing valuation rows")

    print("html_size", HTML.stat().st_size)
    print("data_size", DATA.stat().st_size)
    print("embedded_price_series", len(embedded_price_series))
    print("data_price_series", len(data_price_series))
    for symbol in REQUIRED_SYMBOLS:
        count, start, end = first_last(embedded_price_series.get(symbol))
        if count < 2:
            raise SystemExit(f"missing price history for {symbol}")
        valuation = valuations.get(symbol, {})
        trailing_pe = valuation.get("trailing_pe")
        if not isinstance(trailing_pe, (int, float)) or trailing_pe <= 0:
            raise SystemExit(f"missing trailing P/E for {symbol}")
        if "forward_pe" not in valuation:
            raise SystemExit(f"missing forward P/E field for {symbol}")
        print("price", symbol, count, start, end)
        print("valuation", symbol, trailing_pe, valuation.get("forward_pe"))

    for symbol in PRESERVED_PRICE_SYMBOLS:
        count, start, end = first_last(embedded_price_series.get(symbol))
        data_count, _, _ = first_last(data_price_series.get(symbol))
        if count < 2 or data_count < 2:
            raise SystemExit(f"missing preserved price history for {symbol}")
        print("preserved_price", symbol, count, start, end)

    curves = embedded.get("yieldCurves", {})
    for country in ("United States", "Thailand"):
        count, start, end = first_last(country_curve(curves, country))
        if count < 2:
            raise SystemExit(f"missing yield history for {country}")
        print("yield", country, count, start, end)

    if not ("createSVGPoint" in text and "getScreenCTM" in text):
        raise SystemExit("missing corrected SVG pointer mapping")
    print("eyg_rows", len(valuations))
    print("pointer_fix", True)


if __name__ == "__main__":
    main()
