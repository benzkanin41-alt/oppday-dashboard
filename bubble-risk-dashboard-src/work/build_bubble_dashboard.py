from __future__ import annotations

import csv
import html
import io
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(os.environ.get("BUBBLE_DASHBOARD_ROOT", Path(__file__).resolve().parents[1])).resolve()
OUT = ROOT / "outputs" / "dashboard"
RAW = ROOT / "work" / "raw"
RUN_DATE = date.today()


FRED_SERIES = {
    "SP500": {
        "label": "S&P 500 Index",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/SP500",
        "group": "market",
    },
    "NASDAQCOM": {
        "label": "NASDAQ Composite Index",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/NASDAQCOM",
        "group": "market",
    },
    "VIXCLS": {
        "label": "Cboe VIX Index",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/VIXCLS",
        "group": "sentiment",
    },
    "DGS10": {
        "label": "10-Year Treasury Constant Maturity",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/DGS10",
        "group": "rates",
    },
    "DGS2": {
        "label": "2-Year Treasury Constant Maturity",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/DGS2",
        "group": "rates",
    },
    "FEDFUNDS": {
        "label": "Effective Federal Funds Rate",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/FEDFUNDS",
        "group": "rates",
    },
    "T10YIE": {
        "label": "10-Year Breakeven Inflation Rate",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/T10YIE",
        "group": "inflation",
    },
    "BAMLH0A0HYM2": {
        "label": "ICE BofA US High Yield Option-Adjusted Spread",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
        "group": "credit",
    },
    "WALCL": {
        "label": "Federal Reserve Total Assets",
        "source": "FRED graph CSV",
        "url": "https://fred.stlouisfed.org/series/WALCL",
        "group": "liquidity",
    },
}


ETF_UNIVERSE = [
    {"symbol": "SPY", "name": "S&P 500 proxy", "region": "US", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "QQQ", "name": "Nasdaq-100 proxy", "region": "US", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "IWM", "name": "Russell 2000 proxy", "region": "US", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "FEZ", "name": "Euro Stoxx 50 proxy", "region": "Europe", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "VGK", "name": "Europe developed proxy", "region": "Europe", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "EWJ", "name": "Japan proxy", "region": "Japan", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "MCHI", "name": "China broad proxy", "region": "China/HK", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "FXI", "name": "China large-cap proxy", "region": "China/HK", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "INDA", "name": "India proxy", "region": "India", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "EWY", "name": "South Korea proxy", "region": "South Korea", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "ACWI", "name": "MSCI ACWI proxy", "region": "Global", "bucket": "Index Proxy", "assetclass": "etf"},
    {"symbol": "XLK", "name": "S&P 500 Information Technology", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLC", "name": "S&P 500 Communication Services", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLY", "name": "S&P 500 Consumer Discretionary", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLP", "name": "S&P 500 Consumer Staples", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLV", "name": "S&P 500 Health Care", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLF", "name": "S&P 500 Financials", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLI", "name": "S&P 500 Industrials", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLE", "name": "S&P 500 Energy", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLB", "name": "S&P 500 Materials", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLU", "name": "S&P 500 Utilities", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "XLRE", "name": "S&P 500 Real Estate", "region": "US", "bucket": "S&P 500 Sector", "assetclass": "etf"},
    {"symbol": "SMH", "name": "Nasdaq theme: Semiconductors", "region": "US", "bucket": "Nasdaq Theme Proxy", "assetclass": "etf"},
    {"symbol": "IGV", "name": "Nasdaq theme: Software", "region": "US", "bucket": "Nasdaq Theme Proxy", "assetclass": "etf"},
    {"symbol": "SKYY", "name": "Nasdaq theme: Cloud", "region": "US", "bucket": "Nasdaq Theme Proxy", "assetclass": "etf"},
    {"symbol": "CIBR", "name": "Nasdaq theme: Cybersecurity", "region": "US", "bucket": "Nasdaq Theme Proxy", "assetclass": "etf"},
    {"symbol": "IBB", "name": "Nasdaq theme: Biotechnology", "region": "US", "bucket": "Nasdaq Theme Proxy", "assetclass": "etf"},
    {"symbol": "ARKK", "name": "Speculative growth proxy", "region": "US", "bucket": "Nasdaq Theme Proxy", "assetclass": "etf"},
]


SOURCE_NOTES = [
    {
        "name": "FRED series observations endpoint",
        "url": "https://fred.stlouisfed.org/docs/api/fred/series_observations.html",
        "publication_date": "No publication date shown; accessed 2026-07-02",
        "used_for": "API design reference and FRED graph CSV source path.",
    },
    {
        "name": "SEC EDGAR APIs",
        "url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "publication_date": "Last reviewed 2025-04-08 on SEC page",
        "used_for": "Planned company facts/submissions adapter for valuation and fundamentals.",
    },
    {
        "name": "BIS central bank policy rates",
        "url": "https://data.bis.org/topics/CBPOL",
        "publication_date": "Latest release shown on BIS topic page; accessed 2026-07-02",
        "used_for": "Planned cross-country policy-rate adapter.",
    },
    {
        "name": "BIS central bank total assets",
        "url": "https://data.bis.org/topics/CBTA",
        "publication_date": "Latest release shown on BIS topic page; accessed 2026-07-02",
        "used_for": "Planned cross-country central-bank balance-sheet adapter.",
    },
    {
        "name": "GICS structure",
        "url": "https://www.spglobal.com/spdji/en/landing/topic/gics/",
        "publication_date": "Accessed 2026-07-02",
        "used_for": "S&P 500 sector taxonomy design.",
    },
    {
        "name": "Nasdaq-100 methodology",
        "url": "https://indexes.nasdaqomx.com/docs/Methodology_NDX.pdf",
        "publication_date": "Copyright 2026",
        "used_for": "Nasdaq-100 non-financial eligibility and modified market-cap weighting context.",
    },
    {
        "name": "Nasdaq historical quote API",
        "url": "https://api.nasdaq.com/api/quote/{symbol}/historical",
        "publication_date": "Data fetched 2026-07-02",
        "used_for": "ETF proxy historical prices and volumes.",
    },
    {
        "name": "Cboe VIX overview",
        "url": "https://www.cboe.com/tradable-products/vix",
        "publication_date": "Market data as of 2026-07-02 on page",
        "used_for": "VIX interpretation and sentiment source context.",
    },
    {
        "name": "yfinance project notes",
        "url": "https://github.com/ranaroussi/yfinance",
        "publication_date": "Latest release shown 2026-06-28; accessed 2026-07-02",
        "used_for": "Yahoo Finance adapter caveat; Yahoo chart API was rate-limited in this run.",
    },
]


@dataclass
class Point:
    d: date
    v: float
    volume: float | None = None


def request_text(url: str, *, accept: str = "*/*") -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodexBubbleDashboard/0.1",
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=35) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_date(text: str, fmt: str) -> date:
    return datetime.strptime(text, fmt).date()


def fetch_fred_series(series_id: str) -> dict:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    raw = request_text(url, accept="text/csv")
    (RAW / "fred").mkdir(parents=True, exist_ok=True)
    (RAW / "fred" / f"{series_id}.csv").write_text(raw, encoding="utf-8")
    points: list[Point] = []
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        val = parse_float(row.get(series_id))
        if val is None:
            continue
        points.append(Point(safe_date(row["observation_date"], "%Y-%m-%d"), val))
    return {"ok": bool(points), "points": points, "error": None, "url": url}


def fetch_nasdaq_history(symbol: str, assetclass: str = "etf") -> dict:
    params = urlencode(
        {
            "assetclass": assetclass,
            "fromdate": "2021-01-01",
            "todate": RUN_DATE.isoformat(),
            "limit": "9999",
        }
    )
    url = f"https://api.nasdaq.com/api/quote/{symbol}/historical?{params}"
    try:
        raw = request_text(url, accept="application/json")
        (RAW / "nasdaq").mkdir(parents=True, exist_ok=True)
        (RAW / "nasdaq" / f"{symbol}.json").write_text(raw, encoding="utf-8")
        payload = json.loads(raw)
        rows = (((payload.get("data") or {}).get("tradesTable") or {}).get("rows") or [])
        points: list[Point] = []
        for row in rows:
            val = parse_float(row.get("close"))
            if val is None:
                continue
            vol = parse_float(row.get("volume"))
            points.append(Point(safe_date(row["date"], "%m/%d/%Y"), val, vol))
        points.sort(key=lambda p: p.d)
        return {"ok": bool(points), "points": points, "error": None, "url": url}
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        return {"ok": False, "points": [], "error": repr(exc), "url": url}


def pct_return(points: list[Point], periods: int) -> float | None:
    if len(points) <= periods:
        return None
    latest = points[-1].v
    base = points[-1 - periods].v
    if base == 0:
        return None
    return (latest / base - 1) * 100


def moving_avg(points: list[Point], periods: int) -> float | None:
    if len(points) < periods:
        return None
    return statistics.fmean(p.v for p in points[-periods:])


def trailing_drawdown(points: list[Point], periods: int = 252) -> float | None:
    if not points:
        return None
    sample = points[-periods:] if len(points) >= periods else points
    high = max(p.v for p in sample)
    if high == 0:
        return None
    return (points[-1].v / high - 1) * 100


def interp_score(value: float | None, anchors: list[tuple[float, float]]) -> float:
    if value is None or math.isnan(value):
        return 50.0
    anchors = sorted(anchors)
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    return 50.0


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def summarize_price(points: list[Point]) -> dict:
    latest = points[-1] if points else None
    ma200 = moving_avg(points, 200)
    latest_value = latest.v if latest else None
    dist_200 = ((latest_value / ma200 - 1) * 100) if latest_value is not None and ma200 else None
    ret_1m = pct_return(points, 21)
    ret_3m = pct_return(points, 63)
    ret_1y = pct_return(points, 252)
    ret_3y = pct_return(points, 756)
    dd_1y = trailing_drawdown(points, 252)
    avg_vol_60 = None
    latest_vol = None
    vol_ratio = None
    vols = [p.volume for p in points[-60:] if p.volume is not None]
    if vols:
        avg_vol_60 = statistics.fmean(vols)
        latest_vol = points[-1].volume
        if latest_vol is not None and avg_vol_60:
            vol_ratio = latest_vol / avg_vol_60
    price_score = statistics.fmean(
        [
            interp_score(ret_1y, [(-30, 10), (-10, 25), (0, 40), (10, 55), (25, 75), (45, 92), (70, 100)]),
            interp_score(ret_3y, [(-30, 15), (0, 40), (25, 58), (60, 78), (100, 95), (150, 100)]),
            interp_score(dist_200, [(-20, 10), (-10, 25), (0, 45), (8, 62), (18, 82), (30, 96)]),
            interp_score(dd_1y, [(-45, 10), (-25, 25), (-12, 45), (-5, 62), (0, 80)]),
        ]
    )
    volume_score = interp_score(vol_ratio, [(0.4, 25), (0.8, 45), (1.0, 55), (1.5, 72), (2.5, 90), (4.0, 100)])
    return {
        "as_of": latest.d.isoformat() if latest else None,
        "latest": latest_value,
        "ret_1m": ret_1m,
        "ret_3m": ret_3m,
        "ret_1y": ret_1y,
        "ret_3y": ret_3y,
        "dist_200dma": dist_200,
        "drawdown_1y": dd_1y,
        "latest_volume": latest_vol,
        "avg_volume_60d": avg_vol_60,
        "volume_ratio": vol_ratio,
        "price_heat_score": clamp(price_score),
        "volume_heat_score": clamp(volume_score),
        "sparkline": [{"date": p.d.isoformat(), "value": p.v} for p in points[-180:]],
    }


def latest_value(series: dict[str, dict], key: str) -> float | None:
    points = series.get(key, {}).get("points") or []
    return points[-1].v if points else None


def latest_date(series: dict[str, dict], key: str) -> str | None:
    points = series.get(key, {}).get("points") or []
    return points[-1].d.isoformat() if points else None


def build_macro_scores(fred: dict[str, dict]) -> dict:
    vix = latest_value(fred, "VIXCLS")
    dgs10 = latest_value(fred, "DGS10")
    dgs2 = latest_value(fred, "DGS2")
    fedfunds = latest_value(fred, "FEDFUNDS")
    breakeven = latest_value(fred, "T10YIE")
    hy_oas = latest_value(fred, "BAMLH0A0HYM2")
    walcl_points = fred.get("WALCL", {}).get("points") or []
    walcl_1y = pct_return(walcl_points, 52) if len(walcl_points) < 400 else pct_return(walcl_points, 252)
    yield_curve = dgs10 - dgs2 if dgs10 is not None and dgs2 is not None else None
    real_policy = fedfunds - breakeven if fedfunds is not None and breakeven is not None else None
    sentiment_score = interp_score(vix, [(10, 92), (14, 80), (18, 60), (25, 35), (35, 18), (50, 5)])
    credit_score = interp_score(hy_oas, [(2.0, 92), (3.0, 78), (4.5, 55), (6.0, 35), (8.5, 15), (12, 5)])
    curve_score = interp_score(yield_curve, [(-1.5, 75), (-0.5, 62), (0, 50), (1.0, 42), (2.0, 35)])
    real_rate_score = interp_score(real_policy, [(-2.0, 90), (0.0, 72), (1.0, 55), (2.0, 38), (3.5, 20)])
    liquidity_score = interp_score(walcl_1y, [(-15, 20), (-5, 35), (0, 50), (5, 65), (15, 84), (30, 95)])
    macro_score = statistics.fmean([curve_score, real_rate_score, liquidity_score])
    return {
        "vix": vix,
        "vix_as_of": latest_date(fred, "VIXCLS"),
        "hy_oas": hy_oas,
        "hy_oas_as_of": latest_date(fred, "BAMLH0A0HYM2"),
        "yield_curve_10y_2y": yield_curve,
        "yield_curve_as_of": latest_date(fred, "DGS10"),
        "fedfunds": fedfunds,
        "breakeven_10y": breakeven,
        "real_policy_proxy": real_policy,
        "fed_assets_1y_change": walcl_1y,
        "sentiment_score": clamp(sentiment_score),
        "credit_score": clamp(credit_score),
        "macro_liquidity_score": clamp(macro_score),
    }


def fmt_num(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}%"


def risk_band(score: float | None) -> str:
    if score is None:
        return "Missing"
    if score < 25:
        return "Fear / cheap watch"
    if score < 50:
        return "Normal"
    if score < 65:
        return "Warm"
    if score < 80:
        return "Frothy"
    if score < 90:
        return "Bubble risk"
    return "Mania"


def score_color(score: float | None) -> str:
    if score is None:
        return "#8b949e"
    if score < 25:
        return "#2a9d8f"
    if score < 50:
        return "#5aa469"
    if score < 65:
        return "#d9a441"
    if score < 80:
        return "#e07a3f"
    return "#cf3f48"


def spark_svg(points: list[dict], width: int = 128, height: int = 38) -> str:
    if len(points) < 2:
        return ""
    vals = [float(p["value"]) for p in points]
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    coords = []
    for i, val in enumerate(vals):
        x = i * (width - 2) / (len(vals) - 1) + 1
        y = height - 2 - ((val - lo) / span) * (height - 4)
        coords.append(f"{x:.1f},{y:.1f}")
    return f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true"><polyline points="{" ".join(coords)}"></polyline></svg>'


def card(title: str, value: str, sub: str, score: float | None = None) -> str:
    color = score_color(score)
    ring = "" if score is None else f'<span class="mini-score" style="--score-color:{color};">{score:.0f}</span>'
    return f"""
    <section class="kpi-card">
      <div class="kpi-head"><span>{html.escape(title)}</span>{ring}</div>
      <strong>{html.escape(value)}</strong>
      <p>{html.escape(sub)}</p>
    </section>
    """


def render_dashboard(payload: dict) -> str:
    generated = payload["generated_at"]
    overall = payload["overall"]
    confidence = payload["confidence"]
    indices = payload["indices"]
    sectors = payload["sectors"]
    themes = payload["themes"]
    macro = payload["macro"]
    watch = payload["watchlist"]
    failures = payload["source_failures"]
    source_rows = "\n".join(
        f"<tr><td>{html.escape(src['name'])}</td><td>{html.escape(src['used_for'])}</td><td>{html.escape(src['publication_date'])}</td><td><a href=\"{html.escape(src['url'])}\">source</a></td></tr>"
        for src in payload["sources"]
    )
    index_cards = "\n".join(render_market_tile(item) for item in indices)
    sector_tiles = "\n".join(render_market_tile(item) for item in sectors)
    theme_tiles = "\n".join(render_market_tile(item) for item in themes)
    watch_rows = "\n".join(
        f"<tr><td>{html.escape(w['name'])}</td><td>{html.escape(w['bucket'])}</td><td><span class=\"score-pill\" style=\"--pill:{score_color(w['score'])}\">{w['score']:.0f}</span></td><td>{fmt_pct(w['ret_1y'])}</td><td>{fmt_pct(w['dist_200dma'])}</td><td>{html.escape(w['as_of'] or 'n/a')}</td></tr>"
        for w in watch
    )
    failure_items = "\n".join(f"<li><strong>{html.escape(f['source'])}</strong>: {html.escape(f['status'])}</li>" for f in failures)
    methodology = "\n".join(
        f"<li><strong>{html.escape(m['name'])}</strong>: {html.escape(m['definition'])}</li>"
        for m in payload["methodology"]
    )
    return f"""<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bubble Risk Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --ink:#16202a;
      --muted:#607084;
      --line:#d9e0e8;
      --bg:#f6f8fb;
      --panel:#ffffff;
      --blue:#245f86;
      --teal:#2a9d8f;
      --gold:#d9a441;
      --orange:#e07a3f;
      --red:#cf3f48;
      --slate:#35495e;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      font-family: Arial, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }}
    header {{
      background:#102333;
      color:#fff;
      padding:22px clamp(16px, 4vw, 46px) 18px;
      border-bottom:4px solid #2a9d8f;
    }}
    .topbar {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px; flex-wrap:wrap; }}
    h1 {{ margin:0; font-size:clamp(28px, 4vw, 44px); font-weight:800; }}
    .subtitle {{ margin:8px 0 0; max-width:900px; color:#d8e3ea; line-height:1.45; font-size:15px; }}
    .freshness {{ text-align:right; font-size:13px; color:#cfe2ee; min-width:230px; }}
    main {{ padding:22px clamp(14px, 3vw, 38px) 42px; }}
    .hero-grid {{ display:grid; grid-template-columns: minmax(220px, 1.1fr) repeat(4, minmax(150px, .7fr)); gap:14px; align-items:stretch; }}
    .score-hero {{
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:8px;
      padding:18px;
      min-height:166px;
    }}
    .score-big {{ font-size:56px; line-height:1; font-weight:850; color:{score_color(overall['score'])}; }}
    .band {{ margin-top:8px; font-weight:750; color:var(--slate); }}
    .driver {{ margin:12px 0 0; color:var(--muted); line-height:1.4; }}
    .kpi-card {{
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:8px;
      padding:15px;
      min-height:130px;
    }}
    .kpi-head {{ display:flex; justify-content:space-between; gap:8px; color:var(--muted); font-size:13px; font-weight:700; }}
    .kpi-card strong {{ display:block; font-size:28px; margin-top:14px; color:var(--ink); }}
    .kpi-card p {{ margin:8px 0 0; color:var(--muted); line-height:1.35; font-size:13px; }}
    .mini-score {{
      display:inline-grid; place-items:center; min-width:34px; height:26px;
      border-radius:99px; background: color-mix(in srgb, var(--score-color), white 84%);
      color:var(--score-color); font-weight:850;
    }}
    .section {{ margin-top:22px; }}
    .section-title {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin:0 0 10px; }}
    h2 {{ margin:0; font-size:22px; }}
    .note {{ color:var(--muted); font-size:13px; line-height:1.4; }}
    .tile-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(238px, 1fr)); gap:12px; }}
    .market-tile {{
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:8px;
      padding:13px;
      display:grid;
      grid-template-columns: 1fr auto;
      gap:8px 10px;
      min-height:152px;
    }}
    .market-tile h3 {{ margin:0; font-size:15px; line-height:1.25; }}
    .market-tile .meta {{ color:var(--muted); font-size:12px; margin-top:4px; }}
    .score-pill {{
      --pill:#888;
      display:inline-grid;
      place-items:center;
      min-width:42px;
      height:34px;
      border-radius:8px;
      background: color-mix(in srgb, var(--pill), white 84%);
      color:var(--pill);
      font-weight:850;
      border:1px solid color-mix(in srgb, var(--pill), white 62%);
    }}
    .tile-metrics {{ grid-column:1 / -1; display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; }}
    .metric {{ background:#f7f9fb; border:1px solid #e5ebf0; border-radius:7px; padding:8px; }}
    .metric span {{ display:block; color:var(--muted); font-size:11px; }}
    .metric b {{ display:block; margin-top:4px; font-size:14px; }}
    .spark {{ width:100%; height:38px; grid-column:1 / -1; }}
    .spark polyline {{ fill:none; stroke:#245f86; stroke-width:2.4; stroke-linecap:round; stroke-linejoin:round; }}
    .two-col {{ display:grid; grid-template-columns:minmax(280px, .8fr) minmax(320px, 1.2fr); gap:14px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:15px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid #e8edf2; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; }}
    .method-list {{ margin:0; padding-left:18px; color:var(--muted); line-height:1.5; }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }}
    .tab-btn {{
      border:1px solid var(--line);
      background:#fff;
      color:var(--slate);
      border-radius:8px;
      padding:9px 12px;
      cursor:pointer;
      font-weight:750;
    }}
    .tab-btn.active {{ background:#245f86; color:#fff; border-color:#245f86; }}
    .hidden {{ display:none; }}
    .footer-note {{ margin-top:18px; color:var(--muted); font-size:12px; line-height:1.5; }}
    @media (max-width: 980px) {{
      .hero-grid {{ grid-template-columns:1fr 1fr; }}
      .score-hero {{ grid-column:1 / -1; }}
      .two-col {{ grid-template-columns:1fr; }}
      .freshness {{ text-align:left; }}
    }}
    @media (max-width: 620px) {{
      .hero-grid {{ grid-template-columns:1fr; }}
      .tile-metrics {{ grid-template-columns:1fr; }}
      th:nth-child(4), td:nth-child(4), th:nth-child(5), td:nth-child(5) {{ display:none; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>Bubble Risk Dashboard</h1>
        <p class="subtitle">แผงติดตามความร้อนของตลาดจากราคา, sector/theme, sentiment, credit และ liquidity โดยใช้ข้อมูลที่ดึงได้จริงในรอบ build นี้ พร้อมบอก source และช่องว่างของข้อมูลอย่างเปิดเผย</p>
      </div>
      <div class="freshness">Generated: {html.escape(generated)}<br>Data anchor: market data through {html.escape(payload['data_anchor'])}</div>
    </div>
  </header>
  <main>
    <section class="hero-grid">
      <div class="score-hero">
        <div class="score-big">{overall['score']:.0f}</div>
        <div class="band">{html.escape(overall['band'])}</div>
        <p class="driver">{html.escape(overall['driver'])}</p>
      </div>
      {card("Price Heat", f"{overall['price_score']:.0f}", "Composite from index ETF proxies and FRED market history.", overall['price_score'])}
      {card("Sector Heat", f"{overall['sector_score']:.0f}", "S&P 500 sector ETF heat score.", overall['sector_score'])}
      {card("Sentiment", f"{macro['sentiment_score']:.0f}", f"VIX {fmt_num(macro['vix'])} as of {macro['vix_as_of']}", macro['sentiment_score'])}
      {card("Data Confidence", f"{confidence['score']:.0f}", confidence['summary'], confidence['score'])}
    </section>

    <section class="section two-col">
      <div class="panel">
        <h2>Score Model</h2>
        <ul class="method-list">{methodology}</ul>
        <p class="footer-note">Scores are 0-100. Higher means more bubble/mania risk, not a short-term sell signal. Missing fundamentals are intentionally confidence penalties, not hidden assumptions.</p>
      </div>
      <div class="panel">
        <h2>Top Watchlist</h2>
        <table>
          <thead><tr><th>Name</th><th>Bucket</th><th>Score</th><th>1Y</th><th>vs 200DMA</th><th>As of</th></tr></thead>
          <tbody>{watch_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>Market, Sector And Theme Heat</h2>
        <span class="note">กดแท็บเพื่อแยก global proxies, S&P 500 sectors และ Nasdaq theme proxies</span>
      </div>
      <div class="tabs">
        <button class="tab-btn active" data-tab="indices">Index proxies</button>
        <button class="tab-btn" data-tab="sectors">S&P 500 sectors</button>
        <button class="tab-btn" data-tab="themes">Nasdaq themes</button>
      </div>
      <div id="indices" class="tile-grid">{index_cards}</div>
      <div id="sectors" class="tile-grid hidden">{sector_tiles}</div>
      <div id="themes" class="tile-grid hidden">{theme_tiles}</div>
    </section>

    <section class="section two-col">
      <div class="panel">
        <h2>Macro Snapshot</h2>
        <table>
          <tbody>
            <tr><th>VIX</th><td>{fmt_num(macro['vix'])}</td><td>{html.escape(macro['vix_as_of'] or 'n/a')}</td></tr>
            <tr><th>HY OAS</th><td>{fmt_num(macro['hy_oas'])}</td><td>{html.escape(macro['hy_oas_as_of'] or 'n/a')}</td></tr>
            <tr><th>10Y-2Y curve</th><td>{fmt_num(macro['yield_curve_10y_2y'])} pp</td><td>{html.escape(macro['yield_curve_as_of'] or 'n/a')}</td></tr>
            <tr><th>Real policy proxy</th><td>{fmt_num(macro['real_policy_proxy'])} pp</td><td>Fed funds minus 10Y breakeven</td></tr>
            <tr><th>Fed assets 1Y</th><td>{fmt_pct(macro['fed_assets_1y_change'])}</td><td>FRED WALCL</td></tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Source Gaps</h2>
        <ul class="method-list">{failure_items}</ul>
        <p class="footer-note">TradingView Remix MCP was searched in the available tool registry but no callable market-data tool was exposed in this session. Yahoo chart API returned Too Many Requests, so Nasdaq ETF history and FRED are used in this version.</p>
      </div>
    </section>

    <section class="section panel">
      <h2>Source Manifest</h2>
      <table>
        <thead><tr><th>Source</th><th>Used For</th><th>Publication / Access Date</th><th>Link</th></tr></thead>
        <tbody>{source_rows}</tbody>
      </table>
    </section>
  </main>
  <script>
    document.querySelectorAll('.tab-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tile-grid').forEach(p => p.classList.add('hidden'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.remove('hidden');
      }});
    }});
  </script>
</body>
</html>"""


def render_market_tile(item: dict) -> str:
    m = item["metrics"]
    score = item["score"]
    return f"""
    <article class="market-tile">
      <div>
        <h3>{html.escape(item['name'])}</h3>
        <div class="meta">{html.escape(item['symbol'])} - {html.escape(item['region'])} - {html.escape(item['as_of'] or 'n/a')}</div>
      </div>
      <span class="score-pill" style="--pill:{score_color(score)}">{score:.0f}</span>
      {spark_svg(m.get('sparkline') or [])}
      <div class="tile-metrics">
        <div class="metric"><span>1Y return</span><b>{fmt_pct(m.get('ret_1y'))}</b></div>
        <div class="metric"><span>vs 200DMA</span><b>{fmt_pct(m.get('dist_200dma'))}</b></div>
        <div class="metric"><span>1Y drawdown</span><b>{fmt_pct(m.get('drawdown_1y'))}</b></div>
      </div>
    </article>
    """


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    fred: dict[str, dict] = {}
    source_failures = []
    for series_id in FRED_SERIES:
        try:
            fred[series_id] = fetch_fred_series(series_id)
        except Exception as exc:
            fred[series_id] = {"ok": False, "points": [], "error": repr(exc), "url": f"https://fred.stlouisfed.org/series/{series_id}"}
            source_failures.append({"source": f"FRED {series_id}", "status": repr(exc)})

    market_items = []
    for item in ETF_UNIVERSE:
        result = fetch_nasdaq_history(item["symbol"], item["assetclass"])
        if not result["ok"]:
            source_failures.append({"source": f"Nasdaq {item['symbol']}", "status": result["error"] or "No rows returned"})
            continue
        metrics = summarize_price(result["points"])
        score = clamp(metrics["price_heat_score"] * 0.78 + metrics["volume_heat_score"] * 0.12 + 50 * 0.10)
        market_items.append({**item, "as_of": metrics["as_of"], "score": score, "metrics": metrics, "source_url": result["url"]})
        time.sleep(0.05)

    macro = build_macro_scores(fred)
    indices = [x for x in market_items if x["bucket"] == "Index Proxy"]
    sectors = [x for x in market_items if x["bucket"] == "S&P 500 Sector"]
    themes = [x for x in market_items if x["bucket"] == "Nasdaq Theme Proxy"]

    price_score = statistics.fmean([x["score"] for x in indices]) if indices else 50.0
    sector_score = statistics.fmean([x["score"] for x in sectors]) if sectors else 50.0
    theme_score = statistics.fmean([x["score"] for x in themes]) if themes else 50.0
    credit_liquidity = statistics.fmean([macro["credit_score"], macro["macro_liquidity_score"]])
    overall_score = clamp(
        price_score * 0.30
        + sector_score * 0.23
        + theme_score * 0.17
        + macro["sentiment_score"] * 0.12
        + macro["credit_score"] * 0.10
        + macro["macro_liquidity_score"] * 0.08
    )
    planned_sources = 8
    live_source_groups = 2 + int(bool(indices)) + int(bool(sectors)) + int(bool(themes))
    confidence_score = clamp(live_source_groups / planned_sources * 100)
    watchlist = sorted(market_items, key=lambda x: x["score"], reverse=True)[:10]
    data_anchor = max([x["as_of"] for x in market_items if x.get("as_of")] or [RUN_DATE.isoformat()])
    driver_pool = [
        ("price heat", price_score),
        ("sector heat", sector_score),
        ("Nasdaq theme heat", theme_score),
        ("sentiment", macro["sentiment_score"]),
        ("credit/liquidity", credit_liquidity),
    ]
    top_driver = max(driver_pool, key=lambda x: x[1])
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M local"),
        "data_anchor": data_anchor,
        "overall": {
            "score": overall_score,
            "band": risk_band(overall_score),
            "driver": f"Top live driver in this build: {top_driver[0]} ({top_driver[1]:.0f}/100).",
            "price_score": price_score,
            "sector_score": sector_score,
            "theme_score": theme_score,
            "credit_liquidity_score": credit_liquidity,
        },
        "confidence": {
            "score": confidence_score,
            "summary": f"{live_source_groups}/{planned_sources} source groups live; gaps are listed below.",
        },
        "macro": macro,
        "indices": indices,
        "sectors": sectors,
        "themes": themes,
        "watchlist": [
            {
                "name": x["name"],
                "symbol": x["symbol"],
                "bucket": x["bucket"],
                "score": x["score"],
                "ret_1y": x["metrics"].get("ret_1y"),
                "dist_200dma": x["metrics"].get("dist_200dma"),
                "as_of": x["as_of"],
            }
            for x in watchlist
        ],
        "methodology": [
            {
                "name": "Price heat",
                "definition": "Blend of 1Y/3Y return, distance from 200DMA, and 1Y drawdown recovery.",
            },
            {
                "name": "Sector/theme heat",
                "definition": "ETF proxy price heat plus volume heat; valuation/fundamental adapters are explicitly pending.",
            },
            {
                "name": "Sentiment",
                "definition": "VIX low = complacency/greed heat; VIX high = fear heat reduced.",
            },
            {
                "name": "Credit and liquidity",
                "definition": "High-yield spreads, yield curve, real policy proxy, and Fed balance-sheet change.",
            },
        ],
        "sources": SOURCE_NOTES,
        "source_failures": source_failures
        + [
            {"source": "Yahoo Finance chart API", "status": "Returned Too Many Requests during this run; kept as future fallback only."},
            {"source": "TradingView Remix MCP", "status": "No callable TradingView market-data MCP exposed by tool discovery in this session."},
            {"source": "EDGAR fundamentals", "status": "Planned adapter; not yet aggregated into live sector valuations in v0.1."},
            {"source": "BIS global rates/assets", "status": "Planned adapter; current live macro panel uses FRED US series first."},
        ],
    }

    (OUT / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "source-manifest.json").write_text(json.dumps(payload["sources"], ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "index.html").write_text(render_dashboard(payload), encoding="utf-8")
    print(json.dumps({"status": "ok", "out": str(OUT), "items": len(market_items), "failures": len(payload["source_failures"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



