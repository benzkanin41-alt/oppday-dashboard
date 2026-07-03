from __future__ import annotations

import csv
import html
import io
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'dashboard'
RAW = ROOT / 'work' / 'raw'
RUN_DATE = date.today()
START_20Y = RUN_DATE.replace(year=RUN_DATE.year - 20)
TENORS = ['2Y', '5Y', '10Y', '30Y']
RANGES = [('1M', 31), ('3M', 93), ('6M', 186), ('1Y', 366), ('5Y', 366 * 5)]
NASDAQ_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.nasdaq.com',
    'Referer': 'https://www.nasdaq.com/market-activity/etf/spy',
}


def request_text(url: str, accept: str = '*/*', headers: dict | None = None) -> str:
    hdr = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodexBubbleDashboard/0.3', 'Accept': accept, 'Accept-Language': 'en-US,en;q=0.9'}
    if headers:
        hdr.update(headers)
    with urlopen(Request(url, headers=hdr), timeout=45) as response:
        return response.read().decode('utf-8', errors='replace')


def parse_float(value):
    if value is None:
        return None
    text = str(value).replace('$', '').replace(',', '').replace('%', '').strip()
    if not text or text in {'-', '.', 'N/A', 'n/a'}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_date(text: str, fmt: str = '%Y-%m-%d') -> date | None:
    try:
        return datetime.strptime(text[:10], fmt).date()
    except Exception:
        return None


def visible_lines(raw: str) -> list[str]:
    text = re.sub(r'<(script|style)[^>]*>.*?</\\1>', ' ', raw, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = html.unescape(text)
    return [re.sub(r'\s+', ' ', x).strip() for x in text.splitlines() if x.strip()]


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault('sources', [])
    if not any(s.get('name') == source['name'] for s in sources):
        sources.append(source)


def add_failure_once(payload: dict, source: str, status: str) -> None:
    failures = payload.setdefault('source_failures', [])
    if not any(f.get('source') == source for f in failures):
        failures.append({'source': source, 'status': status})


def strip_marker(text: str, marker: str) -> str:
    start = f'<!-- {marker}:start -->'
    end = f'<!-- {marker}:end -->'
    while start in text and end in text:
        a = text.index(start)
        b = text.index(end, a) + len(end)
        text = text[:a] + text[b:]
    return text


def fmt_num(value, digits=2):
    return 'n/a' if value is None else f'{value:,.{digits}f}'


def fmt_pct(value, digits=2):
    return 'n/a' if value is None else f'{value:+.{digits}f}%'


def fetch_set_market_stats() -> dict:
    url = 'https://www.set.or.th/en/market/product/stock/overview'
    raw = request_text(url, 'text/html')
    (RAW / 'set').mkdir(parents=True, exist_ok=True)
    (RAW / 'set' / 'stock_overview.html').write_text(raw, encoding='utf-8')
    lines = visible_lines(raw)
    joined = ' '.join(lines)
    as_of = None
    m_asof = re.search(r'Key Market Statistics and Performance \(SET\)\s+As of (\d{2} \w{3} \d{4})', joined)
    if m_asof:
        try:
            as_of = datetime.strptime(m_asof.group(1), '%d %b %Y').date().isoformat()
        except ValueError:
            as_of = m_asof.group(1)
    result = {'source_url': url, 'as_of': as_of, 'SET': {}, 'mai': {}}
    patterns = {
        'trailing_pe': r'P/E \(times\)\s+([0-9,.]+)\s+([0-9,.]+)',
        'pbv': r'P/BV \(times\)\s+([0-9,.]+)\s+([0-9,.]+)',
        'market_yield': r'Market Yield \(\%\)\s+([0-9,.]+)\s+([0-9,.]+)',
        'eps': r'Index EPS\s+([0-9,.]+)\s+([0-9,.]+)',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, joined)
        if m:
            result['SET'][key] = parse_float(m.group(1))
            result['mai'][key] = parse_float(m.group(2))
    return result


def fred_series(series_id: str, start: date = START_20Y) -> list[dict]:
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    raw = request_text(url, 'text/csv')
    (RAW / 'fred').mkdir(parents=True, exist_ok=True)
    (RAW / 'fred' / f'{series_id}_20y.csv').write_text(raw, encoding='utf-8')
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        d = safe_date(row.get('observation_date', ''))
        val = parse_float(row.get(series_id))
        if d and d >= start and val is not None:
            rows.append({'date': d.isoformat(), 'value': val})
    return rows


def build_us_yield_curve_20y() -> dict:
    by_date: dict[str, dict] = {}
    latest = {}
    latest_dates = []
    for tenor, sid in {'2Y':'DGS2','5Y':'DGS5','10Y':'DGS10','30Y':'DGS30'}.items():
        pts = fred_series(sid)
        if pts:
            latest[tenor] = pts[-1]['value']; latest_dates.append(pts[-1]['date'])
        for p in pts:
            by_date.setdefault(p['date'], {'date': p['date']})[tenor] = p['value']
    return {'country':'United States','label':'U.S. Treasury Constant Maturity Curve','source':'FRED','source_url':'https://fred.stlouisfed.org/categories/115','as_of':max(latest_dates) if latest_dates else None,'latest':latest,'history':[by_date[k] for k in sorted(by_date)]}


def parse_thaibma_date(value) -> date | None:
    if value is None:
        return None
    text = str(value).replace('Z', '').strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            sample = text[:19] if 'T' in text else text[:10]
            return datetime.strptime(sample, fmt).date()
        except ValueError:
            pass
    return None


def row_date(row: dict) -> date | None:
    for key in ('Asof', 'AsOf', 'asOf', 'asof', 'Date', 'date', 'YieldDate', 'yieldDate'):
        if key in row:
            d = parse_thaibma_date(row.get(key))
            if d:
                return d
    return None


def tenor_value(row: dict, tenor: str):
    keys = [tenor, tenor.lower(), tenor.replace('Y', ' Yr'), tenor.replace('Y', 'Yrs'), tenor.replace('Y', '')]
    for key in keys:
        if key in row:
            return parse_float(row.get(key))
    for key, value in row.items():
        normalized = str(key).replace(' ', '').replace('.', '').upper()
        if normalized == tenor.upper():
            return parse_float(value)
    return None


def build_thai_yield_curve_20y() -> dict:
    base = 'https://www.thaibma.or.th'
    (RAW / 'thaibma').mkdir(parents=True, exist_ok=True)
    history = []
    for year in range(START_20Y.year, RUN_DATE.year + 1):
        url = f'{base}/yieldcurve/getintpttm?year={year}'
        try:
            raw = request_text(url, 'application/json')
        except Exception:
            continue
        (RAW / 'thaibma' / f'getintpttm_{year}.json').write_text(raw, encoding='utf-8')
        payload = json.loads(raw)
        rows = payload.get('data') if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = row_date(row)
            vals = {tenor: tenor_value(row, tenor) for tenor in TENORS}
            if d and d >= START_20Y and any(v is not None for v in vals.values()):
                history.append({'date': d.isoformat(), **vals})
        time.sleep(0.02)
    history.sort(key=lambda x: x['date'])
    latest = history[-1] if history else {}
    return {'country':'Thailand','label':'Thailand Government Bond Yield Curve','source':'ThaiBMA','source_url':'https://www.thaibma.or.th/EN/Market/YieldCurve/Government.aspx','as_of':latest.get('date'),'latest':{t: latest.get(t) for t in TENORS},'history':history}


def nasdaq_history_chunk(symbol: str, start: date, end: date, assetclass='etf') -> list[dict]:
    params = urlencode({'assetclass': assetclass, 'fromdate': start.isoformat(), 'todate': end.isoformat(), 'limit': '9999'})
    url = f'https://api.nasdaq.com/api/quote/{symbol}/historical?{params}'
    raw = request_text(url, 'application/json', NASDAQ_HEADERS)
    (RAW / 'nasdaq').mkdir(parents=True, exist_ok=True)
    payload = json.loads(raw)
    rows = (((payload.get('data') or {}).get('tradesTable') or {}).get('rows') or [])
    out = []
    for row in rows:
        val = parse_float(row.get('close'))
        if val is None:
            continue
        try:
            d = datetime.strptime(row.get('date'), '%m/%d/%Y').date()
        except Exception:
            continue
        out.append({'date': d.isoformat(), 'value': val})
    return sorted(out, key=lambda row: row['date'])


def nasdaq_history_20y(symbol: str, assetclass='etf') -> list[dict]:
    # Nasdaq currently caps the response at about 2,513 trading days even when a 20Y window is requested.
    # Request the full 20Y span first because it returns more history than smaller chunks in this environment.
    try:
        points = nasdaq_history_chunk(symbol, START_20Y, RUN_DATE, assetclass)
        if points:
            return points
    except Exception:
        pass
    seen = {}
    cur = START_20Y
    while cur <= RUN_DATE:
        end = min(cur + timedelta(days=365 * 4), RUN_DATE)
        try:
            for p in nasdaq_history_chunk(symbol, cur, end, assetclass):
                seen[p['date']] = p
        except Exception:
            pass
        cur = end + timedelta(days=1)
        time.sleep(0.04)
    return [seen[k] for k in sorted(seen)]

MANUAL_FORWARD_PE = {
    'SPY': {
        'forward_pe': 20.59,
        'source': 'Barrons / Dow Jones Market Data, published 2026-07-01',
        'url': 'https://www.barrons.com/livecoverage/stock-market-news-today-070126/card/the-s-p-500-is-cheaper-now-than-at-the-start-of-2026-MRZDSfrlkHg8xxAZmWD3',
    }
}


def ten_year_by_region(curves: list[dict]) -> dict:
    out = {}
    for curve in curves:
        y10 = (curve.get('latest') or {}).get('10Y')
        if curve.get('country') == 'United States':
            out['US'] = y10
        elif curve.get('country') == 'Thailand':
            out['Thailand'] = y10
    return out


def full_item_lookup(payload: dict) -> dict:
    lookup = {}
    for bucket in ('indices', 'sectors', 'themes'):
        for item in payload.get(bucket, []):
            if item.get('symbol'):
                lookup[item['symbol']] = item
    return lookup


def build_top_watchlist(payload: dict) -> list[dict]:
    lookup = full_item_lookup(payload)
    seen = set()
    rows = []
    for row in payload.get('watchlist', []):
        sym = row.get('symbol')
        item = lookup.get(sym, row)
        if sym and sym not in seen:
            rows.append(item)
            seen.add(sym)
    for sym in ('SET', 'mai'):
        item = lookup.get(sym)
        if item and sym not in seen:
            rows.append(item)
            seen.add(sym)
    return rows


def enrich_valuations(payload: dict, set_stats: dict, curves: list[dict]) -> list[dict]:
    lookup = full_item_lookup(payload)
    y10 = ten_year_by_region(curves)
    rows = []
    for item in payload.get('indices', []):
        sym = item.get('symbol')
        region = item.get('region')
        trailing = None
        forward = None
        eps = None
        source = 'Primary valuation adapter pending.'
        source_url = None
        if sym in ('SET', 'mai'):
            stats = set_stats.get(sym) or {}
            trailing = stats.get('trailing_pe')
            eps = stats.get('eps')
            source = f"SET Market Overview, as of {set_stats.get('as_of') or 'latest available'}"
            source_url = set_stats.get('source_url')
            item.setdefault('valuation', {})['trailing_pe'] = trailing
            item.setdefault('valuation', {})['forward_pe'] = None
            item['valuation']['eps'] = eps
            item['valuation']['source'] = source
            item['valuation']['source_url'] = source_url
        if sym in MANUAL_FORWARD_PE:
            forward = MANUAL_FORWARD_PE[sym]['forward_pe']
            source = (source + ' Forward P/E: ' + MANUAL_FORWARD_PE[sym]['source']) if source != 'Primary valuation adapter pending.' else MANUAL_FORWARD_PE[sym]['source']
            source_url = source_url or MANUAL_FORWARD_PE[sym]['url']
            item.setdefault('valuation', {})['forward_pe'] = forward
        else:
            forward = (item.get('valuation') or {}).get('forward_pe')
        trailing = (item.get('valuation') or {}).get('trailing_pe') if trailing is None else trailing
        earnings_yield = (100.0 / trailing) if trailing else None
        local_10y = y10.get(region)
        gap = earnings_yield - local_10y if earnings_yield is not None and local_10y is not None else None
        if trailing and local_10y is not None:
            status = 'Computed from trailing P/E minus local 10Y sovereign yield.'
        elif trailing:
            status = 'Trailing P/E available; local 10Y yield adapter pending.'
        else:
            status = 'Trailing P/E not sourced yet; gap held at n/a.'
        rows.append({'symbol': sym, 'name': item.get('name'), 'region': region, 'trailing_pe': trailing, 'forward_pe': forward, 'eps': eps, 'earnings_yield': earnings_yield, 'ten_year_yield': local_10y, 'gap_pp': gap, 'as_of': item.get('as_of'), 'source': source, 'source_url': source_url, 'status': status})
    payload['earnings_yield_gap'] = rows
    return rows


def top_watch_rows_html(rows: list[dict]) -> str:
    out = []
    for x in rows:
        m = x.get('metrics') or {}
        out.append(f"<tr><td>{html.escape(x.get('name') or '')}<div class='row-meta'>{html.escape(x.get('symbol') or '')} - {html.escape(x.get('region') or '')}</div></td><td>{html.escape(x.get('bucket') or '')}</td><td><span class='score-pill' style='--pill:#d9a441'>{float(x.get('score') or 50):.0f}</span></td><td>{fmt_pct(m.get('ret_1y'))}</td><td>{fmt_pct(m.get('dist_200dma'))}</td><td>{html.escape(x.get('as_of') or 'n/a')}</td></tr>")
    return '\n'.join(out)


def eyg_rows_html(rows: list[dict]) -> str:
    out = []
    for r in rows:
        src = f"<div class='row-meta'>{html.escape(r.get('source') or '')}</div>" if r.get('source') else ''
        out.append(f"<tr><td>{html.escape(r.get('name') or '')}<div class='row-meta'>{html.escape(r.get('symbol') or '')} - {html.escape(r.get('region') or '')}</div></td><td>{fmt_num(r.get('trailing_pe'), 2)}</td><td>{fmt_num(r.get('forward_pe'), 2)}</td><td>{fmt_num(r.get('earnings_yield'), 2)}%</td><td>{fmt_num(r.get('ten_year_yield'), 2)}%</td><td>{fmt_num(r.get('gap_pp'), 2)} pp</td><td>{html.escape(r.get('status') or '')}{src}</td></tr>")
    return '\n'.join(out)


def build_price_histories(rows: list[dict], payload: dict) -> dict:
    histories = {}
    for item in rows:
        sym = item.get('symbol')
        if not sym:
            continue
        if sym in ('SET', 'mai'):
            latest = (item.get('metrics') or {}).get('latest')
            as_of = str(item.get('as_of') or RUN_DATE.isoformat())[:10]
            histories[sym] = {'label': item.get('name'), 'symbol': sym, 'source': 'SET current snapshot; historical Excel download blocked by Incapsula in this run.', 'source_url': item.get('source_url'), 'points': [{'date': as_of, 'value': latest}] if latest else []}
            continue
        points = []
        try:
            points = nasdaq_history_20y(sym, 'etf')
        except Exception:
            points = []
        if not points:
            spark = (item.get('metrics') or {}).get('sparkline') or []
            points = [{'date': p.get('date'), 'value': p.get('value')} for p in spark if p.get('date') and p.get('value') is not None]
        histories[sym] = {'label': item.get('name'), 'symbol': sym, 'source': 'Nasdaq historical quote API' if len(points) > 180 else 'Dashboard sparkline fallback', 'source_url': item.get('source_url'), 'points': points}
    return histories


def render_v03_css() -> str:
    return '''
<!-- v03-interactive-css:start -->
    .v03-grid { display:grid; grid-template-columns: minmax(320px, 1fr); gap:14px; }
    .chart-panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:15px; }
    .chart-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin:10px 0 12px; }
    .chart-toolbar select { border:1px solid var(--line); border-radius:7px; padding:8px 10px; background:#fff; color:var(--ink); min-width:230px; }
    .range-buttons { display:flex; gap:6px; flex-wrap:wrap; }
    .range-btn { border:1px solid var(--line); background:#fff; border-radius:7px; padding:7px 10px; font-weight:750; color:var(--slate); cursor:pointer; }
    .range-btn.active { background:#245f86; color:#fff; border-color:#245f86; }
    .interactive-chart-wrap { position:relative; border:1px solid #e5ebf0; border-radius:8px; background:#fbfcfe; min-height:320px; overflow:hidden; }
    .interactive-chart { width:100%; height:320px; display:block; touch-action:none; }
    .chart-tooltip { position:absolute; pointer-events:none; opacity:0; transform:translate(-50%, -112%); background:#102333; color:#fff; padding:8px 10px; border-radius:7px; font-size:12px; line-height:1.35; min-width:150px; box-shadow:0 8px 22px rgba(16,35,51,.18); z-index:5; }
    .chart-tooltip.visible { opacity:1; }
    .chart-note { color:var(--muted); font-size:12px; margin-top:8px; line-height:1.4; }
    .v03-legend { display:flex; flex-wrap:wrap; gap:10px; color:var(--muted); font-size:12px; margin-top:8px; }
    .v03-legend span::before { content:""; display:inline-block; width:18px; height:3px; margin-right:5px; vertical-align:middle; border-radius:99px; }
    .y2::before { background:#245f86; } .y5::before { background:#2a9d8f; } .y10::before { background:#d9a441; } .y30::before { background:#cf3f48; }
    .chart-axis text { fill:#607084; font-size:11px; }
    .chart-axis line, .chart-grid line { stroke:#e5ebf0; stroke-width:1; }
    .chart-line { fill:none; stroke-width:2.2; stroke-linecap:round; stroke-linejoin:round; }
    .chart-focus { fill:#102333; stroke:#fff; stroke-width:2; }
    .row-meta { margin-top:4px; color:var(--muted); font-size:12px; }
<!-- v03-interactive-css:end -->
'''


def render_v03_section(chart_data: dict, eyg_html: str) -> str:
    data_json = json.dumps(chart_data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    watch_options = ''.join(f"<option value='{html.escape(sym)}'>{html.escape(v.get('label') or sym)}</option>" for sym, v in chart_data['priceSeries'].items())
    country_options = ''.join(f"<option value='{html.escape(c.get('country'))}'>{html.escape(c.get('label') or c.get('country'))}</option>" for c in chart_data['yieldCurves'])
    range_buttons = ''.join(f"<button class='range-btn {'active' if label == '1Y' else ''}' data-range='{label}'>{label}</button>" for label, _ in RANGES)
    return f'''
<!-- v03-interactive-section:start -->
    <section class="section v03-grid">
      <div class="section-title"><h2>Top Watchlist Price Charts</h2><span class="note">รวม SET และ mai; เลือกช่วง 1M/3M/6M/1Y/5Y และ hover/click เพื่อดูวันที่กับราคา</span></div>
      <div class="chart-panel">
        <div class="chart-toolbar"><select id="v03-price-select">{watch_options}</select><div class="range-buttons" data-chart="price">{range_buttons}</div></div>
        <div class="interactive-chart-wrap"><svg id="v03-price-chart" class="interactive-chart" viewBox="0 0 900 320"></svg><div id="v03-price-tooltip" class="chart-tooltip"></div></div>
        <p class="chart-note" id="v03-price-note"></p>
      </div>
    </section>

    <section class="section v03-grid">
      <div class="section-title"><h2>Bond Yield Curves</h2><span class="note">2Y/5Y/10Y/30Y ย้อนหลังสูงสุด 20 ปีตาม source ที่ดึงได้</span></div>
      <div class="chart-panel">
        <div class="chart-toolbar"><select id="v03-yield-select">{country_options}</select><div class="range-buttons" data-chart="yield">{range_buttons}</div></div>
        <div class="interactive-chart-wrap"><svg id="v03-yield-chart" class="interactive-chart" viewBox="0 0 900 320"></svg><div id="v03-yield-tooltip" class="chart-tooltip"></div></div>
        <div class="v03-legend"><span class="y2">2Y</span><span class="y5">5Y</span><span class="y10">10Y</span><span class="y30">30Y</span></div>
        <p class="chart-note" id="v03-yield-note"></p>
      </div>
    </section>

    <section class="section panel">
      <h2>Earnings Yield Gap</h2>
      <p class="note">นิยาม: Earnings yield = 100 / Trailing P/E และ Earnings yield gap = earnings yield - 10Y sovereign yield. Forward P/E แสดงไว้เพื่อเทียบมุมมองตลาด แต่ไม่ได้ใช้คำนวณ gap</p>
      <table><thead><tr><th>Index</th><th>Trailing P/E</th><th>Forward P/E</th><th>Earnings Yield</th><th>10Y Yield</th><th>Gap</th><th>Status</th></tr></thead><tbody>{eyg_html}</tbody></table>
    </section>

    <script id="v03-data" type="application/json">{data_json}</script>
    <script>
(function() {{
  const data = JSON.parse(document.getElementById('v03-data').textContent);
  const ranges = {{'1M':31,'3M':93,'6M':186,'1Y':366,'5Y':1826}};
  let priceRange = '1Y';
  let yieldRange = '1Y';
  const colors = {{'2Y':'#245f86','5Y':'#2a9d8f','10Y':'#d9a441','30Y':'#cf3f48'}};
  function fmt(v, d=2) {{ return v === null || v === undefined || Number.isNaN(v) ? 'n/a' : Number(v).toLocaleString(undefined, {{maximumFractionDigits:d, minimumFractionDigits:d}}); }}
  function cutoff(points, label) {{
    if (!points || !points.length) return [];
    const days = ranges[label] || 366;
    const latest = new Date(points[points.length - 1].date + 'T00:00:00');
    const cut = new Date(latest.getTime() - days * 86400000);
    return points.filter(p => new Date(p.date + 'T00:00:00') >= cut);
  }}
  function bounds(vals) {{
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (!isFinite(lo) || !isFinite(hi)) return [0, 1];
    const pad = Math.max((hi - lo) * 0.12, 0.01);
    return [lo - pad, hi + pad];
  }}
  function drawGrid(svg, w, h, pad) {{
    let s = '<g class="chart-grid">';
    for (let i=0;i<5;i++) {{ const y = pad.t + i * (h-pad.t-pad.b)/4; s += `<line x1="${{pad.l}}" x2="${{w-pad.r}}" y1="${{y}}" y2="${{y}}"/>`; }}
    s += '</g>'; return s;
  }}
  function makePath(points, xfn, yfn, valueKey='value') {{ return points.map((p,i) => `${{i?'L':'M'}}${{xfn(i).toFixed(1)}} ${{yfn(p[valueKey]).toFixed(1)}}`).join(' '); }}
  function nearestByX(points, x, pad, w) {{
    if (!points.length) return 0;
    const inner = w - pad.l - pad.r;
    const idx = Math.round((x - pad.l) / inner * (points.length - 1));
    return Math.max(0, Math.min(points.length - 1, idx));
  }}
  function pointer(svg, evt) {{ const r = svg.getBoundingClientRect(); return {{x:(evt.clientX-r.left)*900/r.width, y:(evt.clientY-r.top)*320/r.height, px:evt.clientX-r.left, py:evt.clientY-r.top}}; }}
  function drawPrice() {{
    const select = document.getElementById('v03-price-select');
    const svg = document.getElementById('v03-price-chart');
    const tip = document.getElementById('v03-price-tooltip');
    const note = document.getElementById('v03-price-note');
    const item = data.priceSeries[select.value];
    const pts = cutoff(item.points || [], priceRange).filter(p => p.value !== null && p.value !== undefined);
    const w=900,h=320,pad={{l:54,r:18,t:18,b:34}};
    if (pts.length < 2) {{ svg.innerHTML = `<text x="54" y="150" fill="#607084">Historical series not available; latest snapshot only.</text>`; note.textContent = item.source || ''; return; }}
    const vals = pts.map(p => Number(p.value));
    const [lo,hi] = bounds(vals);
    const xfn = i => pad.l + i*(w-pad.l-pad.r)/(pts.length-1);
    const yfn = v => pad.t + (hi-Number(v))/(hi-lo)*(h-pad.t-pad.b);
    let html = drawGrid(svg,w,h,pad);
    html += `<path class="chart-line" stroke="#245f86" d="${{makePath(pts,xfn,yfn)}}"></path><g id="price-focus"></g>`;
    html += `<g class="chart-axis"><text x="${{pad.l}}" y="${{h-10}}">${{pts[0].date}}</text><text text-anchor="end" x="${{w-pad.r}}" y="${{h-10}}">${{pts[pts.length-1].date}}</text><text x="8" y="${{yfn(hi).toFixed(1)}}">${{fmt(hi)}}</text><text x="8" y="${{yfn(lo).toFixed(1)}}">${{fmt(lo)}}</text></g>`;
    svg.innerHTML = html;
    note.textContent = `${{item.source || ''}} | points shown: ${{pts.length.toLocaleString()}} / stored: ${{(item.points||[]).length.toLocaleString()}}`;
    function show(evt) {{
      const p = pointer(svg, evt); const idx = nearestByX(pts, p.x, pad, w); const row = pts[idx]; const cx=xfn(idx), cy=yfn(row.value);
      document.getElementById('price-focus').innerHTML = `<line x1="${{cx}}" x2="${{cx}}" y1="${{pad.t}}" y2="${{h-pad.b}}" stroke="#9aa8b5" stroke-dasharray="3 3"/><circle class="chart-focus" cx="${{cx}}" cy="${{cy}}" r="5"/>`;
      tip.innerHTML = `<b>${{item.label}}</b><br>${{row.date}}<br>Price: ${{fmt(row.value)}}`;
      tip.style.left = `${{p.px}}px`; tip.style.top = `${{p.py}}px`; tip.classList.add('visible');
    }}
    svg.onpointermove = show; svg.onclick = show; svg.onpointerleave = () => tip.classList.remove('visible');
  }}
  function drawYield() {{
    const select = document.getElementById('v03-yield-select');
    const svg = document.getElementById('v03-yield-chart');
    const tip = document.getElementById('v03-yield-tooltip');
    const note = document.getElementById('v03-yield-note');
    const curve = data.yieldCurves.find(c => c.country === select.value) || data.yieldCurves[0];
    const pts = cutoff(curve.history || [], yieldRange);
    const w=900,h=320,pad={{l:54,r:18,t:18,b:34}};
    const vals = []; pts.forEach(p => ['2Y','5Y','10Y','30Y'].forEach(t => {{ if (p[t] !== null && p[t] !== undefined) vals.push(Number(p[t])); }}));
    if (pts.length < 2 || !vals.length) {{ svg.innerHTML = `<text x="54" y="150" fill="#607084">Yield history not available.</text>`; return; }}
    const [lo,hi] = bounds(vals);
    const xfn = i => pad.l + i*(w-pad.l-pad.r)/(pts.length-1);
    const yfn = v => pad.t + (hi-Number(v))/(hi-lo)*(h-pad.t-pad.b);
    let html = drawGrid(svg,w,h,pad);
    ['2Y','5Y','10Y','30Y'].forEach(t => {{ const valid = pts.filter(p => p[t] !== null && p[t] !== undefined); if (valid.length > 1) html += `<path class="chart-line" stroke="${{colors[t]}}" d="${{makePath(pts.filter(p => p[t] !== null && p[t] !== undefined), (i)=>pad.l+i*(w-pad.l-pad.r)/(valid.length-1), (v)=>yfn(v), t)}}"></path>`; }});
    html += `<g id="yield-focus"></g><g class="chart-axis"><text x="${{pad.l}}" y="${{h-10}}">${{pts[0].date}}</text><text text-anchor="end" x="${{w-pad.r}}" y="${{h-10}}">${{pts[pts.length-1].date}}</text><text x="8" y="${{yfn(hi).toFixed(1)}}">${{fmt(hi)}}%</text><text x="8" y="${{yfn(lo).toFixed(1)}}">${{fmt(lo)}}%</text></g>`;
    svg.innerHTML = html;
    note.textContent = `${{curve.source || ''}} | points shown: ${{pts.length.toLocaleString()}} / stored: ${{(curve.history||[]).length.toLocaleString()}}`;
    function show(evt) {{
      const p = pointer(svg, evt); const idx = nearestByX(pts, p.x, pad, w); const row = pts[idx]; const cx=xfn(idx);
      let focus = `<line x1="${{cx}}" x2="${{cx}}" y1="${{pad.t}}" y2="${{h-pad.b}}" stroke="#9aa8b5" stroke-dasharray="3 3"/>`;
      ['2Y','5Y','10Y','30Y'].forEach(t => {{ if (row[t] !== null && row[t] !== undefined) focus += `<circle class="chart-focus" cx="${{cx}}" cy="${{yfn(row[t])}}" r="4" fill="${{colors[t]}}"/>`; }});
      document.getElementById('yield-focus').innerHTML = focus;
      tip.innerHTML = `<b>${{curve.country}}</b><br>${{row.date}}<br>2Y: ${{fmt(row['2Y'])}}%<br>5Y: ${{fmt(row['5Y'])}}%<br>10Y: ${{fmt(row['10Y'])}}%<br>30Y: ${{fmt(row['30Y'])}}%`;
      tip.style.left = `${{p.px}}px`; tip.style.top = `${{p.py}}px`; tip.classList.add('visible');
    }}
    svg.onpointermove = show; svg.onclick = show; svg.onpointerleave = () => tip.classList.remove('visible');
  }}
  document.getElementById('v03-price-select').addEventListener('change', drawPrice);
  document.getElementById('v03-yield-select').addEventListener('change', drawYield);
  document.querySelectorAll('.range-buttons[data-chart="price"] .range-btn').forEach(btn => btn.addEventListener('click', () => {{ priceRange=btn.dataset.range; document.querySelectorAll('.range-buttons[data-chart="price"] .range-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); drawPrice(); }}));
  document.querySelectorAll('.range-buttons[data-chart="yield"] .range-btn').forEach(btn => btn.addEventListener('click', () => {{ yieldRange=btn.dataset.range; document.querySelectorAll('.range-buttons[data-chart="yield"] .range-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); drawYield(); }}));
  drawPrice(); drawYield();
}})();
    </script>
<!-- v03-interactive-section:end -->
'''


def source_rows_html(sources: list[dict]) -> str:
    return '\n'.join(
        f'<tr><td>{html.escape(s["name"])}</td><td>{html.escape(s["used_for"])}</td><td>{html.escape(s["publication_date"])}</td><td><a href="{html.escape(s["url"])}">source</a></td></tr>'
        for s in sources
    )


def patch_source_manifest_table(html_text: str, sources: list[dict]) -> str:
    rows = source_rows_html(sources)
    pattern = r'(<h2>Source Manifest</h2>\s*<table>\s*<thead><tr><th>Source</th><th>Used For</th><th>Publication / Access Date</th><th>Link</th></tr></thead>\s*)<tbody>.*?</tbody>'
    return re.sub(pattern, r'\1<tbody>' + rows + '</tbody>', html_text, flags=re.S)


def patch_watchlist_table(html_text: str, rows_html: str) -> str:
    pattern = r'(<h2>Top Watchlist</h2>\s*<table>\s*<thead><tr><th>Name</th><th>Bucket</th><th>Score</th><th>1Y</th><th>vs 200DMA</th><th>As of</th></tr></thead>\s*)<tbody>.*?</tbody>'
    new = re.sub(pattern, r'\1<tbody>' + rows_html + '</tbody>', html_text, flags=re.S)
    return new


def main() -> int:
    payload_path = OUT / 'data.json'
    html_path = OUT / 'index.html'
    payload = json.loads(payload_path.read_text(encoding='utf-8'))

    set_stats = fetch_set_market_stats()
    curves = []
    try:
        curves.append(build_us_yield_curve_20y())
    except Exception as exc:
        add_failure_once(payload, 'FRED Treasury yield curve 20Y', repr(exc))
    try:
        curves.append(build_thai_yield_curve_20y())
    except Exception as exc:
        add_failure_once(payload, 'ThaiBMA Government Bond Yield Curve 20Y', repr(exc))
    payload['yield_curves'] = curves

    eyg = enrich_valuations(payload, set_stats, curves)
    top_rows = build_top_watchlist(payload)
    price_histories = build_price_histories(top_rows, payload)
    payload['top_watchlist_v03'] = [{'symbol': x.get('symbol'), 'name': x.get('name'), 'region': x.get('region'), 'bucket': x.get('bucket'), 'score': x.get('score'), 'as_of': x.get('as_of')} for x in top_rows]
    payload['price_histories_v03'] = price_histories

    add_source_once(payload, {'name': 'SET Market Overview statistics', 'url': 'https://www.set.or.th/en/market/product/stock/overview', 'publication_date': f"SET market statistics as of {set_stats.get('as_of') or '2026-07-02'}; accessed 2026-07-02", 'used_for': 'SET and mai trailing P/E, P/BV, market yield, index EPS, and current market statistics.'})
    add_source_once(payload, {'name': 'Nasdaq historical quote API 20Y chunks', 'url': 'https://api.nasdaq.com/api/quote/{symbol}/historical', 'publication_date': 'Data fetched 2026-07-02', 'used_for': 'Top Watchlist ETF price-history charts with range filters.'})
    add_source_once(payload, {'name': 'Barrons / Dow Jones Market Data S&P 500 forward P/E', 'url': MANUAL_FORWARD_PE['SPY']['url'], 'publication_date': 'Published 2026-07-01; accessed 2026-07-02', 'used_for': 'Forward P/E display for S&P 500 proxy only; not used in earnings-yield-gap calculation.'})
    add_failure_once(payload, 'SET historical index Excel files', 'Official SET Table_Index.xls and Table_PE.xls links were discoverable on SET Market Statistics but direct download returned an Incapsula protection page in this run; current SET/mai stats were parsed from official SET Market Overview HTML instead.')
    add_failure_once(payload, 'Forward P/E coverage', 'Forward P/E is only populated where source-backed; earnings-yield-gap calculation uses trailing P/E only.')

    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'source-manifest.json').write_text(json.dumps(payload['sources'], ensure_ascii=False, indent=2), encoding='utf-8')

    chart_data = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M local'),
        'ranges': {k: v for k, v in RANGES},
        'yieldCurves': curves,
        'priceSeries': price_histories,
        'eygRows': eyg,
    }
    html_text = html_path.read_text(encoding='utf-8')
    for marker in ['v02-thai-rates-css', 'v02-thai-rates-section', 'v03-interactive-css', 'v03-interactive-section']:
        html_text = strip_marker(html_text, marker)
    html_text = html_text.replace('  </style>', render_v03_css() + '  </style>', 1)
    html_text = patch_watchlist_table(html_text, top_watch_rows_html(top_rows))
    anchor = '    <section class="section two-col">\n      <div class="panel">\n        <h2>Macro Snapshot</h2>'
    if anchor not in html_text:
        raise SystemExit('Macro Snapshot anchor not found')
    html_text = html_text.replace(anchor, render_v03_section(chart_data, eyg_rows_html(eyg)) + '\n' + anchor, 1)
    html_text = patch_source_manifest_table(html_text, payload['sources'])
    html_path.write_text(html_text, encoding='utf-8')

    summary = {
        'status': 'ok',
        'top_watchlist_rows': len(top_rows),
        'price_series': {k: len(v.get('points') or []) for k, v in price_histories.items()},
        'yield_curves': [(c.get('country'), len(c.get('history') or []), c.get('latest')) for c in curves],
        'set_trailing_pe': set_stats.get('SET', {}).get('trailing_pe'),
        'mai_trailing_pe': set_stats.get('mai', {}).get('trailing_pe'),
        'eyg_rows': len(eyg),
        'html': str(html_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

