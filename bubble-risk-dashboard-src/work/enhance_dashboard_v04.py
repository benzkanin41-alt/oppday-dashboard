from __future__ import annotations

import csv
import gzip
import html
import importlib.util
import io
import json
import math
import re
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
RAW = ROOT / "work" / "raw"
START_1990 = date(1990, 1, 1)
RANGES = [("1M", 31), ("3M", 93), ("6M", 186), ("1Y", 366), ("5Y", 366 * 5), ("10Y", 366 * 10), ("MAX", None)]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
HEADERS_HTML = {"User-Agent": UA, "Accept": "text/html,*/*", "Accept-Encoding": "gzip, deflate", "Accept-Language": "en-US,en;q=0.9"}
HEADERS_JSON = {"User-Agent": UA, "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9"}

PRICE_PROXY = {
    "SPY": ("^GSPC", "S&P 500 Index"),
    "QQQ": ("^NDX", "Nasdaq-100 Index"),
    "IWM": ("^RUT", "Russell 2000 Index"),
    "FEZ": ("^STOXX50E", "Euro Stoxx 50"),
    "VGK": ("VGK", "VGK Europe ETF"),
    "EWJ": ("^N225", "Nikkei 225"),
    "MCHI": ("000001.SS", "Shanghai Composite"),
    "FXI": ("^HSI", "Hang Seng Index"),
    "INDA": ("^NSEI", "Nifty 50"),
    "EWY": ("^KS11", "KOSPI"),
    "ACWI": ("ACWI", "ACWI ETF"),
    "SET": ("^SET.BK", "SET Index"),
    "mai": ("^MAI.BK", "mai Index"),
}
SSGA_FORWARD = {
    "SPY": "https://www.ssga.com/us/en/intermediary/etfs/spdr-sp-500-etf-trust-spy",
    "FEZ": "https://www.ssga.com/us/en/intermediary/etfs/spdr-euro-stoxx-50-etf-fez",
}
ISHARES = {
    "IWM": "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf",
    "ACWI": "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf",
    "EWJ": "https://www.ishares.com/us/products/239665/ishares-msci-japan-etf",
    "MCHI": "https://www.ishares.com/us/products/239619/ishares-msci-china-etf",
    "FXI": "https://www.ishares.com/us/products/239536/ishares-china-largecap-etf",
    "INDA": "https://www.ishares.com/us/products/239659/ishares-msci-india-etf",
    "EWY": "https://www.ishares.com/us/products/239681/ishares-msci-south-korea-etf",
}


def load_v03():
    spec = importlib.util.spec_from_file_location("bubble_v03", ROOT / "work" / "enhance_dashboard_interactive_v03.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def request_text(url: str, headers: dict | None = None, timeout=45) -> str:
    raw = urlopen(Request(url, headers=headers or HEADERS_HTML), timeout=timeout).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def parse_float(value):
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if text in {"", "-", ".", "N/A", "n/a", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault("sources", [])
    if not any(s.get("name") == source["name"] for s in sources):
        sources.append(source)


def add_failure_once(payload: dict, source: str, status: str) -> None:
    failures = payload.setdefault("source_failures", [])
    if not any(f.get("source") == source for f in failures):
        failures.append({"source": source, "status": status})


def strip_marker(text: str, marker: str) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    while start in text and end in text:
        a = text.index(start)
        b = text.index(end, a) + len(end)
        text = text[:a] + text[b:]
    return text


def fred_series(series_id: str, start: date = START_1990) -> list[dict]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    out_dir = RAW / "fred_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / f"{series_id}.csv"
    try:
        proc = subprocess.run(
            ["curl.exe", "-L", "--silent", "--show-error", "--max-time", "45", url],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        raw = proc.stdout
        if "observation_date" not in raw[:200]:
            raise RuntimeError(f"unexpected FRED CSV header for {series_id}")
        cache.write_text(raw, encoding="utf-8")
    except Exception:
        if cache.exists() and cache.stat().st_size > 100:
            raw = cache.read_text(encoding="utf-8", errors="replace")
        else:
            raw = request_text(url, {"User-Agent": UA, "Accept": "text/csv"}, timeout=20)
            cache.write_text(raw, encoding="utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            d = datetime.strptime(row["observation_date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue
        value = parse_float(row.get(series_id))
        if d >= start and value is not None:
            rows.append({"date": d.isoformat(), "value": value})
    return rows


def yahoo_chart(symbol: str) -> list[dict]:
    p1 = int(datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
    enc = quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?period1={p1}&period2={p2}&interval=1d&events=history&includeAdjustedClose=true"
    raw = request_text(url, HEADERS_JSON)
    out_dir = RAW / "yahoo_chart_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', symbol)}.json").write_text(raw, encoding="utf-8")
    payload = json.loads(raw)
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    points = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, timezone.utc).date()
        if d >= START_1990:
            points.append({"date": d.isoformat(), "value": round(float(close), 6)})
    return points


def build_price_series(top_rows: list[dict], existing: dict) -> dict:
    out = {}
    for row in top_rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        chart_symbol, proxy_label = PRICE_PROXY.get(symbol, (symbol, f"{symbol} ETF"))
        points, note = [], ""
        try:
            points = yahoo_chart(chart_symbol)
        except Exception as exc:
            note = f"Yahoo chart fetch failed: {exc!r}."
        if not points and symbol in existing:
            points = (existing[symbol] or {}).get("points") or []
            note += " Fallback to v0.3 stored history."
        out[symbol] = {
            "label": row.get("name") or symbol,
            "symbol": symbol,
            "chart_symbol": chart_symbol,
            "source": "Yahoo Finance chart API",
            "source_url": f"https://finance.yahoo.com/quote/{quote(chart_symbol, safe='')}/history",
            "note": note or f"เนเธเน proxy: {proxy_label}; เธ–เนเธฒ start date เธซเธฅเธฑเธ 1990 เธเธทเธญ source เธกเธตเธเนเธญเธกเธนเธฅเธ•เธฑเนเธเนเธ•เนเธงเธฑเธเธเธฑเนเธเน€เธ—เนเธฒเธเธฑเนเธ",
            "points": points,
        }
        time.sleep(0.03)
    return out


def yahoo_trailing_pe(symbol: str):
    text = request_text(f"https://finance.yahoo.com/quote/{symbol}/key-statistics/", HEADERS_HTML)
    out_dir = RAW / "yahoo_valuation_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{symbol}.html").write_text(text, encoding="utf-8")
    matches = re.findall(r'trailingPE\\":\{\\"raw\\":([0-9.]+)', text)
    return parse_float(matches[-1]) if matches else None


def ishares_pe(symbol: str):
    url = ISHARES.get(symbol)
    if not url:
        return None
    text = request_text(url, HEADERS_HTML)
    out_dir = RAW / "issuer_valuation_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"ishares_{symbol}.html").write_text(text, encoding="utf-8")
    match = re.search(r'P/E Ratio","formattedValue":"([0-9.]+)"', text)
    return parse_float(match.group(1)) if match else None


def ssga_forward_pe(symbol: str):
    url = SSGA_FORWARD.get(symbol)
    if not url:
        return None
    text = request_text(url, HEADERS_HTML)
    out_dir = RAW / "issuer_valuation_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"ssga_{symbol}.html").write_text(text, encoding="utf-8")
    clean = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    match = re.search(r"Price/Earnings Ratio FY1.*?([0-9]+\.[0-9]+)", clean)
    return parse_float(match.group(1)) if match else None


def build_valuations(payload: dict) -> dict:
    rows = {r.get("symbol"): r for r in payload.get("earnings_yield_gap", [])}
    out = {}
    for symbol in ["SPY", "QQQ", "IWM", "FEZ", "VGK", "EWJ", "MCHI", "FXI", "INDA", "EWY", "ACWI"]:
        trailing, trailing_source = None, None
        try:
            trailing = ishares_pe(symbol)
            trailing_source = "iShares official product page P/E Ratio" if trailing else None
        except Exception:
            trailing = None
        if trailing is None:
            try:
                trailing = yahoo_trailing_pe(symbol)
                trailing_source = "Yahoo Finance key-statistics embedded trailingPE" if trailing else None
            except Exception:
                trailing = None
        forward, forward_source = None, None
        try:
            forward = ssga_forward_pe(symbol)
            forward_source = "State Street SPDR Price/Earnings Ratio FY1" if forward else None
        except Exception:
            forward = None
        if forward is None and symbol == "SPY":
            forward, forward_source = 20.59, "Barrons / Dow Jones Market Data, published 2026-07-01"
        out[symbol] = {"trailing_pe": trailing, "forward_pe": forward, "source": trailing_source, "forward_source": forward_source}
        time.sleep(0.05)
    for symbol in ["SET", "mai"]:
        old = rows.get(symbol, {})
        out[symbol] = {"trailing_pe": old.get("trailing_pe"), "forward_pe": None, "source": old.get("source") or "SET Market Overview", "forward_source": None}
    return out


def build_us_yield_curve_1990() -> dict:
    by_date, latest, latest_dates = {}, {}, []
    for tenor, sid in {"2Y": "DGS2", "5Y": "DGS5", "10Y": "DGS10", "30Y": "DGS30"}.items():
        points = fred_series(sid)
        if points:
            latest[tenor] = points[-1]["value"]
            latest_dates.append(points[-1]["date"])
        for p in points:
            by_date.setdefault(p["date"], {"date": p["date"]})[tenor] = p["value"]
    return {"country": "United States", "label": "U.S. Treasury Constant Maturity Curve", "source": "FRED", "source_url": "https://fred.stlouisfed.org/categories/115", "as_of": max(latest_dates) if latest_dates else None, "latest": latest, "history": [by_date[k] for k in sorted(by_date)]}


def latest_on_or_before(points: list[dict], iso_date: str):
    vals = [p for p in points if p["date"] <= iso_date]
    return vals[-1]["value"] if vals else None


def diff_series(a: list[dict], b: list[dict]) -> list[dict]:
    return [{"date": p["date"], "value": p["value"] - latest_on_or_before(b, p["date"])} for p in a if latest_on_or_before(b, p["date"]) is not None]


def ratio_series(a: list[dict], b: list[dict], b_mult=1.0) -> list[dict]:
    out = []
    for p in a:
        bv = latest_on_or_before(b, p["date"])
        if bv:
            out.append({"date": p["date"], "value": p["value"] / (bv * b_mult)})
    return out


def yoy(points: list[dict], periods=52) -> list[dict]:
    out = []
    for i, p in enumerate(points):
        if i >= periods and points[i - periods]["value"]:
            out.append({"date": p["date"], "value": (p["value"] / points[i - periods]["value"] - 1) * 100})
    return out


def percentile(values, latest, invert=False):
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if latest is None or not vals:
        return None
    pct = sum(1 for v in vals if v <= latest) / len(vals) * 100
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


def fmt(v, digits=2):
    return "n/a" if v is None else f"{v:,.{digits}f}"


def mini_spark(points):
    pts = [p for p in (points or [])[-80:] if p.get("value") is not None]
    if len(pts) < 2:
        return '<svg class="v04-spark" viewBox="0 0 120 32"></svg>'
    vals = [p["value"] for p in pts]
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    pairs = []
    for i, p in enumerate(pts):
        x = i * 118 / max(1, len(pts) - 1) + 1
        y = 30 - (p["value"] - lo) / span * 28
        pairs.append(f"{x:.1f},{y:.1f}")
    return f'<svg class="v04-spark" viewBox="0 0 120 32"><polyline points="{" ".join(pairs)}"/></svg>'


def build_macro(payload: dict):
    macro = payload.get("macro", {})
    series = {}
    for sid in ["NCBEILQ027S", "GDP", "BAA", "DGS10", "DGS2", "VIXCLS", "BAMLH0A0HYM2", "WALCL", "FEDFUNDS", "T10YIE"]:
        try:
            series[sid] = fred_series(sid)
        except Exception:
            series[sid] = []
    buffett = ratio_series(series["NCBEILQ027S"], series["GDP"], 1000.0)
    baa_spread = diff_series(series["BAA"], series["DGS10"])
    curve = diff_series(series["DGS10"], series["DGS2"])
    walcl_yoy = yoy(series["WALCL"])
    real_policy = diff_series(series["FEDFUNDS"], series["T10YIE"])
    specs = [
        ("Buffett Indicator (US equities / GDP)", "เธกเธนเธฅเธเนเธฒ equities เน€เธ—เธตเธขเธ GDP; percentile เธชเธนเธ = valuation risk เธชเธนเธ", buffett, False, "x"),
        ("Credit Risk Premium (Baa - 10Y)", "credit spread เธ•เนเธณเธกเธฒเธ = complacency / easy credit", baa_spread, True, "%"),
        ("High Yield OAS", "HY spread เธ•เนเธณเธกเธฒเธ = risk appetite เธชเธนเธ", series["BAMLH0A0HYM2"], True, "%"),
        ("VIX complacency", "VIX เธ•เนเธณ = complacency เธชเธนเธ", series["VIXCLS"], True, ""),
        ("Yield Curve 10Y-2Y", "curve เนเธเธเธซเธฃเธทเธญเธ•เธดเธ”เธฅเธเน€เธเธดเนเธก recession stress", curve, True, "pp"),
        ("Fed Assets YoY", "balance sheet เนเธ•เน€เธฃเนเธง = liquidity tailwind", walcl_yoy, False, "%"),
        ("Real Policy Proxy", "Fed Funds - 10Y breakeven", real_policy, False, "pp"),
    ]
    indicators = []
    for name, desc, pts, inv, unit in specs:
        latest = pts[-1]["value"] if pts else None
        prior = None
        if pts:
            cutoff = (datetime.strptime(pts[-1]["date"], "%Y-%m-%d").date() - timedelta(days=366)).isoformat()
            old = [p for p in pts if p["date"] <= cutoff]
            prior = old[-1]["value"] if old else None
        pct = percentile([p["value"] for p in pts], latest, inv)
        label, color = band(pct)
        indicators.append({"name": name, "desc": desc, "latest": latest, "date": pts[-1]["date"] if pts else None, "delta": latest - prior if latest is not None and prior is not None else None, "pct": pct, "signal": label, "color": color, "unit": unit, "spark": pts[-260:]})
    froth = round(payload.get("overall", {}).get("score") or 0)
    recession = max(0, min(100, round((100 - (macro.get("yield_curve_10y_2y") or 0) * 20 + (macro.get("hy_oas") or 0) * 4) / 2)))
    debt = round((macro.get("credit_score", 50) * 0.55) + (macro.get("sentiment_score", 50) * 0.25) + (macro.get("macro_liquidity_score", 50) * 0.20))
    chip1 = round((payload.get("overall", {}).get("theme_score", 50) * 0.55) + (payload.get("overall", {}).get("sector_score", 50) * 0.45))
    chip2 = round((macro.get("credit_score", 50) * 0.65) + (macro.get("macro_liquidity_score", 50) * 0.35))
    chip3 = round((payload.get("overall", {}).get("theme_score", 50) * 0.45) + (macro.get("sentiment_score", 50) * 0.55))
    chip = round(chip1 * 0.5 + chip2 * 0.3 + chip3 * 0.2)
    return {"indicators": indicators, "scores": {"froth": froth, "recession": recession, "debt": debt, "chip": chip, "chip1": chip1, "chip2": chip2, "chip3": chip3}}


def gauge(title, sub, score, text):
    label, color = band(score)
    deg = -90 + 180 * max(0, min(100, score)) / 100
    return f'<article class="v04-card v04-gauge-card"><h3>{html.escape(title)}</h3><p>{html.escape(sub)}</p><div class="v04-gauge"><div class="v04-gauge-arc"></div><div class="v04-needle" style="transform:rotate({deg:.1f}deg)"></div><div class="v04-score">{score}</div><div class="v04-band" style="color:{color}">{label}</div></div><b style="color:{color}">{label} ยท {score}/100</b><p>{html.escape(text)}</p></article>'


def render_macro_section(payload, macro):
    s = macro["scores"]
    rows = []
    for ind in macro["indicators"]:
        width = 0 if ind["pct"] is None else max(0, min(100, ind["pct"]))
        rows.append(f'<tr><td><strong>{html.escape(ind["name"])}</strong><div class="v04-muted">{html.escape(ind["desc"])}</div></td><td>{fmt(ind["latest"])}{html.escape(ind["unit"])}<div class="v04-muted">{html.escape(ind["date"] or "")}</div></td><td>{fmt(ind["delta"])}</td><td><div class="v04-bar"><span style="width:{width:.0f}%;background:{ind["color"]}"></span><b>{fmt(ind["pct"],0)}</b></div></td><td><span class="v04-tag" style="border-color:{ind["color"]};color:{ind["color"]}">{html.escape(ind["signal"])}</span></td><td>{mini_spark(ind["spark"])}</td></tr>')
    checks = [
        ("No price too high", "Warm", "Valuation/price heat เธขเธฑเธเธชเธนเธเธเธงเนเธฒเธเธเธ•เธดเนเธเธซเธฅเธฒเธข proxy"),
        ("FOMO / fear of being left behind", "Warm", "theme/semiconductor score เธขเธฑเธเน€เธ”เนเธ"),
        ("Eager lending / cheap risk", "Warm", "credit spread เธขเธฑเธเธชเธฐเธ—เนเธญเธ risk appetite"),
        ("Absence of skepticism / this time is different", "Warm", "AI narrative เธขเธฑเธเธ•เนเธญเธเธญเนเธฒเธเธ”เนเธงเธขเธงเธดเธเธฑเธข valuation"),
        ("Hot IPO / new-product proliferation", "Cool", "เธขเธฑเธเนเธกเนเนเธชเนเนเธ numeric score เน€เธเธฃเธฒเธฐเธ•เนเธญเธเธกเธต IPO adapter เนเธขเธ"),
    ]
    check_html = "".join(f'<div class="v04-check"><span></span><strong>{html.escape(a)}</strong><em>{html.escape(b)}</em><p>{html.escape(c)}</p></div>' for a, b, c in checks)
    return f'''
<!-- v04-macro-section:start -->
<section class="v04-dark">
  <div class="v04-head"><div><h2>Macro Monitor โ€” Froth & Cycle</h2><p>Marks temperature + Dalio cycle + Buffett valuation discipline; เนเธชเธ”เธเน€เธเนเธเธ เธฒเธฉเธฒเนเธ—เธขเธเธฃเนเธญเธกเธ—เธฑเธเธจเธฑเธเธ—เน English terms</p></div><div class="v04-asof">data as of<br><strong>{html.escape(payload.get("data_anchor",""))}</strong></div></div>
  <div class="v04-posture"><span>Suggested posture โ€” how aggressive vs defensive</span><h3>{'Lean Defensive' if s['froth'] >= 55 else 'Balanced'}</h3><p>เนเธเธเธเธตเนเธเธงเธฃเน€เธเธดเนเธก margin of safety, เนเธกเนเนเธฅเนเธฃเธฒเธเธฒ, เนเธฅเธฐเน€เธ•เธฃเธตเธขเธก cash buffer เธชเธณเธซเธฃเธฑเธเธเธฑเธเธซเธงเธฐ forced selling.</p><div class="v04-temp"><i style="left:{s['froth']}%"></i></div></div>
  <div class="v04-gauge-grid">{gauge('Froth / Bubble Gauge','Valuation ยท credit ยท liquidity ยท complacency',s['froth'],'เธชเธนเธเธเธถเนเธเนเธเธฅเธงเนเธฒ risk appetite เธฃเนเธญเธเธเธถเนเธ เนเธกเนเนเธเน timing signal')}{gauge('Recession-Risk Gauge','Yield curve ยท spread ยท policy tightness',s['recession'],'เนเธเนเธ”เธน downside protection เธกเธฒเธเธเธงเนเธฒเธ—เธณเธเธฒเธข recession เธเธธเธ”เน€เธ”เธตเธขเธง')}{gauge('Long-Term Debt Cycle','Credit stress ยท liquidity ยท real policy',s['debt'],'เธชเธฐเธ—เนเธญเธ phase เธเธญเธ debt/liquidity cycle')}</div>
  <div class="v04-card"><h3>Bubble Psychology โ€” Howard Marksโ€ Checklist</h3><p class="v04-muted">Qualitative overlay: human read, not numeric score.</p><div class="v04-check-grid">{check_html}</div></div>
  <div class="v04-card"><h3>Froth Gauge โ€” Components</h3><table class="v04-table"><thead><tr><th>Indicator</th><th>Latest</th><th>1Y ฮ”</th><th>Percentile</th><th>Signal</th><th>5Y trend</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
  <div class="v04-card v04-ai"><div>{gauge('AI Chip Bubble Risk','Semis ยท themes ยท credit ยท sentiment',s['chip'],'Composite เธเธฒเธ semiconductor/theme price heat + credit/liquidity stress')}</div><div><h3>AI / Semiconductor Cycle Monitor</h3><p>Early-warning panel: เธ–เนเธฒ Tier 1 เธขเธฑเธเนเธเนเธ เนเธ•เน Tier 2 financing stress เนเธฅเธฐ Tier 3 valuation/sentiment เธชเธนเธเธเธฃเนเธญเธกเธเธฑเธ เนเธซเนเธฅเธ”เธเธฒเธฃเนเธฅเนเธฃเธฒเธเธฒ.</p><div class="v04-tier"><b>{s['chip1']}</b><span>Tier 1 โ€” Bell-ringers</span><em>Physical-demand proxy เธเธฒเธ semiconductor/theme heat</em></div><div class="v04-tier"><b>{s['chip2']}</b><span>Tier 2 โ€” Financing & cycle stress</span><em>Credit/liquidity pressure</em></div><div class="v04-tier"><b>{s['chip3']}</b><span>Tier 3 โ€” Valuation & sentiment</span><em>Theme heat + VIX complacency</em></div></div></div>
</section>
<!-- v04-macro-section:end -->
'''


V04_CSS = '''
<!-- v04-css:start -->
.v04-dark{background:#10141d;color:#eef3fb;border:1px solid #252c3b;border-radius:8px;padding:18px;margin-top:22px}.v04-head{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid #252c3b;padding-bottom:12px}.v04-head h2{font-size:24px}.v04-head p,.v04-muted{color:#96a0b4;line-height:1.45}.v04-asof{text-align:right;color:#96a0b4;font-size:12px}.v04-posture{margin-top:14px;background:#151b27;border:1px solid #252c3b;border-radius:8px;padding:16px}.v04-posture span{text-transform:uppercase;color:#8994aa;font-size:12px;font-weight:800;letter-spacing:.08em}.v04-posture h3{margin:8px 0;color:#eba33c;font-size:25px}.v04-temp{height:16px;background:linear-gradient(90deg,#39965b 0 25%,#74b982 25% 45%,#d7b742 45% 62%,#e9912f 62% 80%,#d95445 80%);border-radius:2px;position:relative;margin-top:14px}.v04-temp i{position:absolute;top:-8px;width:4px;height:32px;background:#fff;border-radius:99px}.v04-gauge-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-top:14px}.v04-card{background:#151b27;border:1px solid #252c3b;border-radius:8px;padding:16px;margin-top:14px}.v04-card h3{margin:0 0 6px;font-size:16px}.v04-card p{margin:6px 0;color:#98a3b7}.v04-gauge{height:150px;position:relative;display:grid;place-items:center}.v04-gauge-arc{width:210px;height:105px;border-radius:210px 210px 0 0;background:linear-gradient(90deg,#39965b 0 28%,#d7b742 28% 55%,#e9912f 55% 78%,#d95445 78%);position:absolute;bottom:26px;overflow:hidden}.v04-gauge-arc:after{content:"";position:absolute;left:24px;right:24px;bottom:0;height:82px;border-radius:180px 180px 0 0;background:#151b27}.v04-needle{position:absolute;bottom:28px;width:4px;height:90px;background:#f3f6fb;border-radius:99px;transform-origin:50% 100%}.v04-score{position:absolute;bottom:44px;font-size:40px;font-weight:900}.v04-band{position:absolute;bottom:26px;font-weight:800}.v04-check-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.v04-check{display:grid;grid-template-columns:14px 1fr auto;gap:6px 8px}.v04-check span{width:10px;height:10px;background:#e9912f;border-radius:50%;margin-top:5px}.v04-check strong{font-size:14px}.v04-check em{font-style:normal;color:#e5a343;font-weight:800;font-size:12px}.v04-check p{grid-column:2/-1;margin:0;color:#98a3b7;font-size:13px}.v04-table{color:#edf3fb}.v04-table th{color:#8994aa}.v04-table td,.v04-table th{border-bottom:1px solid #252c3b}.v04-bar{height:18px;background:#0c1119;border-radius:4px;position:relative;overflow:hidden;min-width:130px}.v04-bar span{display:block;height:100%}.v04-bar b{position:absolute;right:6px;top:1px;font-size:12px;color:#eef3fb}.v04-tag{border:1px solid;border-radius:999px;padding:4px 8px;font-weight:800;font-size:12px}.v04-spark{width:120px;height:32px}.v04-spark polyline{fill:none;stroke:#87a6ff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.v04-ai{display:grid;grid-template-columns:minmax(260px,.8fr) minmax(320px,1.2fr);gap:18px}.v04-tier{display:grid;grid-template-columns:58px 1fr;gap:2px 12px;background:#111722;border:1px solid #252c3b;border-radius:8px;padding:12px;margin-top:10px}.v04-tier b{grid-row:1/3;display:grid;place-items:center;background:#2b2630;color:#f1b13e;border-radius:8px;font-size:24px}.v04-tier span{font-weight:850}.v04-tier em{font-style:normal;color:#98a3b7}@media(max-width:800px){.v04-ai{grid-template-columns:1fr}.v04-head{display:block}.v04-asof{text-align:left;margin-top:8px}.v04-table th:nth-child(3),.v04-table td:nth-child(3),.v04-table th:nth-child(6),.v04-table td:nth-child(6){display:none}}
<!-- v04-css:end -->
'''


def render_eyg_rows(rows):
    html_rows = []
    for r in rows:
        html_rows.append(f"<tr><td>{html.escape(r.get('name') or '')}<div class='row-meta'>{html.escape(r.get('symbol') or '')} - {html.escape(r.get('region') or '')}</div></td><td>{fmt(r.get('trailing_pe'))}</td><td>{fmt(r.get('forward_pe'))}</td><td>{fmt(r.get('earnings_yield'))}%</td><td>{fmt(r.get('ten_year_yield'))}%</td><td>{fmt(r.get('gap_pp'))} pp</td><td>{html.escape(r.get('status') or '')}<div class='row-meta'>Trailing: {html.escape(r.get('source') or 'n/a')}<br>Forward: {html.escape(r.get('forward_source') or 'source gap')}</div></td></tr>")
    return "\n".join(html_rows)


def render_interactive(chart_data, eyg_rows):
    data_json = json.dumps(chart_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    watch = "".join(f"<option value='{html.escape(k)}'>{html.escape(v.get('label') or k)} โ€” {html.escape(v.get('chart_symbol') or k)}</option>" for k, v in chart_data["priceSeries"].items())
    countries = "".join(f"<option value='{html.escape(c.get('country'))}'>{html.escape(c.get('label') or c.get('country'))}</option>" for c in chart_data["yieldCurves"])
    buttons = "".join(f"<button class='range-btn {'active' if k == '5Y' else ''}' data-range='{k}'>{k}</button>" for k, _ in RANGES)
    js = r'''
<script id="v03-data" type="application/json">__DATA__</script>
<script>
(()=>{const data=JSON.parse(document.getElementById('v03-data').textContent),R=data.ranges;let priceRange='5Y',yieldRange='5Y';const pad={l:48,r:18,t:18,b:34},w=900,h=320,fmt=(v,d=2)=>Number(v).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d}),timeOf=p=>new Date(p.date+'T00:00:00Z').getTime();function vis(points,range){const clean=(points||[]).filter(p=>p&&p.date);if(range==='MAX'||!R[range]||clean.length<2)return clean;const last=timeOf(clean[clean.length-1]),cut=last-R[range]*86400000;return clean.filter(p=>timeOf(p)>=cut)}function yScale(vals){const lo=Math.min(...vals),hi=Math.max(...vals),sp=hi-lo||1;return{lo,hi,fn:v=>h-pad.b-(v-lo)/sp*(h-pad.t-pad.b)}}function xScale(pts){const lo=timeOf(pts[0]),hi=timeOf(pts[pts.length-1]),sp=hi-lo||1;return p=>pad.l+(timeOf(p)-lo)/sp*(w-pad.l-pad.r)}function path(pts,x,y,key='value'){return pts.map((p,i)=>(i?'L':'M')+x(p).toFixed(1)+','+y(p[key]).toFixed(1)).join(' ')}function grid(){let s='<g class="chart-grid">';for(let i=0;i<5;i++){const yy=pad.t+i*(h-pad.t-pad.b)/4;s+=`<line x1="${pad.l}" x2="${w-pad.r}" y1="${yy}" y2="${yy}"/>`}return s+'</g>'}function pointer(svg,evt){const pt=svg.createSVGPoint();pt.x=evt.clientX;pt.y=evt.clientY;const sp=pt.matrixTransform(svg.getScreenCTM().inverse()),wr=svg.parentElement.getBoundingClientRect();return{x:sp.x,y:sp.y,px:evt.clientX-wr.left,py:evt.clientY-wr.top}}function nearest(pts,x,xfn){let b=0,d=1e9;pts.forEach((p,i)=>{const nd=Math.abs(xfn(p)-x);if(nd<d){d=nd;b=i}});return b}function tip(t,p,html){t.innerHTML=html;t.style.left=Math.max(84,Math.min(p.px,t.parentElement.clientWidth-84))+'px';t.style.top=Math.max(38,Math.min(p.py,t.parentElement.clientHeight-8))+'px';t.classList.add('visible')}function drawPrice(){const sel=document.getElementById('v03-price-select'),svg=document.getElementById('v03-price-chart'),tt=document.getElementById('v03-price-tooltip'),note=document.getElementById('v03-price-note'),item=data.priceSeries[sel.value],pts=vis(item?.points||[],priceRange).filter(p=>p.value!=null);if(!item||pts.length<2){svg.innerHTML='';note.textContent=item?`${item.label}: historical series เนเธกเนเธเธญ; ${item.note||''}`:'no data';return}const ys=yScale(pts.map(p=>p.value)),x=xScale(pts),y=ys.fn;svg.innerHTML=`${grid()}<path class="chart-line" stroke="#245f86" d="${path(pts,x,y)}"></path><g id="price-focus"></g><g class="chart-axis"><text x="${pad.l}" y="${h-10}">${pts[0].date}</text><text text-anchor="end" x="${w-pad.r}" y="${h-10}">${pts[pts.length-1].date}</text><text x="8" y="${y(ys.hi).toFixed(1)}">${fmt(ys.hi)}</text><text x="8" y="${y(ys.lo).toFixed(1)}">${fmt(ys.lo)}</text></g>`;note.textContent=`${item.label}: ${pts.length.toLocaleString()} เธเธธเธ”, ${pts[0].date} เธ–เธถเธ ${pts[pts.length-1].date}. ${item.note||''}`;const show=e=>{const p=pointer(svg,e),row=pts[nearest(pts,p.x,x)],cx=x(row),cy=y(row.value);document.getElementById('price-focus').innerHTML=`<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${h-pad.b}" stroke="#9aa8b5" stroke-dasharray="3 3"/><circle class="chart-focus" cx="${cx}" cy="${cy}" r="5"/>`;tip(tt,p,`<strong>${row.date}</strong><br>${item.chart_symbol}: ${fmt(row.value)}`)};svg.onpointermove=show;svg.onclick=show;svg.onpointerleave=()=>tt.classList.remove('visible')}function drawYield(){const sel=document.getElementById('v03-yield-select'),svg=document.getElementById('v03-yield-chart'),tt=document.getElementById('v03-yield-tooltip'),note=document.getElementById('v03-yield-note'),curve=data.yieldCurves.find(c=>c.country===sel.value),pts=vis(curve?.history||[],yieldRange);const vals=[];pts.forEach(p=>['2Y','5Y','10Y','30Y'].forEach(k=>{if(p[k]!=null)vals.push(p[k])}));if(!curve||pts.length<2||vals.length<2){svg.innerHTML='';note.textContent=curve?`${curve.label}: historical series เนเธกเนเธเธญ`:'no data';return}const ys=yScale(vals),x=xScale(pts),y=ys.fn,colors={'2Y':'#245f86','5Y':'#2a9d8f','10Y':'#d9a441','30Y':'#cf3f48'};let html=grid();['2Y','5Y','10Y','30Y'].forEach(k=>{const valid=pts.filter(p=>p[k]!=null);if(valid.length>1)html+=`<path class="chart-line" stroke="${colors[k]}" d="${path(valid,x,y,k)}"></path>`});html+=`<g id="yield-focus"></g><g class="chart-axis"><text x="${pad.l}" y="${h-10}">${pts[0].date}</text><text text-anchor="end" x="${w-pad.r}" y="${h-10}">${pts[pts.length-1].date}</text><text x="8" y="${y(ys.hi).toFixed(1)}">${fmt(ys.hi)}%</text><text x="8" y="${y(ys.lo).toFixed(1)}">${fmt(ys.lo)}%</text></g>`;svg.innerHTML=html;note.textContent=`${curve.label}: ${pts.length.toLocaleString()} เธเธธเธ”, ${pts[0].date} เธ–เธถเธ ${pts[pts.length-1].date}.`;const show=e=>{const p=pointer(svg,e),row=pts[nearest(pts,p.x,x)],cx=x(row);let f=`<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${h-pad.b}" stroke="#9aa8b5" stroke-dasharray="3 3"/>`,lines=[`<strong>${row.date}</strong>`];['2Y','5Y','10Y','30Y'].forEach(k=>{if(row[k]!=null){f+=`<circle class="chart-focus" cx="${cx}" cy="${y(row[k])}" r="4" fill="${colors[k]}"/>`;lines.push(`${k}: ${fmt(row[k])}%`)}});document.getElementById('yield-focus').innerHTML=f;tip(tt,p,lines.join('<br>'))};svg.onpointermove=show;svg.onclick=show;svg.onpointerleave=()=>tt.classList.remove('visible')}document.getElementById('v03-price-select').addEventListener('change',drawPrice);document.getElementById('v03-yield-select').addEventListener('change',drawYield);document.querySelectorAll('.range-buttons[data-chart="price"] .range-btn').forEach(b=>b.addEventListener('click',()=>{priceRange=b.dataset.range;document.querySelectorAll('.range-buttons[data-chart="price"] .range-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');drawPrice()}));document.querySelectorAll('.range-buttons[data-chart="yield"] .range-btn').forEach(b=>b.addEventListener('click',()=>{yieldRange=b.dataset.range;document.querySelectorAll('.range-buttons[data-chart="yield"] .range-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');drawYield()}));drawPrice();drawYield();})();
</script>
'''.replace("__DATA__", data_json)
    return f'''
<!-- v03-interactive-section:start -->
<section class="section v03-grid"><div class="section-title"><h2>Top Watchlist Price Charts</h2><span class="note">history เธ•เธฑเนเธเนเธ•เนเธเธต 1990 เน€เธ—เนเธฒเธ—เธตเน source เนเธซเนเนเธ”เน; hover/click เนเธเนเนเธซเนเธ•เธฃเธเน€เธกเนเธฒเธชเนเนเธฅเนเธง</span></div><div class="chart-panel"><div class="chart-toolbar"><select id="v03-price-select">{watch}</select><div class="range-buttons" data-chart="price">{buttons}</div></div><div class="interactive-chart-wrap"><svg id="v03-price-chart" class="interactive-chart" viewBox="0 0 900 320"></svg><div id="v03-price-tooltip" class="chart-tooltip"></div></div><p class="chart-note" id="v03-price-note"></p></div></section>
<section class="section v03-grid"><div class="section-title"><h2>Bond Yield Curves</h2><span class="note">US 2Y/5Y/10Y/30Y เธขเนเธญเธเธ–เธถเธ 1990; Thailand เน€เธ—เนเธฒเธ—เธตเน ThaiBMA เธกเธตเธเนเธญเธกเธนเธฅเธเธฃเธดเธ</span></div><div class="chart-panel"><div class="chart-toolbar"><select id="v03-yield-select">{countries}</select><div class="range-buttons" data-chart="yield">{buttons}</div></div><div class="interactive-chart-wrap"><svg id="v03-yield-chart" class="interactive-chart" viewBox="0 0 900 320"></svg><div id="v03-yield-tooltip" class="chart-tooltip"></div></div><div class="v03-legend"><span class="y2">2Y</span><span class="y5">5Y</span><span class="y10">10Y</span><span class="y30">30Y</span></div><p class="chart-note" id="v03-yield-note"></p></div></section>
<section class="section panel"><h2>Earnings Yield Gap</h2><p class="note">Earnings yield = 100 / Trailing P/E; gap เนเธเน Trailing P/E เน€เธ—เนเธฒเธเธฑเนเธ. Forward P/E เน€เธเนเธ context เนเธฅเธฐเน€เธ•เธดเธกเน€เธเธเธฒเธฐเธ—เธตเนเธกเธต source-backed FY1/forward value.</p><table><thead><tr><th>Index</th><th>Trailing P/E</th><th>Forward P/E</th><th>Earnings Yield</th><th>10Y Yield</th><th>Gap</th><th>Status / Source</th></tr></thead><tbody>{render_eyg_rows(eyg_rows)}</tbody></table></section>
{js}
<!-- v03-interactive-section:end -->
'''


def rebuild_eyg(payload, valuations, curves):
    def y10(region):
        for c in curves:
            if region == "US" and c.get("country") == "United States":
                return (c.get("latest") or {}).get("10Y")
            if region == "Thailand" and c.get("country") == "Thailand":
                return (c.get("latest") or {}).get("10Y")
        return None
    out = []
    for row in payload.get("earnings_yield_gap", []):
        val = valuations.get(row.get("symbol"), {})
        trailing = val.get("trailing_pe")
        ten = y10(row.get("region"))
        ey = 100 / trailing if trailing else None
        gap = ey - ten if ey is not None and ten is not None else None
        status = "เธเธณเธเธงเธ“เธเธฒเธ Trailing P/E minus local 10Y yield" if gap is not None else "เธกเธต valuation เนเธฅเนเธง เนเธ•เนเธขเธฑเธเธเธฒเธ” local 10Y yield เธซเธฃเธทเธญ forward source เธเธฒเธเธชเนเธงเธ"
        out.append({**row, "trailing_pe": trailing, "forward_pe": val.get("forward_pe"), "earnings_yield": ey, "ten_year_yield": ten, "gap_pp": gap, "source": val.get("source") or row.get("source"), "forward_source": val.get("forward_source"), "status": status})
    return out


def patch_source_manifest_table(html_text, sources):
    rows = "\n".join(f'<tr><td>{html.escape(s.get("name",""))}</td><td>{html.escape(s.get("used_for",""))}</td><td>{html.escape(s.get("publication_date",""))}</td><td><a href="{html.escape(s.get("url",""))}">source</a></td></tr>' for s in sources)
    pattern = r'(<h2>Source Manifest</h2>\s*<table>\s*<thead><tr><th>Source</th><th>Used For</th><th>Publication / Access Date</th><th>Link</th></tr></thead>\s*)<tbody>.*?</tbody>'
    return re.sub(pattern, r"\1<tbody>" + rows + "</tbody>", html_text, flags=re.S)


def main():
    v03 = load_v03()
    v03.main()
    payload_path = OUT / "data.json"
    html_path = OUT / "index.html"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    html_text = html_path.read_text(encoding="utf-8")
    curves = payload.get("yield_curves", [])
    try:
        us_curve = build_us_yield_curve_1990()
        curves = [us_curve] + [c for c in curves if c.get("country") != "United States"]
    except Exception as exc:
        add_failure_once(payload, "FRED Treasury yield curve since 1990", repr(exc))
    payload["yield_curves"] = curves
    price_series = build_price_series(payload.get("top_watchlist_v03", []), payload.get("price_histories_v03") or {})
    valuations = build_valuations(payload)
    eyg = rebuild_eyg(payload, valuations, curves)
    macro = build_macro(payload)
    payload["price_histories_v04"] = price_series
    payload["valuation_v04"] = valuations
    payload["earnings_yield_gap"] = eyg
    payload["macro_v04"] = macro
    add_source_once(payload, {"name": "Yahoo Finance chart API since 1990", "url": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", "publication_date": "Data fetched 2026-07-03", "used_for": "Top Watchlist/index price-history charts from 1990 where available."})
    add_source_once(payload, {"name": "Yahoo Finance key-statistics embedded trailingPE", "url": "https://finance.yahoo.com/quote/{symbol}/key-statistics/", "publication_date": "Data fetched 2026-07-03", "used_for": "Trailing P/E fallback for ETF/index proxy valuation rows."})
    add_source_once(payload, {"name": "State Street SPDR product pages Price/Earnings Ratio FY1", "url": "https://www.ssga.com/us/en/intermediary/etfs", "publication_date": "Data fetched 2026-07-03", "used_for": "Forward P/E / FY1 P/E where available."})
    add_source_once(payload, {"name": "iShares official product pages P/E Ratio", "url": "https://www.ishares.com/us/products", "publication_date": "Data fetched 2026-07-03", "used_for": "Portfolio P/E Ratio for iShares ETF proxies where available."})
    add_source_once(payload, {"name": "FRED macro froth indicators", "url": "https://fred.stlouisfed.org/", "publication_date": "Data fetched 2026-07-03", "used_for": "Buffett indicator proxy, credit premium, HY OAS, VIX, yield curve, Fed assets, real policy proxy."})
    add_failure_once(payload, "Forward P/E full global coverage", "Forward P/E is populated only where a source-backed FY1/forward value was found; missing values are left n/a rather than estimated.")
    add_failure_once(payload, "mai long-run price history", "Yahoo chart returned only latest mai observation; needs SETSMART/session-based adapter for long history.")
    chart_data = {"generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M local"), "ranges": {k: v for k, v in RANGES}, "yieldCurves": curves, "priceSeries": price_series, "eygRows": eyg}
    for marker in ["v04-css", "v04-macro-section", "v03-interactive-css", "v03-interactive-section"]:
        html_text = strip_marker(html_text, marker)
    html_text = html_text.replace("</style>", V04_CSS + "\n" + v03.render_v03_css() + "\n</style>", 1)
    html_text = html_text.replace("<main>", "<main>\n" + render_macro_section(payload, macro), 1)
    anchor = '<section class="section">\n      <div class="section-title">\n        <h2>Source Gaps'
    interactive = render_interactive(chart_data, eyg)
    html_text = html_text.replace(anchor, interactive + "\n" + anchor, 1) if anchor in html_text else html_text.replace("</main>", interactive + "\n</main>", 1)
    html_text = patch_source_manifest_table(html_text, payload.get("sources", []))
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "source-manifest.json").write_text(json.dumps(payload.get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "price_series": {k: len(v.get("points") or []) for k, v in price_series.items()}, "yield_curves": [(c.get("country"), len(c.get("history") or []), (c.get("history") or [{}])[0].get("date"), c.get("as_of")) for c in curves], "valuations": valuations, "html": str(html_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

