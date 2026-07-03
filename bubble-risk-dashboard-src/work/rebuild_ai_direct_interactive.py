from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "outputs" / "dashboard"
DATA_PATH = DASHBOARD / "data.json"
HTML_PATH = DASHBOARD / "index.html"
MANIFEST_PATH = DASHBOARD / "source-manifest.json"


PALETTE = [
    "#70a7ff",
    "#f6b34a",
    "#70cf8d",
    "#ff6b5a",
    "#b48cff",
    "#5ed5d1",
    "#f181b7",
]


def strip_marker(text: str, name: str) -> str:
    start = f"<!-- {name}:start -->"
    end = f"<!-- {name}:end -->"
    a = text.find(start)
    b = text.find(end)
    if a == -1 or b == -1:
        return text
    return text[:a] + text[b + len(end) :]


def h(value: Any) -> str:
    return html.escape(str(value), quote=True)


def latest_value(series_map: dict[str, list[dict[str, Any]]]) -> str:
    latest: tuple[str, str, float] | None = None
    for name, points in series_map.items():
        for point in points:
            if "date" not in point or "value" not in point:
                continue
            try:
                value = float(point["value"])
            except (TypeError, ValueError):
                continue
            item = (str(point["date"]), name, value)
            if latest is None or item[0] > latest[0]:
                latest = item
    if latest is None:
        return "n/a"
    return f"{latest[1]} {latest[2]:,.2f} ({latest[0]})"


def normalize_series(
    series_map: dict[str, list[dict[str, Any]]],
    source_kind: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, (name, points) in enumerate(series_map.items()):
        clean_points = []
        for point in points:
            if "date" not in point or "value" not in point:
                continue
            try:
                value = float(point["value"])
            except (TypeError, ValueError):
                continue
            clean = {
                "date": str(point["date"]),
                "value": value,
                "source_kind": source_kind,
            }
            for field in ("source", "tag", "form", "filed", "accn", "metric"):
                if point.get(field):
                    clean[field] = point[field]
            clean_points.append(clean)
        normalized.append(
            {
                "name": name,
                "color": PALETTE[index % len(PALETTE)],
                "points": sorted(clean_points, key=lambda x: x["date"]),
            }
        )
    return normalized


def observation_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    rendered = []
    for row in rows:
        payload = html.escape(json.dumps(row, ensure_ascii=False), quote=True)
        rendered.append(
            "<tr class=\"ai-observation-row\" tabindex=\"0\" "
            f"data-ai-observation=\"{payload}\">"
            f"<td>{h(row.get('date', ''))}</td>"
            f"<td>{h(row.get('metric', 'Observation'))}</td>"
            f"<td>{h(row.get('value', ''))}</td>"
            f"<td>{h(row.get('source', ''))}</td>"
            "</tr>"
        )
    return (
        "<table class=\"ai-small-table ai-observation-table\">"
        "<thead><tr><th>Date</th><th>Metric</th><th>Value</th><th>Source</th></tr></thead>"
        "<tbody>"
        + "".join(rendered)
        + "</tbody></table>"
    )


def card_html(group: dict[str, Any]) -> str:
    series_count = sum(len(s["points"]) for s in group["series"])
    obs_count = len(group.get("observations", []))
    table = observation_rows(group.get("observations", []))
    return f"""
    <article class="ai-card" data-ai-card="{h(group['id'])}">
      <div class="ai-card-head">
        <div>
          <h3>{h(group['title'])}</h3>
          <p>{h(group['subtitle'])}</p>
        </div>
        <span class="{h(group['badge_class'])}">{h(group['badge'])}</span>
      </div>
      <div class="ai-meta-row">
        <b>Latest:</b> {h(group['latest'])}
        <span>{series_count} chart points{'; ' + str(obs_count) + ' observation rows' if obs_count else ''}</span>
      </div>
      <div class="ai-coverage">{h(group['coverage'])}</div>
      <div class="ai-interactive-chart" data-ai-chart="{h(group['id'])}">
        <svg class="ai-chart-svg" viewBox="0 0 720 300" role="img" aria-label="{h(group['title'])} 2-year chart"></svg>
        <div class="ai-tooltip" role="status"></div>
      </div>
      <div class="ai-legend" data-ai-legend="{h(group['id'])}"></div>
      <div class="ai-selected-detail" data-ai-detail="{h(group['id'])}">คลิกจุดบนกราฟเพื่อดูวันที่ ค่า และ source ของจุดนั้น</div>
      {table}
    </article>
    """


def build_model(ai: dict[str, Any]) -> dict[str, Any]:
    window_start = ai.get("lookback_start") or "2024-07-03"
    window_end = date.today().isoformat()
    groups = [
        {
            "id": "gpu-rental",
            "title": "GPU Rental Price Indexes",
            "subtitle": "NeoCloud and hyperscaler H100/B200 rental price observations.",
            "unit": "$/GPU-hour index",
            "badge": "Sparse public observations",
            "badge_class": "ai-badge-warn",
            "coverage": "2-year chart window. Public source exposes only the dated Silicon Data observations shown here; dense daily/monthly history requires licensed GPU rental data.",
            "latest": latest_value(ai["gpu_rental"]),
            "series": normalize_series(ai["gpu_rental"], "Silicon Data observation"),
            "observations": [],
        },
        {
            "id": "hbm-memory",
            "title": "HBM / Memory Supply Proxy",
            "subtitle": "Micron revenue, inventory, and capex from SEC, plus HBM sold-out observations.",
            "unit": "$B",
            "badge": "SEC quarterly plus observations",
            "badge_class": "ai-badge-ok",
            "coverage": "Full SEC quarterly points available inside the 2-year window. HBM sold-out status is source-backed observation, not a full capacity API.",
            "latest": latest_value(ai["micron"]),
            "series": normalize_series(ai["micron"], "SEC Company Facts"),
            "observations": ai.get("hbm_observations", []),
        },
        {
            "id": "cowos-packaging",
            "title": "CoWoS / Advanced Packaging",
            "subtitle": "Normalized capacity and supply-demand observations for advanced packaging.",
            "unit": "index / x",
            "badge": "Sparse source-backed index",
            "badge_class": "ai-badge-warn",
            "coverage": "2-year chart window with only sourced observations. Public sources do not provide a complete CoWoS monthly API in this workspace.",
            "latest": latest_value(ai["cowos"]),
            "series": normalize_series(ai["cowos"], "CoWoS observation index"),
            "observations": [],
        },
        {
            "id": "hyperscaler-capex",
            "title": "Hyperscaler AI Capex",
            "subtitle": "MSFT, GOOGL, META, AMZN, and ORCL capex from SEC Company Facts.",
            "unit": "$B",
            "badge": "Full SEC quarterly",
            "badge_class": "ai-badge-ok",
            "coverage": "SEC XBRL quarterly facts inside the 2-year lookback. Points are source-backed filings, not derived theme scores.",
            "latest": latest_value(ai["capex"]),
            "series": normalize_series(ai["capex"], "SEC Company Facts"),
            "observations": [],
        },
        {
            "id": "vendor-financing",
            "title": "Vendor Financing / Neocloud Leverage",
            "subtitle": "CoreWeave capex, debt, PP&E, and debt issuance from SEC, plus major financing events.",
            "unit": "$B",
            "badge": "SEC quarterly plus events",
            "badge_class": "ai-badge-ok",
            "coverage": "SEC quarterly points are complete for available CoreWeave filings in the 2-year window; financing event rows are source-backed observations.",
            "latest": latest_value(ai["coreweave"]),
            "series": normalize_series(ai["coreweave"], "SEC Company Facts"),
            "observations": ai.get("vendor_events", []),
        },
    ]
    return {
        "generated_at": ai.get("generated_at"),
        "window_start": window_start,
        "window_end": window_end,
        "groups": groups,
    }


AI_CSS = """
<!-- ai-direct-css:start -->
.ai-direct{background:#0f1520;color:#eef3fb;border:1px solid #273247;border-radius:8px;margin-top:22px;padding:18px}.ai-direct h2{font-size:24px;color:#f5f8ff;margin:0}.ai-direct>p{color:#b9c8dc;margin:8px 0 16px;line-height:1.55}.ai-note{color:#f2d18c;background:#211d12;border:1px solid #6b5222;border-radius:6px;padding:10px;margin:12px 0;line-height:1.45}.ai-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:14px 0}.ai-pill{background:#101722;border:1px solid #27364e;border-radius:8px;padding:10px}.ai-pill b{display:block;color:#fff;font-size:20px}.ai-pill span{color:#aabbd2;font-size:12px}.ai-grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px}.ai-card{background:#151d2b;border:1px solid #29364d;border-radius:8px;padding:14px;min-width:0}.ai-card-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.ai-card h3{margin:0 0 5px;color:#f4f7ff;font-size:17px}.ai-card p{margin:0;color:#b7c8df;line-height:1.4}.ai-card-head span{border-radius:999px;padding:5px 9px;font-size:12px;font-weight:800;white-space:nowrap}.ai-badge-ok{border:1px solid #62c784;color:#9be0ae;background:#102519}.ai-badge-warn{border:1px solid #d49731;color:#ffd78a;background:#2a1d0d}.ai-meta-row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#c6d6ea;font-size:12px;margin:9px 0}.ai-meta-row b{color:#f5f8ff}.ai-meta-row span{color:#92a9c4}.ai-coverage{color:#f0c36d;background:#1b1b16;border:1px solid #4b3d1e;border-radius:6px;padding:8px;margin:8px 0 10px;font-size:12px;line-height:1.4}.ai-interactive-chart{position:relative;background:#101722;border:1px solid #243048;border-radius:6px;overflow:hidden}.ai-chart-svg{display:block;width:100%;height:auto;min-height:260px}.ai-grid-line{stroke:#26364f;stroke-width:1}.ai-axis-label{fill:#9fb2ca;font-size:12px}.ai-series-line{fill:none;stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}.ai-point{cursor:pointer;stroke:#f5f8ff;stroke-width:1.6;filter:drop-shadow(0 0 4px rgba(112,167,255,.35))}.ai-point:focus{outline:none;stroke:#ffffff;stroke-width:3}.ai-hover-line{stroke:#d7e4f6;stroke-width:1;stroke-dasharray:4 4;opacity:.7;display:none}.ai-tooltip{position:absolute;display:none;max-width:300px;background:#07101c;color:#eef6ff;border:1px solid #4a5f82;border-radius:8px;padding:10px;font-size:12px;line-height:1.35;box-shadow:0 12px 30px rgba(0,0,0,.35);pointer-events:none;z-index:5}.ai-tooltip.visible{display:block}.ai-tooltip b{display:block;color:#fff;margin-bottom:3px}.ai-tooltip small{display:block;color:#9eb5d0;margin-top:5px}.ai-legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;color:#c3d1e4;font-size:12px}.ai-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.ai-selected-detail{margin-top:10px;background:#101722;border:1px solid #27364e;border-radius:6px;padding:10px;color:#cfe0f5;font-size:12px;line-height:1.45;min-height:44px}.ai-selected-detail b{color:#fff}.ai-small-table{font-size:12px;margin-top:10px;width:100%;border-collapse:collapse}.ai-small-table th,.ai-small-table td{padding:7px 8px;border-bottom:1px solid #26344a;color:#d6e3f4;text-align:left;vertical-align:top}.ai-small-table th{color:#9eb3ce}.ai-observation-row{cursor:pointer}.ai-observation-row:hover,.ai-observation-row:focus{background:#1c273a;outline:none}@media(max-width:720px){.ai-grid-cards{grid-template-columns:1fr}.ai-card-head{display:block}.ai-card-head span{display:inline-block;margin-top:8px}.ai-chart-svg{min-height:220px}}
<!-- ai-direct-css:end -->
"""


AI_JS = """
<script>
(function(){
  var dataEl = document.getElementById('ai-direct-data');
  if (!dataEl) return;
  var model = JSON.parse(dataEl.textContent);
  var NS = 'http://www.w3.org/2000/svg';
  var margin = {left: 54, right: 22, top: 22, bottom: 38};
  var width = 720;
  var height = 300;
  var domainStart = new Date(model.window_start + 'T00:00:00Z').getTime();
  var domainEnd = new Date(model.window_end + 'T00:00:00Z').getTime();

  function svgEl(name, attrs) {
    var el = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function(key){ el.setAttribute(key, attrs[key]); });
    return el;
  }

  function fmt(value, unit) {
    var digits = Math.abs(value) >= 100 ? 0 : 2;
    return Number(value).toLocaleString(undefined, {maximumFractionDigits: digits}) + (unit ? ' ' + unit : '');
  }

  function xScale(time) {
    if (domainEnd === domainStart) return margin.left;
    return margin.left + (time - domainStart) / (domainEnd - domainStart) * (width - margin.left - margin.right);
  }

  function clamp(value, lo, hi) {
    return Math.max(lo, Math.min(hi, value));
  }

  function detailHtml(point, unit) {
    var lines = [
      '<b>' + escapeHtml(point.series) + '</b>',
      'Date: ' + escapeHtml(point.date),
      'Value: ' + escapeHtml(fmt(point.value, unit))
    ];
    if (point.tag) lines.push('SEC tag: ' + escapeHtml(point.tag));
    if (point.form) lines.push('Filing: ' + escapeHtml(point.form) + (point.filed ? ' filed ' + escapeHtml(point.filed) : ''));
    if (point.accn) lines.push('Accession: ' + escapeHtml(point.accn));
    if (point.source) lines.push('Source: ' + escapeHtml(point.source));
    if (point.source_kind) lines.push('Source type: ' + escapeHtml(point.source_kind));
    return lines.join('<br>');
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function pointerInSvg(svg, event) {
    var pt = svg.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    var ctm = svg.getScreenCTM();
    if (!ctm) return null;
    return pt.matrixTransform(ctm.inverse());
  }

  function nearest(points, local) {
    var best = null;
    points.forEach(function(point){
      var dx = point.x - local.x;
      var dy = point.y - local.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (!best || dist < best.dist) best = {point: point, dist: dist};
    });
    return best;
  }

  function showTooltip(card, tooltip, svgBox, point, pin) {
    tooltip.innerHTML = detailHtml(point, card.unit) + (pin ? '<small>Click blank chart area to clear.</small>' : '<small>Click point to pin this detail.</small>');
    tooltip.classList.add('visible');
    var left = clamp(point.x + 14, 8, width - 314);
    var top = clamp(point.y - 18, 8, height - 132);
    tooltip.style.left = (left / width * svgBox.clientWidth) + 'px';
    tooltip.style.top = (top / height * svgBox.clientHeight) + 'px';
  }

  function setDetail(cardId, htmlText) {
    var detail = document.querySelector('[data-ai-detail="' + cardId + '"]');
    if (detail) detail.innerHTML = htmlText;
  }

  function drawChart(card) {
    var holder = document.querySelector('[data-ai-chart="' + card.id + '"]');
    if (!holder) return;
    var svg = holder.querySelector('svg');
    var tooltip = holder.querySelector('.ai-tooltip');
    svg.innerHTML = '';
    var values = [];
    card.series.forEach(function(series){
      series.points.forEach(function(point){
        var t = new Date(point.date + 'T00:00:00Z').getTime();
        if (t >= domainStart && t <= domainEnd) values.push(point.value);
      });
    });
    if (!values.length) return;
    var minY = Math.min.apply(null, values);
    var maxY = Math.max.apply(null, values);
    if (minY === maxY) {
      minY = minY * 0.9;
      maxY = maxY * 1.1 + 1;
    }
    var pad = (maxY - minY) * 0.14;
    minY = Math.max(0, minY - pad);
    maxY = maxY + pad;
    function yScale(value) {
      return height - margin.bottom - (value - minY) / (maxY - minY) * (height - margin.top - margin.bottom);
    }

    for (var i = 0; i <= 4; i++) {
      var y = margin.top + i * (height - margin.top - margin.bottom) / 4;
      svg.appendChild(svgEl('line', {x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: 'ai-grid-line'}));
      var labelValue = maxY - i * (maxY - minY) / 4;
      var text = svgEl('text', {x: 8, y: y + 4, class: 'ai-axis-label'});
      text.textContent = fmt(labelValue, '');
      svg.appendChild(text);
    }
    var years = [model.window_start, model.window_end];
    var midDate = new Date((domainStart + domainEnd) / 2).toISOString().slice(0, 10);
    years.splice(1, 0, midDate);
    years.forEach(function(d){
      var x = xScale(new Date(d + 'T00:00:00Z').getTime());
      var text = svgEl('text', {x: x - 28, y: height - 10, class: 'ai-axis-label'});
      text.textContent = d;
      svg.appendChild(text);
    });

    var hoverLine = svgEl('line', {x1: 0, y1: margin.top, x2: 0, y2: height - margin.bottom, class: 'ai-hover-line'});
    svg.appendChild(hoverLine);
    var allPoints = [];
    card.series.forEach(function(series){
      var points = series.points.map(function(point){
        var time = new Date(point.date + 'T00:00:00Z').getTime();
        return Object.assign({}, point, {
          series: series.name,
          color: series.color,
          time: time,
          x: xScale(time),
          y: yScale(point.value)
        });
      }).filter(function(point){ return point.time >= domainStart && point.time <= domainEnd; });
      if (points.length > 1) {
        var d = points.map(function(point, index){
          return (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
        }).join(' ');
        svg.appendChild(svgEl('path', {d: d, class: 'ai-series-line', stroke: series.color}));
      }
      points.forEach(function(point){
        allPoints.push(point);
        var circle = svgEl('circle', {cx: point.x, cy: point.y, r: 5, fill: series.color, class: 'ai-point', tabindex: '0'});
        circle.addEventListener('pointerenter', function(){
          hoverLine.setAttribute('x1', point.x);
          hoverLine.setAttribute('x2', point.x);
          hoverLine.style.display = 'block';
          showTooltip(card, tooltip, holder, point, false);
        });
        circle.addEventListener('click', function(event){
          event.stopPropagation();
          hoverLine.setAttribute('x1', point.x);
          hoverLine.setAttribute('x2', point.x);
          hoverLine.style.display = 'block';
          showTooltip(card, tooltip, holder, point, true);
          setDetail(card.id, detailHtml(point, card.unit));
        });
        circle.addEventListener('keydown', function(event){
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setDetail(card.id, detailHtml(point, card.unit));
            showTooltip(card, tooltip, holder, point, true);
          }
        });
        svg.appendChild(circle);
      });
    });
    svg.addEventListener('pointermove', function(event){
      var local = pointerInSvg(svg, event);
      if (!local) return;
      var hit = nearest(allPoints, local);
      if (hit && hit.dist < 32) {
        hoverLine.setAttribute('x1', hit.point.x);
        hoverLine.setAttribute('x2', hit.point.x);
        hoverLine.style.display = 'block';
        showTooltip(card, tooltip, holder, hit.point, false);
      }
    });
    svg.addEventListener('pointerleave', function(){
      tooltip.classList.remove('visible');
      hoverLine.style.display = 'none';
    });
    svg.addEventListener('click', function(){
      tooltip.classList.remove('visible');
      hoverLine.style.display = 'none';
      setDetail(card.id, 'คลิกจุดบนกราฟเพื่อดูวันที่ ค่า และ source ของจุดนั้น');
    });
    var legend = document.querySelector('[data-ai-legend="' + card.id + '"]');
    if (legend) {
      legend.innerHTML = card.series.map(function(series){
        return '<span><i style="background:' + series.color + '"></i>' + escapeHtml(series.name) + '</span>';
      }).join('');
    }
  }

  model.groups.forEach(drawChart);

  document.querySelectorAll('.ai-observation-row').forEach(function(row){
    row.addEventListener('click', function(){
      var obs = JSON.parse(row.getAttribute('data-ai-observation'));
      var card = row.closest('[data-ai-card]');
      var id = card ? card.getAttribute('data-ai-card') : '';
      setDetail(id, '<b>' + escapeHtml(obs.metric || 'Observation') + '</b><br>Date: ' + escapeHtml(obs.date || '') + '<br>Value: ' + escapeHtml(obs.value || '') + '<br>Source: ' + escapeHtml(obs.source || ''));
    });
  });
})();
</script>
"""


def section_html(model: dict[str, Any]) -> str:
    total_points = sum(len(s["points"]) for g in model["groups"] for s in g["series"])
    sec_groups = sum(1 for g in model["groups"] if "SEC" in g["badge"])
    sparse_groups = sum(1 for g in model["groups"] if "Sparse" in g["badge"])
    cards = "\n".join(card_html(g) for g in model["groups"])
    model_json = html.escape(json.dumps(model, ensure_ascii=False), quote=False)
    return f"""
<!-- ai-direct-section:start -->
<section class="ai-direct" id="ai-semiconductor-direct">
  <h2>AI / Semiconductor Direct Data Monitor</h2>
  <p>ส่วนนี้เป็นข้อมูลจริงแยกจาก derived score เดิม: SEC quarterly facts สำหรับ capex, debt, inventory, revenue และ source-backed observations สำหรับ GPU rental, HBM, CoWoS และ vendor financing. ทุกกราฟใช้กรอบเวลา 2 ปีเดียวกันตั้งแต่ {h(model['window_start'])} ถึง {h(model['window_end'])}.</p>
  <div class="ai-note">หลักสำคัญ: กราฟคลิกดูรายละเอียดรายจุดได้ แต่ระบบจะไม่เติมข้อมูลย้อนหลังปลอม จุดไหนมี API/filing จริงจะแสดงครบตาม source; จุดไหน public source ให้แค่ observation จะถูกระบุว่า sparse.</div>
  <div class="ai-summary">
    <div class="ai-pill"><b>{total_points}</b><span>chart points inside the 2-year window</span></div>
    <div class="ai-pill"><b>{sec_groups}</b><span>cards with SEC quarterly hard data</span></div>
    <div class="ai-pill"><b>{sparse_groups}</b><span>cards with sparse public observations</span></div>
    <div class="ai-pill"><b>{h(model.get('generated_at', 'n/a'))}</b><span>data build timestamp</span></div>
  </div>
  <div class="ai-grid-cards">
{cards}
  </div>
  <script id="ai-direct-data" type="application/json">{model_json}</script>
{AI_JS}
</section>
<!-- ai-direct-section:end -->
"""


def add_source_once(sources: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    url = entry.get("url")
    if not url or any(src.get("url") == url for src in sources):
        return
    sources.append(entry)


def update_manifest(payload: dict[str, Any]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else []
    add_source_once(
        manifest,
        {
            "name": "SEC EDGAR Company Facts API",
            "url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
            "publication_date": "SEC page published 2024-06-06; last reviewed/updated 2025-04-08; accessed 2026-07-03",
            "used_for": "Quarterly XBRL facts for hyperscaler capex, CoreWeave debt/capex/PP&E/debt issuance, and Micron revenue/inventory/capex.",
        },
    )
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["sources"] = manifest


def main() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    ai = payload.get("ai_semiconductor_direct_v06")
    if not ai:
        raise SystemExit("Missing ai_semiconductor_direct_v06 in data.json")
    model = build_model(ai)
    payload["ai_semiconductor_direct_v07"] = model
    update_manifest(payload)
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    html_text = HTML_PATH.read_text(encoding="utf-8")
    html_text = strip_marker(html_text, "ai-direct-section")
    html_text = strip_marker(html_text, "ai-direct-css")
    html_text = html_text.replace("</style>", AI_CSS + "\n</style>", 1)
    insertion = section_html(model)
    anchor = "<section class=\"sources\">"
    if anchor in html_text:
        html_text = html_text.replace(anchor, insertion + "\n" + anchor, 1)
    else:
        html_text = html_text.replace("</body>", insertion + "\n</body>", 1)
    HTML_PATH.write_text(html_text, encoding="utf-8")
    print(f"rebuilt ai direct interactive section with {len(model['groups'])} cards and v07 data")


if __name__ == "__main__":
    main()
