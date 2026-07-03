from __future__ import annotations

import csv
import io
import json
import math
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
RAW = ROOT / "work" / "raw" / "fred_v04"
START_1990 = date(1990, 1, 1)

FRED_SERIES = [
    "NCBEILQ027S",
    "GDP",
    "BAA",
    "DGS10",
    "DGS2",
    "VIXCLS",
    "BAMLH0A0HYM2",
    "WALCL",
    "FEDFUNDS",
    "T10YIE",
]


def parse_float(value):
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", ".", "-", "n/a", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_fred_csv(series_id: str) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / f"{series_id}.csv"
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        proc = subprocess.run(
            ["curl.exe", "-L", "--silent", "--show-error", "--max-time", "45", url],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        text = proc.stdout
        if "observation_date" not in text[:200]:
            raise RuntimeError(f"unexpected FRED CSV header for {series_id}")
        cache.write_text(text, encoding="utf-8")
        return text
    except Exception:
        if cache.exists() and cache.stat().st_size > 100:
            return cache.read_text(encoding="utf-8", errors="replace")
        raise


def fred_points(series_id: str) -> list[dict]:
    raw = fetch_fred_csv(series_id)
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            obs_date = datetime.strptime(row["observation_date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue
        value = parse_float(row.get(series_id))
        if obs_date >= START_1990 and value is not None:
            rows.append({"date": obs_date.isoformat(), "value": value})
    return rows


def latest_on_or_before(points: list[dict], iso_date: str):
    vals = [p for p in points if p["date"] <= iso_date]
    return vals[-1]["value"] if vals else None


def diff_series(a: list[dict], b: list[dict]) -> list[dict]:
    out = []
    for point in a:
        other = latest_on_or_before(b, point["date"])
        if other is not None:
            out.append({"date": point["date"], "value": point["value"] - other})
    return out


def ratio_series(a: list[dict], b: list[dict], b_mult=1.0) -> list[dict]:
    out = []
    for point in a:
        other = latest_on_or_before(b, point["date"])
        if other:
            out.append({"date": point["date"], "value": point["value"] / (other * b_mult)})
    return out


def yoy(points: list[dict], periods=52) -> list[dict]:
    out = []
    for idx, point in enumerate(points):
        if idx >= periods and points[idx - periods]["value"]:
            out.append({"date": point["date"], "value": (point["value"] / points[idx - periods]["value"] - 1) * 100})
    return out


def percentile(values, latest, invert=False):
    vals = [value for value in values if value is not None and math.isfinite(value)]
    if latest is None or not vals:
        return None
    pct = sum(1 for value in vals if value <= latest) / len(vals) * 100
    return 100 - pct if invert else pct


def band(score):
    if score is None:
        return "n/a", "#8994aa"
    if score < 25:
        return "Cool", "#4aaa63"
    if score < 50:
        return "Normal", "#7abc86"
    if score < 65:
        return "Warm", "#d9b644"
    if score < 80:
        return "Frothy", "#e9912f"
    return "Extreme", "#d95445"


def build_indicators(series: dict[str, list[dict]]) -> list[dict]:
    buffett = ratio_series(series["NCBEILQ027S"], series["GDP"], 1000.0)
    baa_spread = diff_series(series["BAA"], series["DGS10"])
    curve = diff_series(series["DGS10"], series["DGS2"])
    walcl_yoy = yoy(series["WALCL"])
    real_policy = diff_series(series["FEDFUNDS"], series["T10YIE"])
    specs = [
        ("Buffett Indicator (US equities / GDP)", "US equity market value versus GDP; high percentile means high valuation risk.", buffett, False, "x"),
        ("Credit Risk Premium (Baa - 10Y)", "Low credit spread can indicate complacency and easy credit.", baa_spread, True, "%"),
        ("High Yield OAS", "Low high-yield spread can indicate elevated risk appetite.", series["BAMLH0A0HYM2"], True, "%"),
        ("VIX complacency", "Low VIX can indicate market complacency.", series["VIXCLS"], True, ""),
        ("Yield Curve 10Y-2Y", "Flat or inverted curve raises recession-cycle stress.", curve, True, "pp"),
        ("Fed Assets YoY", "Faster balance-sheet growth can be a liquidity tailwind.", walcl_yoy, False, "%"),
        ("Real Policy Proxy", "Fed Funds minus 10Y breakeven inflation.", real_policy, False, "pp"),
    ]
    indicators = []
    for name, desc, points, invert, unit in specs:
        latest = points[-1]["value"] if points else None
        prior = None
        if points:
            cutoff = (datetime.strptime(points[-1]["date"], "%Y-%m-%d").date() - timedelta(days=366)).isoformat()
            older = [point for point in points if point["date"] <= cutoff]
            prior = older[-1]["value"] if older else None
        pct = percentile([point["value"] for point in points], latest, invert)
        signal, color = band(pct)
        indicators.append(
            {
                "name": name,
                "desc": desc,
                "latest": latest,
                "date": points[-1]["date"] if points else None,
                "delta": latest - prior if latest is not None and prior is not None else None,
                "pct": pct,
                "signal": signal,
                "color": color,
                "unit": unit,
                "spark": points[-260:],
            }
        )
    return indicators


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault("sources", [])
    if not any(item.get("name") == source["name"] for item in sources):
        sources.append(source)


def add_failure_once(payload: dict, source: str, status: str) -> None:
    failures = payload.setdefault("source_failures", [])
    if not any(item.get("source") == source and item.get("status") == status for item in failures):
        failures.append({"source": source, "status": status})


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    series = {series_id: fred_points(series_id) for series_id in FRED_SERIES}
    indicators = build_indicators(series)
    macro = payload.setdefault("macro_v04", {})
    macro["indicators"] = indicators
    add_source_once(
        payload,
        {
            "name": "FRED macro froth indicators",
            "url": "https://fred.stlouisfed.org/",
            "publication_date": datetime.now().strftime("Data fetched %Y-%m-%d"),
            "used_for": "Buffett indicator proxy, credit premium, HY OAS, VIX, yield curve, Fed assets, real policy proxy.",
        },
    )
    add_failure_once(
        payload,
        "FRED Python urllib adapter",
        "urllib timed out in this Windows/Codex runtime; Froth Components are fetched with curl.exe CSV fallback.",
    )
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({item["name"]: {"latest": item["latest"], "date": item["date"], "pct": item["pct"]} for item in indicators}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
