from __future__ import annotations

import csv
import html
import io
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'dashboard'
RAW = ROOT / 'work' / 'raw'
RUN_DATE = date.today()
TENORS = ['2Y', '5Y', '10Y', '30Y']


def request_text(url: str, accept: str = '*/*') -> str:
    req = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodexBubbleDashboard/0.2',
        'Accept': accept,
        'Accept-Language': 'en-US,en;q=0.9',
    })
    with urlopen(req, timeout=40) as response:
        return response.read().decode('utf-8', errors='replace')


def parse_float(value):
    if value is None:
        return None
    text = str(value).replace('$', '').replace(',', '').strip()
    if not text or text == '.':
        return None
    try:
        return float(text)
    except ValueError:
        return None


def visible_lines(raw: str) -> list[str]:
    text = re.sub(r'<(script|style)[^>]*>.*?</\\1>', ' ', raw, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = html.unescape(text)
    return [re.sub(r'\s+', ' ', x).strip() for x in text.splitlines() if x.strip()]


def parse_set_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%d %b %Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S Bangkok')
    except ValueError:
        return value


def fetch_set_index(slug: str, symbol: str, name: str) -> dict:
    url = f'https://www.set.or.th/en/market/index/{slug}/overview'
    raw = request_text(url, 'text/html')
    (RAW / 'set').mkdir(parents=True, exist_ok=True)
    (RAW / 'set' / f'{slug}_overview.html').write_text(raw, encoding='utf-8')
    lines = visible_lines(raw)
    marker = f'{symbol} Index Series'.lower()
    start = next((i for i, line in enumerate(lines) if line.lower() == marker), None)
    if start is None:
        start = next((i for i, line in enumerate(lines) if 'index series' in line.lower() and symbol.lower() in line.lower()), 0)
    window = lines[start:start + 80]
    joined = ' '.join(window)
    latest = None
    for i, line in enumerate(window):
        if line == 'Index':
            for candidate in window[i + 1:i + 8]:
                latest = parse_float(candidate)
                if latest is not None:
                    break
        if latest is not None:
            break
    if latest is None:
        match = re.search(r'Index\s+([0-9][0-9,]*\.\d+)', joined)
        latest = parse_float(match.group(1)) if match else None
    chg = pct = None
    m = re.search(r'([+-]?[0-9][0-9,]*\.\d+)\s*\(([+-]?[0-9]+(?:\.\d+)?)%\)', joined)
    if m:
        chg = parse_float(m.group(1)); pct = parse_float(m.group(2))
    dm = re.search(r'Last Update\s*:?[ ]*(\d{2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2})', joined)
    as_of = parse_set_datetime(dm.group(1) if dm else None) or RUN_DATE.isoformat()
    return {'symbol': symbol, 'name': name, 'region': 'Thailand', 'latest': latest, 'change': chg, 'change_pct': pct, 'as_of': as_of, 'url': url}


def fred_points(series_id: str) -> list[dict]:
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    raw = request_text(url, 'text/csv')
    (RAW / 'fred').mkdir(parents=True, exist_ok=True)
    (RAW / 'fred' / f'{series_id}.csv').write_text(raw, encoding='utf-8')
    points = []
    for row in csv.DictReader(io.StringIO(raw)):
        val = parse_float(row.get(series_id))
        if val is not None:
            points.append({'date': row['observation_date'], 'value': val})
    return points


def us_curve() -> dict:
    maps = {'2Y': 'DGS2', '5Y': 'DGS5', '10Y': 'DGS10', '30Y': 'DGS30'}
    by_date = {}
    latest = {}
    dates = []
    for tenor, sid in maps.items():
        pts = fred_points(sid)
        if pts:
            latest[tenor] = pts[-1]['value']; dates.append(pts[-1]['date'])
        for p in pts[-260:]:
            by_date.setdefault(p['date'], {'date': p['date']})[tenor] = p['value']
    return {'country': 'United States', 'label': 'U.S. Treasury Constant Maturity Curve', 'source': 'FRED', 'source_url': 'https://fred.stlouisfed.org/categories/115', 'as_of': max(dates), 'latest': latest, 'history': [by_date[k] for k in sorted(by_date)][-180:]}


def parse_date_any(value) -> date | None:
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
            d = parse_date_any(row.get(key))
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


def thai_curve() -> dict:
    base = 'https://www.thaibma.or.th'
    (RAW / 'thaibma').mkdir(parents=True, exist_ok=True)
    avail_raw = request_text(f'{base}/yieldcurve/avail', 'application/json')
    (RAW / 'thaibma' / 'avail.json').write_text(avail_raw, encoding='utf-8')
    dates = [parse_date_any(x) for x in json.loads(avail_raw)]
    dates = [d for d in dates if d]
    latest_available = max(dates) if dates else RUN_DATE
    hist_url = f'{base}/yieldcurve/getintpttm?year={latest_available.year}'
    hist_raw = request_text(hist_url, 'application/json')
    (RAW / 'thaibma' / f'getintpttm_{latest_available.year}.json').write_text(hist_raw, encoding='utf-8')
    payload = json.loads(hist_raw)
    rows = payload.get('data') if isinstance(payload, dict) else payload
    history = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = row_date(row)
        vals = {tenor: tenor_value(row, tenor) for tenor in TENORS}
        if d and any(v is not None for v in vals.values()):
            history.append({'date': d.isoformat(), **vals})
    history.sort(key=lambda x: x['date'])
    latest = history[-1]
    return {'country': 'Thailand', 'label': 'Thailand Government Bond Yield Curve', 'source': 'ThaiBMA', 'source_url': 'https://www.thaibma.or.th/EN/Market/YieldCurve/Government.aspx', 'as_of': latest['date'], 'latest': {t: latest.get(t) for t in TENORS}, 'history': history[-180:]}


def fmt_num(value, digits=1):
    return 'n/a' if value is None else f'{value:,.{digits}f}'


def fmt_pct(value, digits=1):
    return 'n/a' if value is None else f'{value:+.{digits}f}%'


def curve_svg(curve: dict, width=520, height=172) -> str:
    rows = curve.get('history') or []
    colors = {'2Y': '#245f86', '5Y': '#2a9d8f', '10Y': '#d9a441', '30Y': '#cf3f48'}
    vals = [float(row[t]) for row in rows for t in TENORS if row.get(t) is not None]
    if len(rows) < 2 or not vals:
        return '<div class="empty-chart">No historical curve data</div>'
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.12, 0.05)
    lo -= pad; hi += pad
    span = hi - lo or 1
    grid = ''.join(f'<line x1="30" x2="{width-10}" y1="{12 + i*(height-34)/3:.1f}" y2="{12 + i*(height-34)/3:.1f}" />' for i in range(4))
    lines = []
    for tenor in TENORS:
        coords = []
        for i, row in enumerate(rows):
            val = row.get(tenor)
            if val is None:
                continue
            x = 30 + i * (width - 44) / (len(rows) - 1)
            y = 12 + (height - 34) - ((float(val) - lo) / span) * (height - 34)
            coords.append(f'{x:.1f},{y:.1f}')
        if len(coords) >= 2:
            lines.append(f'<polyline points="{" ".join(coords)}" stroke="{colors[tenor]}" />')
    return f'<svg class="yield-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Yield curve history"><g class="chart-grid">{grid}</g><g class="chart-lines">{"".join(lines)}</g></svg>'


def yield_card(curve: dict) -> str:
    latest = curve.get('latest') or {}
    metrics = ''.join(f'<div class="yield-metric"><span>{t}</span><b>{fmt_num(latest.get(t), 2)}%</b></div>' for t in TENORS)
    legend = ''.join(f'<span class="legend-{t.lower()}">{t}</span>' for t in TENORS)
    return f'''
    <article class="yield-card">
      <div class="yield-head"><div><h3>{html.escape(curve.get('label', 'Yield Curve'))}</h3><p>{html.escape(curve.get('source', 'source'))} - as of {html.escape(curve.get('as_of', 'n/a'))}</p></div><a href="{html.escape(curve.get('source_url', '#'))}">source</a></div>
      <div class="yield-metrics">{metrics}</div>
      {curve_svg(curve)}
      <div class="legend">{legend}</div>
    </article>'''


def thai_tile(item: dict) -> str:
    return f'''
    <article class="market-tile thai-tile">
      <div><h3>{html.escape(item['name'])}</h3><div class="meta">{html.escape(item['symbol'])} - Thailand - {html.escape(item['as_of'])}</div></div>
      <span class="score-pill" style="--pill:#d9a441">50</span>
      <div class="tile-metrics">
        <div class="metric"><span>Latest</span><b>{fmt_num(item.get('latest'), 2)}</b></div>
        <div class="metric"><span>Day change</span><b>{fmt_num(item.get('change'), 2)} ({fmt_pct(item.get('change_pct'))})</b></div>
        <div class="metric"><span>Data mode</span><b>latest only</b></div>
      </div>
    </article>'''


def earnings_gap_rows(indices: list[dict], curves: list[dict]) -> tuple[list[dict], str]:
    y10 = {}
    for c in curves:
        if c.get('country') == 'United States':
            y10['US'] = (c.get('latest') or {}).get('10Y')
        if c.get('country') == 'Thailand':
            y10['Thailand'] = (c.get('latest') or {}).get('10Y')
    rows = []
    html_rows = []
    for item in indices:
        region = item.get('region')
        ten = y10.get(region)
        status = 'P/E not sourced from a primary adapter yet; gap is held at n/a.'
        row = {'symbol': item.get('symbol'), 'name': item.get('name'), 'region': region, 'pe': None, 'earnings_yield': None, 'ten_year_yield': ten, 'gap_pp': None, 'as_of': item.get('as_of'), 'status': status}
        rows.append(row)
        html_rows.append(f'<tr><td>{html.escape(row["name"] or "")}<div class="row-meta">{html.escape(row["symbol"] or "")} - {html.escape(region or "")}</div></td><td>n/a</td><td>n/a</td><td>{fmt_num(ten, 2)}%</td><td>n/a</td><td>{html.escape(status)}</td></tr>')
    return rows, '\n'.join(html_rows)


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


def main() -> int:
    payload_path = OUT / 'data.json'
    html_path = OUT / 'index.html'
    payload = json.loads(payload_path.read_text(encoding='utf-8'))

    thai_indices = [fetch_set_index('set', 'SET', 'SET Index'), fetch_set_index('mai', 'mai', 'mai Index')]
    thai_payload_items = []
    for item in thai_indices:
        thai_payload_items.append({
            'symbol': item['symbol'], 'name': item['name'], 'region': 'Thailand', 'bucket': 'Index Proxy',
            'as_of': item['as_of'], 'score': 50.0,
            'metrics': {'as_of': item['as_of'], 'latest': item['latest'], 'day_change': item['change'], 'day_change_pct': item['change_pct'], 'ret_1y': None, 'dist_200dma': None, 'drawdown_1y': None, 'sparkline': []},
            'source_url': item['url'], 'latest_only': True,
            'source_note': 'Official SET latest snapshot; historical and valuation adapters are pending.'
        })
    payload['indices'] = [x for x in payload.get('indices', []) if x.get('symbol') not in {'SET', 'mai'}] + thai_payload_items

    curves = []
    try:
        curves.append(us_curve())
    except Exception as exc:
        add_failure_once(payload, 'FRED Treasury yield curve', repr(exc))
    try:
        curves.append(thai_curve())
    except Exception as exc:
        add_failure_once(payload, 'ThaiBMA Government Bond Yield Curve', repr(exc))
    payload['yield_curves'] = curves
    payload['yield_curve_gaps'] = [
        {'market': 'Europe index proxies', 'country_proxy': 'Germany / euro-area sovereign curve', 'status': '2Y/5Y/10Y/30Y primary API adapter is not wired in v0.2.'},
        {'market': 'Japan index proxies', 'country_proxy': 'Japan government bond curve', 'status': '2Y/5Y/10Y/30Y primary API adapter is not wired in v0.2.'},
        {'market': 'China/HK index proxies', 'country_proxy': 'China government bond curve and HK dollar curve', 'status': '2Y/5Y/10Y/30Y primary API adapter is not wired in v0.2.'},
        {'market': 'India index proxy', 'country_proxy': 'India government securities curve', 'status': '2Y/5Y/10Y/30Y primary API adapter is not wired in v0.2.'},
        {'market': 'South Korea index proxy', 'country_proxy': 'Korea treasury bond curve', 'status': '2Y/5Y/10Y/30Y primary API adapter is not wired in v0.2.'},
        {'market': 'Global ACWI proxy', 'country_proxy': 'No single sovereign curve', 'status': 'Needs weighted regional curve design before an earnings-yield-gap score is meaningful.'},
    ]
    eyg_data, eyg_html = earnings_gap_rows(payload.get('indices', []), curves)
    payload['earnings_yield_gap'] = eyg_data

    add_source_once(payload, {'name': 'FRED U.S. Treasury 2Y/5Y/10Y/30Y constant maturity yields', 'url': 'https://fred.stlouisfed.org/categories/115', 'publication_date': 'Daily FRED Treasury series; accessed 2026-07-02', 'used_for': 'U.S. 2Y, 5Y, 10Y, and 30Y Treasury yield curve chart and latest rates.'})
    add_source_once(payload, {'name': 'SET Index overview', 'url': 'https://www.set.or.th/en/market/index/set/overview', 'publication_date': 'SET page Last Update 2026-07-02; accessed 2026-07-02', 'used_for': 'SET Index latest value and daily change snapshot.'})
    add_source_once(payload, {'name': 'SET mai Index overview', 'url': 'https://www.set.or.th/en/market/index/mai/overview', 'publication_date': 'SET page Last Update 2026-07-02; accessed 2026-07-02', 'used_for': 'mai Index latest value and daily change snapshot.'})
    add_source_once(payload, {'name': 'ThaiBMA Government Bond Yield Curve', 'url': 'https://www.thaibma.or.th/EN/Market/YieldCurve/Government.aspx', 'publication_date': 'ThaiBMA yield curve latest available 2026-07-02; accessed 2026-07-02', 'used_for': 'Thailand government bond 2Y, 5Y, 10Y, and 30Y yield curve chart and latest rates.'})
    add_failure_once(payload, 'SET historical/valuation data', 'Official overview pages provided latest SET/mai snapshots; historical prices and P/E adapter remain pending.')
    add_failure_once(payload, 'Non-US/Thailand sovereign curves', '2Y/5Y/10Y/30Y adapters for Europe, Japan, China/HK, India, and South Korea are listed as coverage gaps.')
    add_failure_once(payload, 'Earnings yield gap valuation inputs', 'P/E adapters are not yet sourced from primary index/exchange/issuer data, so gap is n/a except 10Y yield column.')

    anchors = [x.get('as_of') for x in payload.get('indices', []) if x.get('as_of')] + [c.get('as_of') for c in curves if c.get('as_of')]
    if anchors:
        payload['data_anchor'] = max(anchors)
    payload.setdefault('confidence', {})['summary'] = payload.get('confidence', {}).get('summary', '') + ' Thailand SET/mai and U.S./Thailand 2Y/5Y/10Y/30Y curves added in v0.2.'

    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'source-manifest.json').write_text(json.dumps(payload['sources'], ensure_ascii=False, indent=2), encoding='utf-8')

    html_text = html_path.read_text(encoding='utf-8')
    html_text = strip_marker(html_text, 'v02-thai-rates-css')
    html_text = strip_marker(html_text, 'v02-thai-rates-section')
    css = '''
<!-- v02-thai-rates-css:start -->
    .yield-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:12px; }
    .yield-card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; min-height:300px; }
    .yield-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    .yield-head h3 { margin:0; font-size:16px; }
    .yield-head p { margin:5px 0 0; color:var(--muted); font-size:12px; }
    .yield-head a { color:var(--blue); font-weight:700; font-size:12px; text-decoration:none; }
    .yield-metrics { display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin:12px 0 8px; }
    .yield-metric { background:#f7f9fb; border:1px solid #e5ebf0; border-radius:7px; padding:8px; }
    .yield-metric span { display:block; color:var(--muted); font-size:11px; }
    .yield-metric b { display:block; margin-top:4px; font-size:15px; }
    .yield-chart { width:100%; height:172px; }
    .chart-grid line { stroke:#e5ebf0; stroke-width:1; }
    .chart-lines polyline { fill:none; stroke-width:2.3; stroke-linecap:round; stroke-linejoin:round; }
    .legend { display:flex; gap:10px; flex-wrap:wrap; color:var(--muted); font-size:12px; }
    .legend span::before { content:""; display:inline-block; width:18px; height:3px; margin-right:5px; vertical-align:middle; border-radius:99px; }
    .legend-2y::before { background:#245f86; } .legend-5y::before { background:#2a9d8f; } .legend-10y::before { background:#d9a441; } .legend-30y::before { background:#cf3f48; }
    .row-meta { margin-top:4px; color:var(--muted); font-size:12px; }
<!-- v02-thai-rates-css:end -->
'''
    html_text = html_text.replace('  </style>', css + '  </style>', 1)
    thai_tiles = '\n'.join(thai_tile(x) for x in thai_indices)
    curve_cards = '\n'.join(yield_card(c) for c in curves)
    gaps = ''.join(f'<li><strong>{html.escape(g["market"])}</strong>: {html.escape(g["country_proxy"])} - {html.escape(g["status"])}</li>' for g in payload['yield_curve_gaps'])
    section = f'''
<!-- v02-thai-rates-section:start -->
    <section class="section">
      <div class="section-title"><h2>Thailand Dashboard And Bond Yield Curves</h2><span class="note">SET/mai official snapshot plus 2Y/5Y/10Y/30Y yield curves from FRED and ThaiBMA</span></div>
      <div class="tile-grid">{thai_tiles}</div>
    </section>
    <section class="section">
      <div class="section-title"><h2>Bond Yield Curves And Earnings Yield Gap</h2><span class="note">กราฟเส้น 2Y/5Y/10Y/30Y จาก source หลักที่ดึงได้จริงในรอบนี้</span></div>
      <div class="yield-grid">{curve_cards}</div>
    </section>
    <section class="section panel">
      <h2>Earnings Yield Gap</h2>
      <p class="note">นิยาม: Earnings yield = 100 / P/E และ Earnings yield gap = earnings yield - 10Y sovereign yield. ถ้า P/E ยังไม่มี source หลัก ระบบจะแสดง n/a แทนการเดา</p>
      <table><thead><tr><th>Index</th><th>P/E</th><th>Earnings Yield</th><th>10Y Yield</th><th>Gap</th><th>Status</th></tr></thead><tbody>{eyg_html}</tbody></table>
      <h3>Yield Coverage Gaps</h3><ul class="method-list">{gaps}</ul>
    </section>
<!-- v02-thai-rates-section:end -->
'''
    anchor = '    <section class="section two-col">\n      <div class="panel">\n        <h2>Macro Snapshot</h2>'
    if anchor not in html_text:
        raise SystemExit('Macro Snapshot anchor not found')
    html_text = html_text.replace(anchor, section + '\n' + anchor, 1)
    html_path.write_text(html_text, encoding='utf-8')
    print(json.dumps({'status': 'ok', 'thai_indices': thai_indices, 'yield_curves': len(curves), 'eyg_rows': len(eyg_data), 'html': str(html_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
