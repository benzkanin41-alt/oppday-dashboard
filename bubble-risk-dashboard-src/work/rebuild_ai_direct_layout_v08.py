from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "outputs" / "dashboard"
DATA_PATH = DASHBOARD / "data.json"
HTML_PATH = DASHBOARD / "index.html"
MANIFEST_PATH = DASHBOARD / "source-manifest.json"

DEFAULT_DETAIL = "\u0e0a\u0e35\u0e49\u0e08\u0e38\u0e14\u0e1a\u0e19\u0e01\u0e23\u0e32\u0e1f\u0e2b\u0e23\u0e37\u0e2d\u0e04\u0e25\u0e34\u0e01\u0e08\u0e38\u0e14 \u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e14\u0e39\u0e27\u0e31\u0e19\u0e17\u0e35\u0e48 \u0e04\u0e48\u0e32 \u0e41\u0e25\u0e30 source \u0e02\u0e2d\u0e07\u0e08\u0e38\u0e14\u0e19\u0e31\u0e49\u0e19"
RESET_DETAIL = DEFAULT_DETAIL

PALETTE = [
    "#70a7ff",
    "#f6b34a",
    "#70cf8d",
    "#ff6b5a",
    "#b48cff",
    "#5ed5d1",
    "#f181b7",
]


def now_bangkok() -> str:
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S Bangkok")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S local")


def strip_marker(text: str, name: str) -> str:
    start = f"<!-- {name}:start -->"
    end = f"<!-- {name}:end -->"
    a = text.find(start)
    b = text.find(end)
    if a == -1 or b == -1:
        return text
    return text[:a] + text[b + len(end) :]


def esc(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def safe_script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def add_source_failure(payload: dict[str, Any], source: str, status: str) -> None:
    failures = payload.setdefault("source_failures", [])
    for item in failures:
        if item.get("source") == source:
            item["status"] = status
            return
    failures.append({"source": source, "status": status})


def add_source_once(sources: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    url = entry.get("url")
    if not url or any(src.get("url") == url for src in sources):
        return
    sources.append(entry)


def latest_value(series_map: dict[str, list[dict[str, Any]]]) -> str:
    latest: tuple[str, str, float] | None = None
    for name, points in series_map.items():
        for point in points:
            try:
                item = (str(point["date"]), name, float(point["value"]))
            except (KeyError, TypeError, ValueError):
                continue
            if latest is None or item[0] > latest[0]:
                latest = item
    if not latest:
        return "n/a"
    return f"{latest[1]} {latest[2]:,.2f} ({latest[0]})"


def normalize_series(series_map: dict[str, list[dict[str, Any]]], source_kind: str) -> list[dict[str, Any]]:
    series_list: list[dict[str, Any]] = []
    for index, (name, points) in enumerate(series_map.items()):
        clean_points = []
        for point in points:
            try:
                clean = {
                    "date": str(point["date"]),
                    "value": float(point["value"]),
                    "source_kind": source_kind,
                }
            except (KeyError, TypeError, ValueError):
                continue
            for field in ("source", "tag", "form", "filed", "accn", "metric"):
                if point.get(field):
                    clean[field] = point[field]
            clean_points.append(clean)
        series_list.append(
            {
                "name": name,
                "color": PALETTE[index % len(PALETTE)],
                "points": sorted(clean_points, key=lambda x: x["date"]),
            }
        )
    return series_list


def observation_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    rendered = []
    for row in rows:
        payload = esc(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        rendered.append(
            f'<tr class="ai-observation-row" tabindex="0" data-ai-observation="{payload}">'
            f"<td>{esc(row.get('date', ''))}</td>"
            f"<td>{esc(row.get('metric', 'Observation'))}</td>"
            f"<td>{esc(row.get('value', ''))}</td>"
            f"<td>{esc(row.get('source', ''))}</td>"
            "</tr>"
        )
    return (
        '<table class="ai-small-table ai-observation-table">'
        "<thead><tr><th>Date</th><th>Metric</th><th>Value</th><th>Source</th></tr></thead>"
        "<tbody>"
        + "".join(rendered)
        + "</tbody></table>"
    )


def card_html(group: dict[str, Any]) -> str:
    series_count = sum(len(series["points"]) for series in group["series"])
    obs_count = len(group.get("observations", []))
    obs_suffix = f"; {obs_count} observation rows" if obs_count else ""
    return f"""
    <article class="ai-card" data-ai-card="{esc(group['id'])}">
      <div class="ai-card-head">
        <div>
          <h3>{esc(group['title'])}</h3>
          <p>{esc(group['subtitle'])}</p>
        </div>
        <span class="{esc(group['badge_class'])}">{esc(group['badge'])}</span>
      </div>
      <div class="ai-meta-row">
        <b>Latest:</b> {esc(group['latest'])}
        <span>{series_count} chart points{obs_suffix}</span>
      </div>
      <div class="ai-coverage">{esc(group['coverage'])}</div>
      <div class="ai-interactive-chart" data-ai-chart="{esc(group['id'])}">
        <svg class="ai-chart-svg" viewBox="0 0 720 360" role="img" aria-label="{esc(group['title'])} 2-year chart"></svg>
      </div>
      <div class="ai-legend" data-ai-legend="{esc(group['id'])}"></div>
      <div class="ai-selected-detail" data-ai-detail="{esc(group['id'])}">{esc(DEFAULT_DETAIL)}</div>
      {observation_rows(group.get("observations", []))}
    </article>
    """


def gpu_observations(ai: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for series_name, points in ai.get("gpu_rental", {}).items():
        for point in points:
            rows.append(
                {
                    "date": point.get("date", ""),
                    "metric": series_name,
                    "value": point.get("value", ""),
                    "source": point.get("source", ""),
                }
            )
    return sorted(rows, key=lambda x: (x["date"], x["metric"]))


def cowos_observations(ai: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for series_name, points in ai.get("cowos", {}).items():
        for point in points:
            rows.append(
                {
                    "date": point.get("date", ""),
                    "metric": series_name,
                    "value": point.get("value", ""),
                    "source": point.get("source", ""),
                }
            )
    return sorted(rows, key=lambda x: (x["date"], x["metric"]))


def build_model(ai: dict[str, Any]) -> dict[str, Any]:
    window_start = ai.get("lookback_start") or "2024-07-03"
    window_end = datetime.now().date().isoformat()
    groups = [
        {
            "id": "gpu-rental",
            "title": "GPU Rental Price Indexes",
            "subtitle": "NeoCloud and hyperscaler H100/B200 rental price observations.",
            "unit": "$/GPU-hour index",
            "badge": "Sparse public observations",
            "badge_class": "ai-badge-warn",
            "coverage": "2-year window is shown in full. Public data has only dated Silicon Data / provider observations; no complete daily or monthly history was found in open sources.",
            "latest": latest_value(ai["gpu_rental"]),
            "series": normalize_series(ai["gpu_rental"], "GPU rental observation"),
            "observations": gpu_observations(ai),
            "sparse": True,
        },
        {
            "id": "hbm-memory",
            "title": "HBM / Memory Supply Proxy",
            "subtitle": "Micron revenue, inventory, and capex from SEC, plus HBM sold-out observations.",
            "unit": "$B",
            "badge": "SEC quarterly plus observations",
            "badge_class": "ai-badge-ok",
            "coverage": "SEC quarterly points are stored inside the 2-year window. HBM status remains source-backed observation, not a full capacity API.",
            "latest": latest_value(ai["micron"]),
            "series": normalize_series(ai["micron"], "SEC Company Facts"),
            "observations": ai.get("hbm_observations", []),
            "sparse": False,
        },
        {
            "id": "cowos-packaging",
            "title": "CoWoS / Advanced Packaging",
            "subtitle": "Normalized capacity and supply-demand observations for advanced packaging.",
            "unit": "index / x",
            "badge": "Sparse source-backed index",
            "badge_class": "ai-badge-warn",
            "coverage": "2-year window is shown in full. Public sources give dated CoWoS capacity and demand/capacity observations, not a complete monthly API.",
            "latest": latest_value(ai["cowos"]),
            "series": normalize_series(ai["cowos"], "CoWoS observation index"),
            "observations": cowos_observations(ai),
            "sparse": True,
        },
        {
            "id": "hyperscaler-capex",
            "title": "Hyperscaler AI Capex",
            "subtitle": "MSFT, GOOGL, META, AMZN, and ORCL capex from SEC Company Facts.",
            "unit": "$B",
            "badge": "Full SEC quarterly",
            "badge_class": "ai-badge-ok",
            "coverage": "Quarterly SEC XBRL facts are stored and clickable inside the 2-year lookback.",
            "latest": latest_value(ai["capex"]),
            "series": normalize_series(ai["capex"], "SEC Company Facts"),
            "observations": [],
            "sparse": False,
        },
        {
            "id": "vendor-financing",
            "title": "Vendor Financing / Neocloud Leverage",
            "subtitle": "CoreWeave capex, debt, PP&E, and debt issuance from SEC, plus major financing events.",
            "unit": "$B",
            "badge": "SEC quarterly plus events",
            "badge_class": "ai-badge-ok",
            "coverage": "CoreWeave SEC quarterly points are stored where filings exist; financing events are preserved as clickable source-backed rows.",
            "latest": latest_value(ai["coreweave"]),
            "series": normalize_series(ai["coreweave"], "SEC Company Facts"),
            "observations": ai.get("vendor_events", []),
            "sparse": False,
        },
    ]
    return {
        "generated_at": now_bangkok(),
        "data_source_generated_at": ai.get("generated_at"),
        "window_start": window_start,
        "window_end": window_end,
        "groups": groups,
        "notes": [
            "Hover or click a point; details appear below the chart and do not cover the graph.",
            "GPU rental and CoWoS are sparse because open sources do not provide dense historical APIs in this workspace.",
        ],
    }


AI_CSS = """
<!-- ai-direct-css:start -->
.ai-direct{background:#0f1520;color:#eef3fb;border:1px solid #273247;border-radius:8px;margin-top:14px;margin-bottom:64px;padding:18px 18px 28px;clear:both}.ai-direct h2{font-size:24px;color:#f5f8ff;margin:0}.ai-direct>p{color:#b9c8dc;margin:8px 0 16px;line-height:1.55}.ai-note{color:#f2d18c;background:#211d12;border:1px solid #6b5222;border-radius:6px;padding:10px;margin:12px 0;line-height:1.45}.ai-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:14px 0}.ai-pill{background:#101722;border:1px solid #27364e;border-radius:8px;padding:10px}.ai-pill b{display:block;color:#fff;font-size:20px}.ai-pill span{color:#aabbd2;font-size:12px}.ai-grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px;align-items:start;margin-bottom:24px}.ai-card{background:#151d2b;border:1px solid #29364d;border-radius:8px;padding:14px;min-width:0}.ai-card-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.ai-card h3{margin:0 0 5px;color:#f4f7ff;font-size:17px}.ai-card p{margin:0;color:#b7c8df;line-height:1.4}.ai-card-head span{border-radius:999px;padding:5px 9px;font-size:12px;font-weight:800;white-space:nowrap}.ai-badge-ok{border:1px solid #62c784;color:#9be0ae;background:#102519}.ai-badge-warn{border:1px solid #d49731;color:#ffd78a;background:#2a1d0d}.ai-meta-row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#c6d6ea;font-size:12px;margin:9px 0}.ai-meta-row b{color:#f5f8ff}.ai-meta-row span{color:#92a9c4}.ai-coverage{color:#f0c36d;background:#1b1b16;border:1px solid #4b3d1e;border-radius:6px;padding:8px;margin:8px 0 10px;font-size:12px;line-height:1.4}.ai-interactive-chart{position:relative;background:#101722;border:1px solid #243048;border-radius:6px;overflow:hidden}.ai-chart-svg{display:block;width:100%;height:auto;min-height:310px}.ai-grid-line{stroke:#26364f;stroke-width:1}.ai-axis-label{fill:#9fb2ca;font-size:12px}.ai-series-line{fill:none;stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}.ai-point{cursor:pointer;stroke:#f5f8ff;stroke-width:1.6;filter:drop-shadow(0 0 4px rgba(112,167,255,.35))}.ai-point:focus{outline:none;stroke:#fff;stroke-width:3}.ai-hover-line{stroke:#d7e4f6;stroke-width:1;stroke-dasharray:4 4;opacity:.65;display:none}.ai-window-rail{stroke:#607089;stroke-width:3;stroke-linecap:round;opacity:.85}.ai-window-tick{stroke:#9fb2ca;stroke-width:1.4}.ai-window-dot{stroke:#101722;stroke-width:1.4}.ai-window-label{fill:#9fb2ca;font-size:11px}.ai-no-data-band{fill:#182234;opacity:.8}.ai-no-data-label{fill:#f0c36d;font-size:12px}.ai-legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;color:#c3d1e4;font-size:12px}.ai-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.ai-selected-detail{margin-top:10px;background:#101722;border:1px solid #27364e;border-radius:6px;padding:10px;color:#cfe0f5;font-size:12px;line-height:1.45;min-height:44px}.ai-selected-detail b{color:#fff}.ai-small-table{font-size:12px;margin-top:10px;width:100%;border-collapse:collapse}.ai-small-table th,.ai-small-table td{padding:7px 8px;border-bottom:1px solid #26344a;color:#d6e3f4;text-align:left;vertical-align:top}.ai-small-table th{color:#9eb3ce}.ai-observation-row{cursor:pointer}.ai-observation-row:hover,.ai-observation-row:focus{background:#1c273a;outline:none}@media(max-width:720px){.ai-grid-cards{grid-template-columns:1fr}.ai-card-head{display:block}.ai-card-head span{display:inline-block;margin-top:8px}.ai-chart-svg{min-height:240px}}
<!-- ai-direct-css:end -->
"""


AI_JS = f"""
<script>
(function(){{
  var dataEl = document.getElementById('ai-direct-data');
  if (!dataEl) return;
  var model = JSON.parse(dataEl.textContent);
  var NS = 'http://www.w3.org/2000/svg';
  var margin = {{left: 54, right: 22, top: 22, bottom: 70}};
  var width = 720;
  var height = 360;
  var resetDetail = {json.dumps(RESET_DETAIL, ensure_ascii=False)};
  var domainStart = new Date(model.window_start + 'T00:00:00Z').getTime();
  var domainEnd = new Date(model.window_end + 'T00:00:00Z').getTime();

  function svgEl(name, attrs) {{
    var el = document.createElementNS(NS, name);
    Object.keys(attrs || {{}}).forEach(function(key){{ el.setAttribute(key, attrs[key]); }});
    return el;
  }}
  function fmt(value, unit) {{
    var digits = Math.abs(value) >= 100 ? 0 : 2;
    return Number(value).toLocaleString(undefined, {{maximumFractionDigits: digits}}) + (unit ? ' ' + unit : '');
  }}
  function xScale(time) {{
    if (domainEnd === domainStart) return margin.left;
    return margin.left + (time - domainStart) / (domainEnd - domainStart) * (width - margin.left - margin.right);
  }}
  function escapeHtml(value) {{
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }}
  function pointerInSvg(svg, event) {{
    var pt = svg.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    var ctm = svg.getScreenCTM();
    return ctm ? pt.matrixTransform(ctm.inverse()) : null;
  }}
  function nearest(points, local) {{
    var best = null;
    points.forEach(function(point){{
      var dx = point.x - local.x;
      var dy = point.y - local.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (!best || dist < best.dist) best = {{point: point, dist: dist}};
    }});
    return best;
  }}
  function setDetail(cardId, htmlText) {{
    var detail = document.querySelector('[data-ai-detail="' + cardId + '"]');
    if (detail) detail.innerHTML = htmlText;
  }}
  function detailHtml(point, unit) {{
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
  }}
  function showPoint(card, point, hoverLine) {{
    hoverLine.setAttribute('x1', point.x);
    hoverLine.setAttribute('x2', point.x);
    hoverLine.style.display = 'block';
    setDetail(card.id, detailHtml(point, card.unit));
  }}
  function drawCoverageRail(svg, card, allPoints) {{
    var railY = height - 48;
    svg.appendChild(svgEl('line', {{x1: margin.left, y1: railY, x2: width - margin.right, y2: railY, class: 'ai-window-rail'}}));
    [model.window_start, model.window_end].forEach(function(d, idx){{
      var x = idx ? width - margin.right : margin.left;
      svg.appendChild(svgEl('line', {{x1: x, y1: railY - 8, x2: x, y2: railY + 8, class: 'ai-window-tick'}}));
      var t = svgEl('text', {{x: idx ? x - 66 : x, y: height - 14, class: 'ai-window-label'}});
      t.textContent = d;
      svg.appendChild(t);
    }});
    var label = svgEl('text', {{x: margin.left, y: railY - 12, class: card.sparse ? 'ai-no-data-label' : 'ai-window-label'}});
    label.textContent = card.sparse ? '2-year window: public data is sparse; dots are the sourced observations found' : '2-year data window';
    svg.appendChild(label);
    allPoints.forEach(function(point){{
      svg.appendChild(svgEl('circle', {{cx: point.x, cy: railY, r: 3.5, fill: point.color, class: 'ai-window-dot'}}));
    }});
  }}
  function drawChart(card) {{
    var holder = document.querySelector('[data-ai-chart="' + card.id + '"]');
    if (!holder) return;
    var svg = holder.querySelector('svg');
    svg.innerHTML = '';
    var values = [];
    card.series.forEach(function(series){{
      series.points.forEach(function(point){{
        var t = new Date(point.date + 'T00:00:00Z').getTime();
        if (t >= domainStart && t <= domainEnd) values.push(point.value);
      }});
    }});
    if (!values.length) return;
    var minY = Math.min.apply(null, values);
    var maxY = Math.max.apply(null, values);
    if (minY === maxY) {{ minY = minY * 0.9; maxY = maxY * 1.1 + 1; }}
    var pad = (maxY - minY) * 0.14;
    minY = Math.max(0, minY - pad);
    maxY = maxY + pad;
    function yScale(value) {{
      return height - margin.bottom - (value - minY) / (maxY - minY) * (height - margin.top - margin.bottom);
    }}
    for (var i = 0; i <= 4; i++) {{
      var y = margin.top + i * (height - margin.top - margin.bottom) / 4;
      svg.appendChild(svgEl('line', {{x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: 'ai-grid-line'}}));
      var labelValue = maxY - i * (maxY - minY) / 4;
      var text = svgEl('text', {{x: 8, y: y + 4, class: 'ai-axis-label'}});
      text.textContent = fmt(labelValue, '');
      svg.appendChild(text);
    }}
    var midDate = new Date((domainStart + domainEnd) / 2).toISOString().slice(0, 10);
    [model.window_start, midDate, model.window_end].forEach(function(d){{
      var x = xScale(new Date(d + 'T00:00:00Z').getTime());
      var text = svgEl('text', {{x: x - 28, y: height - 55, class: 'ai-axis-label'}});
      text.textContent = d;
      svg.appendChild(text);
    }});
    var hoverLine = svgEl('line', {{x1: 0, y1: margin.top, x2: 0, y2: height - margin.bottom, class: 'ai-hover-line'}});
    svg.appendChild(hoverLine);
    var allPoints = [];
    card.series.forEach(function(series){{
      var points = series.points.map(function(point){{
        var time = new Date(point.date + 'T00:00:00Z').getTime();
        return Object.assign({{}}, point, {{
          series: series.name,
          color: series.color,
          time: time,
          x: xScale(time),
          y: yScale(point.value)
        }});
      }}).filter(function(point){{ return point.time >= domainStart && point.time <= domainEnd; }});
      if (points.length > 1) {{
        var d = points.map(function(point, index){{
          return (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
        }}).join(' ');
        svg.appendChild(svgEl('path', {{d: d, class: 'ai-series-line', stroke: series.color}}));
      }}
      points.forEach(function(point){{
        allPoints.push(point);
        var circle = svgEl('circle', {{cx: point.x, cy: point.y, r: 5.5, fill: series.color, class: 'ai-point', tabindex: '0'}});
        circle.addEventListener('pointerenter', function(){{ showPoint(card, point, hoverLine); }});
        circle.addEventListener('click', function(event){{ event.stopPropagation(); showPoint(card, point, hoverLine); }});
        circle.addEventListener('keydown', function(event){{
          if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); showPoint(card, point, hoverLine); }}
        }});
        svg.appendChild(circle);
      }});
    }});
    drawCoverageRail(svg, card, allPoints);
    svg.addEventListener('pointermove', function(event){{
      var local = pointerInSvg(svg, event);
      if (!local) return;
      var hit = nearest(allPoints, local);
      if (hit && hit.dist < 32) showPoint(card, hit.point, hoverLine);
    }});
    svg.addEventListener('pointerleave', function(){{ hoverLine.style.display = 'none'; }});
    svg.addEventListener('click', function(){{ hoverLine.style.display = 'none'; setDetail(card.id, resetDetail); }});
    var legend = document.querySelector('[data-ai-legend="' + card.id + '"]');
    if (legend) {{
      legend.innerHTML = card.series.map(function(series){{
        return '<span><i style="background:' + series.color + '"></i>' + escapeHtml(series.name) + '</span>';
      }}).join('');
    }}
  }}
  model.groups.forEach(drawChart);
  document.querySelectorAll('.ai-observation-row').forEach(function(row){{
    row.addEventListener('click', function(){{
      var obs = JSON.parse(row.getAttribute('data-ai-observation'));
      var card = row.closest('[data-ai-card]');
      var id = card ? card.getAttribute('data-ai-card') : '';
      setDetail(id, '<b>' + escapeHtml(obs.metric || 'Observation') + '</b><br>Date: ' + escapeHtml(obs.date || '') + '<br>Value: ' + escapeHtml(obs.value || '') + '<br>Source: ' + escapeHtml(obs.source || ''));
    }});
  }});
}})();
</script>
"""


def section_html(model: dict[str, Any]) -> str:
    total_points = sum(len(series["points"]) for group in model["groups"] for series in group["series"])
    sec_groups = sum(1 for group in model["groups"] if "SEC" in group["badge"])
    sparse_groups = sum(1 for group in model["groups"] if group.get("sparse"))
    cards = "\n".join(card_html(group) for group in model["groups"])
    model_json = safe_script_json(model)
    return f"""
<!-- ai-direct-section:start -->
<section class="ai-direct" id="ai-semiconductor-direct">
  <h2>AI / Semiconductor Direct Data Monitor</h2>
  <p>ส่วนนี้อยู่ใต้ AI Chip Bubble Risk และแยกข้อมูลจริงออกจาก derived score เดิม: SEC quarterly facts สำหรับ capex, debt, inventory, revenue และ source-backed observations สำหรับ GPU rental, HBM, CoWoS และ vendor financing. ทุกกราฟใช้กรอบเวลา 2 ปีตั้งแต่ {esc(model['window_start'])} ถึง {esc(model['window_end'])}.</p>
  <div class="ai-note">Hover หรือคลิกจุดแล้วรายละเอียดจะแสดงใน panel ใต้กราฟ จึงไม่บังกราฟอีกต่อไป. สำหรับ GPU rental และ CoWoS ถ้า public source ไม่มีข้อมูลถี่ครบ 2 ปี ระบบจะแสดงเป็น sparse observation และไม่เติมข้อมูลปลอม.</div>
  <div class="ai-summary">
    <div class="ai-pill"><b>{total_points}</b><span>chart points stored in the 2-year window</span></div>
    <div class="ai-pill"><b>{sec_groups}</b><span>cards with SEC quarterly hard data</span></div>
    <div class="ai-pill"><b>{sparse_groups}</b><span>cards with sparse public observations</span></div>
    <div class="ai-pill"><b>{esc(model.get('generated_at', 'n/a'))}</b><span>dashboard refresh timestamp</span></div>
  </div>
  <div class="ai-grid-cards">
{cards}
  </div>
  <script id="ai-direct-data" type="application/json">{model_json}</script>
{AI_JS}
</section>
<!-- ai-direct-section:end -->
"""


def insert_after_ai_chip(html_text: str, insertion: str) -> str:
    marker = '<div class="v04-card v04-ai">'
    start = html_text.find(marker)
    if start != -1:
        line_end = html_text.find("\n", start)
        if line_end != -1:
            return html_text[: line_end + 1] + insertion + "\n" + html_text[line_end + 1 :]
    anchor = '<section class="sources">'
    if anchor in html_text:
        return html_text.replace(anchor, insertion + "\n" + anchor, 1)
    return html_text.replace("</body>", insertion + "\n</body>", 1)


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
    add_source_once(
        manifest,
        {
            "name": "Business Insider / Silicon Data GPU rental observations",
            "url": "https://www.businessinsider.com/ai-demand-boosts-gpu-prices-silicon-data-ceo-carmen-li-2026-4",
            "publication_date": "Published 2026-04-06; accessed 2026-07-03",
            "used_for": "Sparse GPU rental price observations and explicit source gap for dense historical GPU rental data.",
        },
    )
    add_source_once(
        manifest,
        {
            "name": "Tom's Hardware / Counterpoint advanced packaging observations",
            "url": "https://www.tomshardware.com/tech-industry/global-semiconductor-foundry-market-hit-a-record-320-billion-in-2025",
            "publication_date": "Published 2026-04-02; accessed 2026-07-03",
            "used_for": "Advanced packaging capacity-growth observation used in the CoWoS chart.",
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
    payload["ai_semiconductor_direct_v08"] = model
    payload["dashboard_refreshed_at"] = model["generated_at"]
    add_source_failure(
        payload,
        "GPU rental dense historical API",
        "Open search found only dated public observations; full 2-year daily/monthly history requires licensed Silicon Data or provider-history adapter.",
    )
    add_source_failure(
        payload,
        "CoWoS monthly capacity history",
        "Open search found dated capacity/demand observations but no complete monthly CoWoS public API; chart stores sourced observations and keeps the gap visible.",
    )
    update_manifest(payload)
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    html_text = HTML_PATH.read_text(encoding="utf-8")
    html_text = strip_marker(html_text, "ai-direct-section")
    html_text = strip_marker(html_text, "ai-direct-css")
    html_text = html_text.replace("</style>", AI_CSS + "\n</style>", 1)
    html_text = insert_after_ai_chip(html_text, section_html(model))
    HTML_PATH.write_text(html_text, encoding="utf-8")
    print(f"rebuilt AI direct v08 under AI Chip Bubble Risk with {len(model['groups'])} cards")


if __name__ == "__main__":
    main()
