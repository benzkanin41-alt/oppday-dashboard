from __future__ import annotations

import csv
import io
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
RAW = ROOT / "work" / "raw" / "current_market"
LATEST = RAW / "latest_sources.json"

CBOE_VIX_CSV = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
NYFED_EFFR_URL = "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate={start}&endDate={end}&type=rate"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
START_1990 = date(1990, 1, 1)
FETCH_STATUS = {}


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


def run_curl(url: str, timeout: int = 70) -> str:
    proc = subprocess.run(
        ["curl.exe", "--fail", "-L", "--silent", "--show-error", "--max-time", str(timeout), url],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout + 15,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"curl failed for {url}")
    return proc.stdout


def validate_source_text(name: str, text: str) -> None:
    valid = False
    if name.endswith(".csv"):
        column = Path(name).stem
        for row in csv.DictReader(io.StringIO(text)):
            raw_date = (row.get("DATE") or row.get("Date")) if name == "VIX_History.csv" else row.get("observation_date")
            value = parse_float(row.get("CLOSE") or row.get("Close") or row.get("VIX Close")) if name == "VIX_History.csv" else parse_float(row.get(column))
            try:
                datetime.strptime(raw_date, "%m/%d/%Y") if name == "VIX_History.csv" else date.fromisoformat(raw_date[:10])
                valid = value is not None and math.isfinite(value)
            except (TypeError, ValueError):
                continue
            if valid:
                break
    elif name.endswith(".xml"):
        root = ET.fromstring(text)
        ns = {"d": "http://schemas.microsoft.com/ado/2007/08/dataservices", "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"}
        for row in root.findall(".//m:properties", ns):
            raw_date = row.findtext("d:NEW_DATE", namespaces=ns)
            values = [parse_float(row.findtext(f"d:BC_{term}YEAR", namespaces=ns)) for term in (2, 10)]
            if raw_date and all(value is not None and math.isfinite(value) for value in values):
                date.fromisoformat(raw_date[:10])
                valid = True
                break
    elif name == "nyfed_effr_latest.json":
        data = json.loads(text)
        for row in data.get("refRates", []):
            value = parse_float(row.get("percentRate"))
            if row.get("effectiveDate") and value is not None and math.isfinite(value):
                date.fromisoformat(row["effectiveDate"])
                valid = True
                break
    if not valid:
        raise ValueError(f"No valid observations in {name}")


def cached_text(name: str, url: str, timeout: int = 70) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    previous = json.loads(LATEST.read_text(encoding="utf-8")) if LATEST.exists() else {}
    old_status = previous.get("fetch_status", {}).get(name, {})
    status = {"url": url, "attempted_at": datetime.now(timezone.utc).isoformat(), "last_successful_fetch": old_status.get("last_successful_fetch")}
    try:
        text = run_curl(url, timeout=timeout)
        validate_source_text(name, text)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
        status.update(mode="live", last_successful_fetch=status["attempted_at"])
        FETCH_STATUS[name] = status
        return text
    except Exception as exc:
        status.update(mode="unavailable", error=str(exc))
        FETCH_STATUS[name] = status
        if path.exists():
            cached = path.read_text(encoding="utf-8", errors="replace")
            validate_source_text(name, cached)
            status["mode"] = "cache"
            return cached
        raise


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


def prior_one_year(points: list[dict]) -> float | None:
    if not points:
        return None
    latest_day = datetime.strptime(points[-1]["date"], "%Y-%m-%d").date()
    cutoff = (latest_day - timedelta(days=366)).isoformat()
    older = [point for point in points if point["date"] <= cutoff]
    return older[-1]["value"] if older else None


def make_indicator(name: str, desc: str, points: list[dict], invert: bool, unit: str) -> dict:
    points = [p for p in points if p.get("value") is not None]
    latest = points[-1]["value"] if points else None
    prior = prior_one_year(points)
    pct = percentile([point["value"] for point in points], latest, invert)
    signal, color = band(pct)
    return {
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


def parse_cboe_vix() -> list[dict]:
    text = cached_text("VIX_History.csv", CBOE_VIX_CSV, timeout=70)
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        raw_date = (row.get("DATE") or row.get("Date") or "").strip()
        value = parse_float(row.get("CLOSE") or row.get("Close") or row.get("VIX Close"))
        if not raw_date or value is None:
            continue
        try:
            obs_date = datetime.strptime(raw_date, "%m/%d/%Y").date()
        except ValueError:
            continue
        if obs_date >= START_1990:
            rows.append({"date": obs_date.isoformat(), "value": value})
    rows.sort(key=lambda p: p["date"])
    return rows


def parse_treasury_year(year: int) -> tuple[list[dict], str | None]:
    xml = cached_text(f"treasury_yield_curve_{year}.xml", TREASURY_XML_URL.format(year=year), timeout=80)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    root = ET.fromstring(xml)
    feed_updated = root.findtext("atom:updated", namespaces=ns)
    rows = []
    for props in root.findall(".//m:properties", ns):
        raw_date = props.findtext("d:NEW_DATE", namespaces=ns)
        if not raw_date:
            continue
        two = parse_float(props.findtext("d:BC_2YEAR", namespaces=ns))
        ten = parse_float(props.findtext("d:BC_10YEAR", namespaces=ns))
        if two is not None and ten is not None:
            rows.append({"date": raw_date[:10], "value": ten - two, "2Y": two, "10Y": ten})
    rows.sort(key=lambda p: p["date"])
    return rows, feed_updated


def fred_points(series_id: str) -> list[dict]:
    text = cached_text(f"{series_id}.csv", FRED_CSV_URL.format(series_id=series_id), timeout=70)
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            obs_date = datetime.strptime(row["observation_date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue
        value = parse_float(row.get(series_id))
        if obs_date >= START_1990 and value is not None:
            rows.append({"date": obs_date.isoformat(), "value": value})
    return rows


def latest_on_or_before(points: list[dict], iso_date: str) -> float | None:
    vals = [p for p in points if p["date"] <= iso_date]
    return vals[-1]["value"] if vals else None


def diff_series(a: list[dict], b: list[dict]) -> list[dict]:
    out = []
    for point in a:
        other = latest_on_or_before(b, point["date"])
        if other is not None:
            out.append({"date": point["date"], "value": point["value"] - other})
    return out


def merge_points(base: list[dict], overlay: list[dict]) -> list[dict]:
    by_date = {p["date"]: {"date": p["date"], "value": p["value"]} for p in base}
    for point in overlay:
        by_date[point["date"]] = {"date": point["date"], "value": point["value"]}
    return [by_date[key] for key in sorted(by_date)]


def parse_nyfed_effr() -> list[dict]:
    end = datetime.now().date()
    start = end - timedelta(days=45)
    url = NYFED_EFFR_URL.format(start=start.isoformat(), end=end.isoformat())
    text = cached_text("nyfed_effr_latest.json", url, timeout=50)
    data = json.loads(text)
    rows = []
    for item in data.get("refRates", []):
        raw_date = item.get("effectiveDate")
        value = parse_float(item.get("percentRate"))
        if raw_date and value is not None:
            rows.append({"date": raw_date, "value": value})
    rows.sort(key=lambda p: p["date"])
    return rows


def upsert_indicator(payload: dict, indicator: dict) -> None:
    macro = payload.setdefault("macro_v04", {})
    indicators = macro.setdefault("indicators", [])
    for idx, item in enumerate(indicators):
        if item.get("name") == indicator["name"]:
            indicators[idx] = indicator
            return
    indicators.append(indicator)


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault("sources", [])
    key = (source.get("name"), source.get("url"))
    if not any((item.get("name"), item.get("url")) == key for item in sources):
        sources.append(source)


def update_scores(payload: dict) -> None:
    macro = payload.setdefault("macro_v04", {})
    indicators = {item.get("name"): item for item in macro.get("indicators", [])}
    scores = macro.setdefault("scores", {})
    froth_inputs = [
        indicators.get("Buffett Indicator (US equities / GDP)", {}).get("pct"),
        indicators.get("Credit Risk Premium (Baa - 10Y)", {}).get("pct"),
        indicators.get("High Yield OAS", {}).get("pct"),
        indicators.get("VIX complacency", {}).get("pct"),
        indicators.get("Fed Assets YoY", {}).get("pct"),
    ]
    recession_inputs = [
        indicators.get("Yield Curve 10Y-2Y", {}).get("pct"),
        indicators.get("Credit Risk Premium (Baa - 10Y)", {}).get("pct"),
        indicators.get("High Yield OAS", {}).get("pct"),
        indicators.get("Real Policy Proxy", {}).get("pct"),
    ]
    debt_inputs = [
        indicators.get("Credit Risk Premium (Baa - 10Y)", {}).get("pct"),
        indicators.get("Fed Assets YoY", {}).get("pct"),
        indicators.get("Real Policy Proxy", {}).get("pct"),
    ]
    for key, values in (("froth", froth_inputs), ("recession", recession_inputs), ("debt", debt_inputs)):
        vals = [v for v in values if v is not None]
        if vals:
            scores[key] = round(sum(vals) / len(vals))


def main() -> None:
    FETCH_STATUS.clear()
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    vix = parse_cboe_vix()
    fred_dgs10 = fred_points("DGS10")
    fred_dgs2 = fred_points("DGS2")
    fred_curve = diff_series(fred_dgs10, fred_dgs2)
    treasury_curve, treasury_updated = parse_treasury_year(datetime.now().year)
    curve = merge_points(fred_curve, treasury_curve)
    effr = merge_points(fred_points("EFFR"), parse_nyfed_effr())
    t10yie = fred_points("T10YIE")
    real_policy = diff_series(effr, t10yie)

    upsert_indicator(
        payload,
        make_indicator(
            "VIX complacency",
            "Low VIX can indicate market complacency. Uses Cboe VIX daily history when fresher than FRED.",
            vix,
            True,
            "",
        ),
    )
    upsert_indicator(
        payload,
        make_indicator(
            "Yield Curve 10Y-2Y",
            "Flat or inverted curve raises recession-cycle stress. Latest point uses U.S. Treasury daily XML.",
            curve,
            True,
            "pp",
        ),
    )
    upsert_indicator(
        payload,
        make_indicator(
            "Real Policy Proxy",
            "Effective Fed Funds Rate minus 10Y breakeven inflation.",
            real_policy,
            False,
            "pp",
        ),
    )
    update_scores(payload)
    add_source_once(
        payload,
        {
            "name": "Cboe VIX historical price data",
            "url": "https://www.cboe.com/tradable-products/vix/vix-historical-data",
            "publication_date": f"updated daily; latest observation {vix[-1]['date'] if vix else 'n/a'}",
            "used_for": "VIX complacency row and 5-year sparkline in Froth Components.",
        },
    )
    add_source_once(
        payload,
        {
            "name": "U.S. Treasury Daily Treasury Rates XML",
            "url": TREASURY_XML_URL.format(year=datetime.now().year),
            "publication_date": f"feed updated {treasury_updated or 'n/a'}; latest observation {treasury_curve[-1]['date'] if treasury_curve else 'n/a'}",
            "used_for": "Latest U.S. 10Y-2Y yield-curve row and yield-curve dashboard point.",
        },
    )
    add_source_once(
        payload,
        {
            "name": "New York Fed EFFR API",
            "url": NYFED_EFFR_URL.format(start=(datetime.now().date() - timedelta(days=45)).isoformat(), end=datetime.now().date().isoformat()),
            "publication_date": f"latest EFFR observation {effr[-1]['date'] if effr else 'n/a'}",
            "used_for": "Real Policy Proxy using Effective Fed Funds Rate instead of monthly FEDFUNDS.",
        },
    )
    latest = {
        "fetch_status": FETCH_STATUS,
        "cboe_vix": {"date": vix[-1]["date"] if vix else None, "url": CBOE_VIX_CSV},
        "treasury_curve_10y2y": {
            "date": treasury_curve[-1]["date"] if treasury_curve else None,
            "feed_updated": treasury_updated,
            "url": TREASURY_XML_URL.format(year=datetime.now().year),
        },
        "nyfed_effr": {"date": effr[-1]["date"] if effr else None},
        "fred_t10yie": {"date": t10yie[-1]["date"] if t10yie else None},
        "real_policy_proxy": {"date": real_policy[-1]["date"] if real_policy else None},
    }
    payload["current_market_fetch_status"] = FETCH_STATUS
    for name, status in FETCH_STATUS.items():
        if status["mode"] != "live":
            payload.setdefault("source_failures", []).append({"source": f"Current market refresh: {name}", "status": f"Used validated cache; original observation dates retained. Last successful fetch: {status['last_successful_fetch'] or 'unknown'}. {status.get('error', '')}"})
    for source in payload.get("sources", []):
        status = next((item for item in FETCH_STATUS.values() if item["url"] == source.get("url")), None)
        if source.get("name") == "Cboe VIX historical price data":
            status = FETCH_STATUS.get("VIX_History.csv")
        if status:
            source["refresh_mode"] = status["mode"]
            source["last_successful_fetch"] = status["last_successful_fetch"]
            source["publication_date"] += f"; refresh mode: {status['mode']}; last successful retrieval: {status['last_successful_fetch'] or 'unknown'}"
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", **latest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
