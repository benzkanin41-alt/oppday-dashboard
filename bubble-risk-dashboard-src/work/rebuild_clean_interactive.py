from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
HTML = OUT / "index.html"
DATA = OUT / "data.json"
RANGES = [("1M", 31), ("3M", 93), ("6M", 186), ("1Y", 366), ("5Y", 366 * 5), ("10Y", 366 * 10), ("MAX", None)]


def fmt(value, digits=2):
    return "n/a" if value is None else f"{value:,.{digits}f}"


def strip_marker(text: str, marker: str) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    while start in text and end in text:
        a = text.index(start)
        b = text.index(end, a) + len(end)
        text = text[:a] + text[b:]
    return text


def clean_price_series(payload: dict) -> dict:
    out = {}
    for symbol, item in (payload.get("price_histories_v04") or {}).items():
        chart_symbol = item.get("chart_symbol") or symbol
        out[symbol] = {
            "label": item.get("label") or symbol,
            "symbol": symbol,
            "chart_symbol": chart_symbol,
            "source": item.get("source") or "Yahoo Finance chart API",
            "source_url": item.get("source_url") or "",
            "note": f"Proxy {chart_symbol}; if the first date is after 1990, the source starts there.",
            "points": item.get("points") or [],
        }
    return out


def clean_eyg_rows(payload: dict) -> list[dict]:
    rows = []
    for row in payload.get("earnings_yield_gap", []):
        status = (
            "Computed from Trailing P/E minus local 10Y yield"
            if row.get("gap_pp") is not None
            else "Valuation is available, but local 10Y yield or forward source is still missing"
        )
        rows.append({**row, "status": status})
    return rows


def render_eyg_rows(rows: list[dict]) -> str:
    out = []
    for row in rows:
        out.append(
            "<tr>"
            f"<td>{html.escape(row.get('name') or '')}<div class='row-meta'>{html.escape(row.get('symbol') or '')} - {html.escape(row.get('region') or '')}</div></td>"
            f"<td>{fmt(row.get('trailing_pe'))}</td>"
            f"<td>{fmt(row.get('forward_pe'))}</td>"
            f"<td>{fmt(row.get('earnings_yield'))}%</td>"
            f"<td>{fmt(row.get('ten_year_yield'))}%</td>"
            f"<td>{fmt(row.get('gap_pp'))} pp</td>"
            f"<td>{html.escape(row.get('status') or '')}<div class='row-meta'>Trailing: {html.escape(row.get('source') or 'n/a')}<br>Forward: {html.escape(row.get('forward_source') or 'source gap')}</div></td>"
            "</tr>"
        )
    return "\n".join(out)


def render_section(chart_data: dict, eyg_rows: list[dict]) -> str:
    data_json = json.dumps(chart_data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    watch = "".join(
        f"<option value='{html.escape(symbol)}'>{html.escape(item.get('label') or symbol)} - {html.escape(item.get('chart_symbol') or symbol)}</option>"
        for symbol, item in chart_data["priceSeries"].items()
    )
    countries = "".join(
        f"<option value='{html.escape(curve.get('country') or '')}'>{html.escape(curve.get('label') or curve.get('country') or '')}</option>"
        for curve in chart_data["yieldCurves"]
    )
    buttons = "".join(
        f"<button class='range-btn {'active' if key == '5Y' else ''}' data-range='{key}'>{key}</button>"
        for key, _ in RANGES
    )
    js = r'''
<script id="v03-data" type="application/json">__DATA__</script>
<script>
(()=>{const data=JSON.parse(document.getElementById('v03-data').textContent),R=data.ranges;let priceRange='5Y',yieldRange='5Y';const pad={l:48,r:18,t:18,b:34},w=900,h=320,fmt=(v,d=2)=>Number(v).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d}),timeOf=p=>new Date(p.date+'T00:00:00Z').getTime();function vis(points,range){const clean=(points||[]).filter(p=>p&&p.date);if(range==='MAX'||!R[range]||clean.length<2)return clean;const last=timeOf(clean[clean.length-1]),cut=last-R[range]*86400000;return clean.filter(p=>timeOf(p)>=cut)}function yScale(vals){const lo=Math.min(...vals),hi=Math.max(...vals),sp=hi-lo||1;return{lo,hi,fn:v=>h-pad.b-(v-lo)/sp*(h-pad.t-pad.b)}}function xScale(pts){const lo=timeOf(pts[0]),hi=timeOf(pts[pts.length-1]),sp=hi-lo||1;return p=>pad.l+(timeOf(p)-lo)/sp*(w-pad.l-pad.r)}function path(pts,x,y,key='value'){return pts.map((p,i)=>(i?'L':'M')+x(p).toFixed(1)+','+y(p[key]).toFixed(1)).join(' ')}function grid(){let s='<g class="chart-grid">';for(let i=0;i<5;i++){const yy=pad.t+i*(h-pad.t-pad.b)/4;s+=`<line x1="${pad.l}" x2="${w-pad.r}" y1="${yy}" y2="${yy}"/>`}return s+'</g>'}function pointer(svg,evt){const pt=svg.createSVGPoint();pt.x=evt.clientX;pt.y=evt.clientY;const sp=pt.matrixTransform(svg.getScreenCTM().inverse()),wr=svg.parentElement.getBoundingClientRect();return{x:sp.x,y:sp.y,px:evt.clientX-wr.left,py:evt.clientY-wr.top}}function nearest(pts,x,xfn){let b=0,d=1e9;pts.forEach((p,i)=>{const nd=Math.abs(xfn(p)-x);if(nd<d){d=nd;b=i}});return b}function tip(t,p,html){t.innerHTML=html;t.style.left=Math.max(84,Math.min(p.px,t.parentElement.clientWidth-84))+'px';t.style.top=Math.max(38,Math.min(p.py,t.parentElement.clientHeight-8))+'px';t.classList.add('visible')}function drawPrice(){const sel=document.getElementById('v03-price-select'),svg=document.getElementById('v03-price-chart'),tt=document.getElementById('v03-price-tooltip'),note=document.getElementById('v03-price-note'),item=data.priceSeries[sel.value],pts=vis(item?.points||[],priceRange).filter(p=>p.value!=null);if(!item||pts.length<2){svg.innerHTML='';note.textContent=item?`${item.label}: not enough history. ${item.note||''}`:'no data';return}const ys=yScale(pts.map(p=>p.value)),x=xScale(pts),y=ys.fn;svg.innerHTML=`${grid()}<path class="chart-line" stroke="#245f86" d="${path(pts,x,y)}"></path><g id="price-focus"></g><g class="chart-axis"><text x="${pad.l}" y="${h-10}">${pts[0].date}</text><text text-anchor="end" x="${w-pad.r}" y="${h-10}">${pts[pts.length-1].date}</text><text x="8" y="${y(ys.hi).toFixed(1)}">${fmt(ys.hi)}</text><text x="8" y="${y(ys.lo).toFixed(1)}">${fmt(ys.lo)}</text></g>`;note.textContent=`${item.label}: ${pts.length.toLocaleString()} points, ${pts[0].date} to ${pts[pts.length-1].date}. ${item.note||''}`;const show=e=>{const p=pointer(svg,e),row=pts[nearest(pts,p.x,x)],cx=x(row),cy=y(row.value);document.getElementById('price-focus').innerHTML=`<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${h-pad.b}" stroke="#9aa8b5" stroke-dasharray="3 3"/><circle class="chart-focus" cx="${cx}" cy="${cy}" r="5"/>`;tip(tt,p,`<strong>${row.date}</strong><br>${item.chart_symbol}: ${fmt(row.value)}`)};svg.onpointermove=show;svg.onclick=show;svg.onpointerleave=()=>tt.classList.remove('visible')}function drawYield(){const sel=document.getElementById('v03-yield-select'),svg=document.getElementById('v03-yield-chart'),tt=document.getElementById('v03-yield-tooltip'),note=document.getElementById('v03-yield-note'),curve=data.yieldCurves.find(c=>c.country===sel.value),pts=vis(curve?.history||[],yieldRange);const vals=[];pts.forEach(p=>['2Y','5Y','10Y','30Y'].forEach(k=>{if(p[k]!=null)vals.push(p[k])}));if(!curve||pts.length<2||vals.length<2){svg.innerHTML='';note.textContent=curve?`${curve.label}: not enough history.`:'no data';return}const ys=yScale(vals),x=xScale(pts),y=ys.fn,colors={'2Y':'#245f86','5Y':'#2a9d8f','10Y':'#d9a441','30Y':'#cf3f48'};let html=grid();['2Y','5Y','10Y','30Y'].forEach(k=>{const valid=pts.filter(p=>p[k]!=null);if(valid.length>1)html+=`<path class="chart-line" stroke="${colors[k]}" d="${path(valid,x,y,k)}"></path>`});html+=`<g id="yield-focus"></g><g class="chart-axis"><text x="${pad.l}" y="${h-10}">${pts[0].date}</text><text text-anchor="end" x="${w-pad.r}" y="${h-10}">${pts[pts.length-1].date}</text><text x="8" y="${y(ys.hi).toFixed(1)}">${fmt(ys.hi)}%</text><text x="8" y="${y(ys.lo).toFixed(1)}">${fmt(ys.lo)}%</text></g>`;svg.innerHTML=html;note.textContent=`${curve.label}: ${pts.length.toLocaleString()} points, ${pts[0].date} to ${pts[pts.length-1].date}.`;const show=e=>{const p=pointer(svg,e),row=pts[nearest(pts,p.x,x)],cx=x(row);let f=`<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${h-pad.b}" stroke="#9aa8b5" stroke-dasharray="3 3"/>`,lines=[`<strong>${row.date}</strong>`];['2Y','5Y','10Y','30Y'].forEach(k=>{if(row[k]!=null){f+=`<circle class="chart-focus" cx="${cx}" cy="${y(row[k])}" r="4" fill="${colors[k]}"/>`;lines.push(`${k}: ${fmt(row[k])}%`)}});document.getElementById('yield-focus').innerHTML=f;tip(tt,p,lines.join('<br>'))};svg.onpointermove=show;svg.onclick=show;svg.onpointerleave=()=>tt.classList.remove('visible')}document.getElementById('v03-price-select').addEventListener('change',drawPrice);document.getElementById('v03-yield-select').addEventListener('change',drawYield);document.querySelectorAll('.range-buttons[data-chart="price"] .range-btn').forEach(b=>b.addEventListener('click',()=>{priceRange=b.dataset.range;document.querySelectorAll('.range-buttons[data-chart="price"] .range-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');drawPrice()}));document.querySelectorAll('.range-buttons[data-chart="yield"] .range-btn').forEach(b=>b.addEventListener('click',()=>{yieldRange=b.dataset.range;document.querySelectorAll('.range-buttons[data-chart="yield"] .range-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');drawYield()}));drawPrice();drawYield();})();
</script>
'''.replace("__DATA__", data_json)
    return f'''
<!-- v03-interactive-section:start -->
<section class="section v03-grid"><div class="section-title"><h2>Top Watchlist Price Charts</h2><span class="note">History from 1990 where the source supports it; hover/click uses corrected SVG pointer mapping and shows date/value.</span></div><div class="chart-panel"><div class="chart-toolbar"><select id="v03-price-select">{watch}</select><div class="range-buttons" data-chart="price">{buttons}</div></div><div class="interactive-chart-wrap"><svg id="v03-price-chart" class="interactive-chart" viewBox="0 0 900 320"></svg><div id="v03-price-tooltip" class="chart-tooltip"></div></div><p class="chart-note" id="v03-price-note"></p></div></section>
<section class="section v03-grid"><div class="section-title"><h2>Bond Yield Curves</h2><span class="note">2Y/5Y/10Y/30Y rates with 1M, 3M, 6M, 1Y, 5Y, 10Y, and MAX filters; hover/click shows the point date and values.</span></div><div class="chart-panel"><div class="chart-toolbar"><select id="v03-yield-select">{countries}</select><div class="range-buttons" data-chart="yield">{buttons}</div></div><div class="interactive-chart-wrap"><svg id="v03-yield-chart" class="interactive-chart" viewBox="0 0 900 320"></svg><div id="v03-yield-tooltip" class="chart-tooltip"></div></div><div class="v03-legend"><span class="y2">2Y</span><span class="y5">5Y</span><span class="y10">10Y</span><span class="y30">30Y</span></div><p class="chart-note" id="v03-yield-note"></p></div></section>
<section class="section panel"><h2>Earnings Yield Gap</h2><p class="note">Earnings yield = 100 / Trailing P/E. Earnings yield gap uses Trailing P/E only; Forward P/E is shown as context where source-backed data exists.</p><table><thead><tr><th>Index</th><th>Trailing P/E</th><th>Forward P/E</th><th>Earnings Yield</th><th>10Y Yield</th><th>Gap</th><th>Status / Source</th></tr></thead><tbody>{render_eyg_rows(eyg_rows)}</tbody></table></section>
{js}
<!-- v03-interactive-section:end -->
'''


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    price_series = clean_price_series(payload)
    eyg_rows = clean_eyg_rows(payload)
    chart_data = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M local"),
        "ranges": {key: value for key, value in RANGES},
        "yieldCurves": payload.get("yield_curves", []),
        "priceSeries": price_series,
        "eygRows": eyg_rows,
    }
    html_text = HTML.read_text(encoding="utf-8")
    html_text = strip_marker(html_text, "v03-interactive-section")
    section = render_section(chart_data, eyg_rows)
    anchor = '<section class="section">\n      <div class="section-title">\n        <h2>Source Gaps'
    if anchor in html_text:
        html_text = html_text.replace(anchor, section + "\n" + anchor, 1)
    else:
        html_text = html_text.replace("</main>", section + "\n</main>", 1)
    HTML.write_text(html_text, encoding="utf-8")
    print("clean interactive section rebuilt")


if __name__ == "__main__":
    main()
