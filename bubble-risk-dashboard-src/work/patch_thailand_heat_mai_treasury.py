from __future__ import annotations

import html
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"

TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
SET_OVERVIEW = "https://www.set.or.th/en/market/index/set/overview"
MAI_OVERVIEW = "https://www.set.or.th/en/market/index/mai/overview"
RANGES = [("1M", 31), ("3M", 93), ("6M", 186), ("1Y", 366), ("5Y", 366 * 5), ("10Y", 366 * 10), ("MAX", None)]


def fmt_pct(value) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def fmt_num(value, digits: int = 2) -> str:
    return "n/a" if value is None else f"{float(value):,.{digits}f}"


def score_color(score: float | None) -> str:
    if score is None:
        return "#9aa8b5"
    if score < 45:
        return "#5aa469"
    if score < 65:
        return "#d9a441"
    if score < 80:
        return "#e07a3f"
    return "#cf3f48"


def spark_svg(points: list[dict], width: int = 128, height: int = 38) -> str:
    points = [p for p in (points or []) if p.get("value") is not None]
    if len(points) < 2:
        return '<svg class="spark" viewBox="0 0 128 38" aria-hidden="true"><circle cx="64" cy="19" r="3.5"></circle></svg>'
    vals = [float(p["value"]) for p in points]
    lo, hi = min(vals), max(vals)
    spread = hi - lo or 1.0
    coords = []
    for i, value in enumerate(vals):
        x = 1 + i * (width - 2) / max(1, len(vals) - 1)
        y = height - 2 - ((value - lo) / spread) * (height - 4)
        coords.append(f"{x:.1f},{y:.1f}")
    return f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true"><polyline points="{" ".join(coords)}"></polyline></svg>'


def parse_float(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def run_curl(url: str, timeout: int = 60) -> str:
    proc = subprocess.run(
        ["curl.exe", "-L", "--silent", "--show-error", "--max-time", str(timeout), url],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout + 10,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"curl failed for {url}")
    return proc.stdout


def fetch_treasury_year(year: int) -> tuple[list[dict], str | None]:
    xml = run_curl(TREASURY_XML_URL.format(year=year), timeout=70)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    root = ET.fromstring(xml)
    feed_updated = root.findtext("atom:updated", namespaces=ns)
    rows: list[dict] = []
    for props in root.findall(".//m:properties", ns):
        date_raw = props.findtext("d:NEW_DATE", namespaces=ns)
        if not date_raw:
            continue
        row = {
            "date": date_raw[:10],
            "2Y": parse_float(props.findtext("d:BC_2YEAR", namespaces=ns)),
            "5Y": parse_float(props.findtext("d:BC_5YEAR", namespaces=ns)),
            "10Y": parse_float(props.findtext("d:BC_10YEAR", namespaces=ns)),
            "30Y": parse_float(props.findtext("d:BC_30YEAR", namespaces=ns)),
        }
        if any(row[k] is not None for k in ("2Y", "5Y", "10Y", "30Y")):
            rows.append(row)
    rows.sort(key=lambda r: r["date"])
    return rows, feed_updated


def merge_us_treasury_latest(payload: dict) -> dict:
    rows, feed_updated = fetch_treasury_year(datetime.now().year)
    if not rows:
        return {"treasury_rows": 0, "treasury_latest": None}
    latest = rows[-1]
    curves = payload.setdefault("yield_curves", [])
    us = next((c for c in curves if c.get("country") == "United States"), None)
    if us is None:
        us = {"country": "United States", "history": []}
        curves.insert(0, us)
    by_date = {r.get("date"): r for r in us.get("history", []) if r.get("date")}
    for row in rows:
        by_date[row["date"]] = row
    history = [by_date[k] for k in sorted(by_date)]
    us.update(
        {
            "country": "United States",
            "label": "U.S. Treasury Daily Treasury Rates",
            "source": "FRED historical series plus U.S. Treasury official daily XML for current year/latest",
            "source_url": TREASURY_XML_URL.format(year=datetime.now().year),
            "as_of": latest["date"],
            "latest": {k: latest.get(k) for k in ("2Y", "5Y", "10Y", "30Y")},
            "history": history,
        }
    )
    source = {
        "name": "U.S. Treasury Daily Treasury Rates XML",
        "url": TREASURY_XML_URL.format(year=datetime.now().year),
        "publication_date": f"feed updated {feed_updated or 'n/a'}; latest observation {latest['date']}",
        "used_for": "U.S. 2Y, 5Y, 10Y, and 30Y yield curve current-year observations and latest dashboard point.",
    }
    add_source_once(payload, source)
    return {"treasury_rows": len(rows), "treasury_latest": latest["date"]}


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault("sources", [])
    key = (source.get("name"), source.get("url"))
    if not any((s.get("name"), s.get("url")) == key for s in sources):
        sources.append(source)


def add_failure_once(payload: dict, name: str, detail: str) -> None:
    gaps = payload.setdefault("source_failures", [])
    if not any(g.get("name") == name and g.get("detail") == detail for g in gaps):
        gaps.append({"name": name, "detail": detail})


def update_thailand_notes(payload: dict) -> None:
    add_source_once(
        payload,
        {
            "name": "SET Index overview",
            "url": SET_OVERVIEW,
            "publication_date": "SET page Last Update, accessed by daily dashboard refresh",
            "used_for": "SET Index latest value, daily change, and Thailand index card.",
        },
    )
    add_source_once(
        payload,
        {
            "name": "SET mai Index overview",
            "url": MAI_OVERVIEW,
            "publication_date": "SET page Last Update, accessed by daily dashboard refresh",
            "used_for": "mai Index latest value, daily change, and Thailand index card.",
        },
    )
    add_failure_once(
        payload,
        "mai historical daily index prices",
        "Official SET overview provides a live mai snapshot, but the public historical download was blocked or unavailable in this local run; the chart renders the source-backed latest point instead of fabricating history.",
    )


def compute_price_metrics(points: list[dict]) -> dict:
    points = [p for p in (points or []) if p.get("value") is not None]
    if not points:
        return {}
    latest = float(points[-1]["value"])
    ret_1y = None
    if len(points) > 252:
        base = float(points[-253]["value"])
        if base:
            ret_1y = (latest / base - 1) * 100
    ma = None
    if len(points) >= 200:
        ma = sum(float(p["value"]) for p in points[-200:]) / 200
    dist = (latest / ma - 1) * 100 if ma else None
    drawdown = None
    last_year = points[-252:] if len(points) >= 252 else points
    high = max(float(p["value"]) for p in last_year)
    if high:
        drawdown = (latest / high - 1) * 100
    return {
        "latest": latest,
        "ret_1y": ret_1y,
        "dist_200dma": dist,
        "drawdown_1y": drawdown,
        "sparkline": points[-180:],
    }


def enrich_thailand_indices(payload: dict) -> None:
    histories = payload.get("price_histories_v04") or {}
    valuations = payload.get("valuation_sources_v04") or {}
    for item in payload.get("indices", []):
        symbol = item.get("symbol")
        if symbol not in {"SET", "mai"}:
            continue
        metrics = item.setdefault("metrics", {})
        hist_metrics = compute_price_metrics((histories.get(symbol) or {}).get("points") or [])
        for key, value in hist_metrics.items():
            metrics.setdefault(key, value)
        if valuations.get(symbol, {}).get("trailing_pe") is not None:
            metrics["trailing_pe"] = valuations[symbol]["trailing_pe"]
        hist = histories.get(symbol)
        if hist:
            hist.setdefault("label", item.get("name") or symbol)
            hist.setdefault("symbol", symbol)
            hist.setdefault("source_url", item.get("source_url") or (SET_OVERVIEW if symbol == "SET" else MAI_OVERVIEW))
        if symbol == "mai" and hist:
            hist["source"] = "SET official latest snapshot; historical mai daily adapter unavailable in this run."
            hist["note"] = "Official current point only. Historical mai source gap is shown in Source Gaps; no synthetic history is used."
            hist["render_mode"] = "single-point"

    watch = payload.setdefault("top_watchlist_v03", [])
    present = {x.get("symbol") for x in watch}
    for item in payload.get("indices", []):
        if item.get("symbol") in {"SET", "mai"} and item.get("symbol") not in present:
            watch.append(
                {
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "region": item.get("region"),
                    "bucket": "Index Proxy",
                    "score": item.get("score"),
                    "as_of": item.get("as_of"),
                }
            )


def render_metric(label: str, value: str) -> str:
    return f'<div class="metric"><span>{html.escape(label)}</span><b>{html.escape(value)}</b></div>'


def render_market_tile(item: dict) -> str:
    m = item.get("metrics") or {}
    symbol = item.get("symbol") or ""
    score = item.get("score")
    if score is None:
        score = 50
    if symbol in {"SET", "mai"} and m.get("ret_1y") is None:
        metrics_html = "".join(
            [
                render_metric("Latest", fmt_num(m.get("latest"))),
                render_metric("Day change", fmt_pct(m.get("day_change_pct"))),
                render_metric("Trailing P/E", fmt_num(m.get("trailing_pe"), 2)),
            ]
        )
    else:
        metrics_html = "".join(
            [
                render_metric("1Y return", fmt_pct(m.get("ret_1y"))),
                render_metric("vs 200DMA", fmt_pct(m.get("dist_200dma"))),
                render_metric("1Y drawdown", fmt_pct(m.get("drawdown_1y"))),
            ]
        )
    title = html.escape(item.get("name") or symbol)
    meta = html.escape(f"{symbol} - {item.get('region') or 'n/a'} - {item.get('as_of') or 'n/a'}")
    return f"""
    <article class="market-tile">
      <div>
        <h3>{title}</h3>
        <div class="meta">{meta}</div>
      </div>
      <span class="score-pill" style="--pill:{score_color(float(score))}">{float(score):.0f}</span>
      {spark_svg(m.get('sparkline') or [])}
      <div class="tile-metrics">{metrics_html}</div>
    </article>"""


def patch_market_heat_grid(html_text: str, payload: dict) -> str:
    cards = "\n".join(render_market_tile(item) for item in payload.get("indices", []))
    pattern = r'(<div id="indices" class="tile-grid">)(.*?)(</div>\s*<div id="sectors" class="tile-grid hidden">)'
    replacement = r"\1" + "\n" + cards + "\n      " + r"\3"
    patched, count = re.subn(pattern, replacement, html_text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Could not locate Market, Sector And Theme Heat index grid")
    return patched


def clean_price_series(payload: dict) -> dict:
    out = {}
    for symbol, item in (payload.get("price_histories_v04") or {}).items():
        out[symbol] = {
            "label": item.get("label") or symbol,
            "symbol": symbol,
            "chart_symbol": item.get("chart_symbol") or symbol,
            "source": item.get("source") or "Yahoo Finance chart API",
            "source_url": item.get("source_url") or "",
            "note": item.get("note")
            or f"Proxy {item.get('chart_symbol') or symbol}; if the first date is after 1990, the source starts there.",
            "points": item.get("points") or [],
            "render_mode": item.get("render_mode"),
        }
    return out


def update_v03_json(html_text: str, payload: dict) -> str:
    chart_data = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M local"),
        "ranges": {key: value for key, value in RANGES},
        "yieldCurves": payload.get("yield_curves", []),
        "priceSeries": clean_price_series(payload),
        "eygRows": payload.get("earnings_yield_gap", []),
    }
    data_json = json.dumps(chart_data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    patched, count = re.subn(
        r'(<script id="v03-data" type="application/json">)(.*?)(</script>)',
        lambda m: m.group(1) + data_json + m.group(3),
        html_text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not locate v03-data script tag")
    return patched


def patch_single_point_chart_js(html_text: str) -> str:
    draw_price = r"""function drawPrice(){const sel=document.getElementById('v03-price-select'),svg=document.getElementById('v03-price-chart'),tt=document.getElementById('v03-price-tooltip'),note=document.getElementById('v03-price-note'),item=data.priceSeries[sel.value],pts=vis(item?.points||[],priceRange).filter(p=>p.value!=null);if(!item||pts.length<1){svg.innerHTML='';note.textContent=item?`${item.label}: no source-backed price point available. ${item.note||''}`:'no data';return}const single=pts.length===1,one=pts[0],span=single?Math.max(Math.abs(Number(one.value))*0.01,1):0,ys=yScale(single?[Number(one.value)-span,Number(one.value)+span]:pts.map(p=>p.value)),x=single?(()=>pad.l+(w-pad.l-pad.r)/2):xScale(pts),y=ys.fn,main=single?`<circle class="chart-focus" cx="${x(one).toFixed(1)}" cy="${y(one.value).toFixed(1)}" r="6"></circle>`:`<path class="chart-line" stroke="#245f86" d="${path(pts,x,y)}"></path>`;svg.innerHTML=`${grid()}${main}<g id="price-focus"></g><g class="chart-axis"><text x="${pad.l}" y="${h-10}">${pts[0].date}</text><text text-anchor="end" x="${w-pad.r}" y="${h-10}">${pts[pts.length-1].date}</text><text x="8" y="${y(ys.hi).toFixed(1)}">${fmt(ys.hi)}</text><text x="8" y="${y(ys.lo).toFixed(1)}">${fmt(ys.lo)}</text></g>`;note.textContent=single?`${item.label}: 1 source-backed snapshot, ${one.date}. ${item.note||''}`:`${item.label}: ${pts.length.toLocaleString()} points, ${pts[0].date} to ${pts[pts.length-1].date}. ${item.note||''}`;const show=e=>{const p=pointer(svg,e),row=single?one:pts[nearest(pts,p.x,x)],cx=x(row),cy=y(row.value);document.getElementById('price-focus').innerHTML=`<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${h-pad.b}" stroke="#9aa8b5" stroke-dasharray="3 3"/><circle class="chart-focus" cx="${cx}" cy="${cy}" r="5"/>`;tip(tt,p,`<strong>${row.date}</strong><br>${item.chart_symbol}: ${fmt(row.value)}<br>${item.source||''}`)};svg.onpointermove=show;svg.onclick=show;svg.onpointerleave=()=>tt.classList.remove('visible')}"""
    patched, count = re.subn(
        r"function drawPrice\(\)\{.*?\}function drawYield\(\)\{",
        draw_price + "function drawYield(){",
        html_text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not patch drawPrice single-point renderer")
    return patched


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    treasury_status = merge_us_treasury_latest(payload)
    update_thailand_notes(payload)
    enrich_thailand_indices(payload)
    html_text = HTML.read_text(encoding="utf-8")
    html_text = patch_market_heat_grid(html_text, payload)
    html_text = update_v03_json(html_text, payload)
    html_text = patch_single_point_chart_js(html_text)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    HTML.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", **treasury_status, "heat_has_set_mai": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
