from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
HTML = OUT / "index.html"
DATA = OUT / "data.json"


SERIES_LABEL = {
    "VIX complacency": "Cboe VIX historical price data",
    "High Yield OAS": "FRED BAMLH0A0HYM2",
    "Yield Curve 10Y-2Y": "U.S. Treasury daily XML latest + FRED history",
    "Real Policy Proxy": "NY Fed EFFR + FRED T10YIE",
    "Fed Assets YoY": "FRED WALCL YoY (weekly Wednesday series)",
    "Buffett Indicator (US equities / GDP)": "FRED NCBEILQ027S / GDP source gap",
}


def strip_marker(text: str, marker: str) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    while start in text and end in text:
        a = text.index(start)
        b = text.index(end, a) + len(end)
        text = text[:a] + text[b:]
    return text


def band(score):
    if score is None:
        return "n/a", "#9aa8b5"
    if score < 25:
        return "Cool", "#4aaa63"
    if score < 50:
        return "Normal", "#7abc86"
    if score < 65:
        return "Warm", "#d9b644"
    if score < 80:
        return "Frothy", "#e9912f"
    return "Extreme", "#d95445"


def fmt(value, digits=2):
    return "n/a" if value is None else f"{value:,.{digits}f}"


def unit_fmt(value, unit):
    if value is None:
        return "n/a"
    if unit in {"%", "pp", "x"}:
        return f"{fmt(value)}{unit}"
    return fmt(value)


def spark(points):
    pts = [p for p in (points or [])[-80:] if p.get("value") is not None]
    if len(pts) < 2:
        return '<svg class="v04-spark" viewBox="0 0 120 32"></svg>'
    vals = [p["value"] for p in pts]
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    pairs = []
    for i, point in enumerate(pts):
        x = i * 118 / max(1, len(pts) - 1) + 1
        y = 30 - (point["value"] - lo) / span * 28
        pairs.append(f"{x:.1f},{y:.1f}")
    return f'<svg class="v04-spark" viewBox="0 0 120 32"><polyline points="{" ".join(pairs)}"/></svg>'


def gauge(title, subtitle, score, body):
    label, color = band(score)
    deg = -90 + 180 * max(0, min(100, score or 0)) / 100
    return (
        '<article class="v04-card v04-gauge-card">'
        f"<h3>{html.escape(title)}</h3><p>{html.escape(subtitle)}</p>"
        '<div class="v04-gauge"><div class="v04-gauge-arc"></div>'
        f'<div class="v04-needle" style="transform:rotate({deg:.1f}deg)"></div>'
        f'<div class="v04-score">{score}</div><div class="v04-band" style="color:{color}">{label}</div></div>'
        f'<b style="color:{color}">{label} - {score}/100</b><p>{html.escape(body)}</p>'
        "</article>"
    )


def render_macro(payload):
    macro = payload.get("macro_v04", {})
    scores = macro.get("scores", {})
    rows = []
    for indicator in macro.get("indicators", []):
        pct = indicator.get("pct")
        label, color = band(pct)
        width = 0 if pct is None else max(0, min(100, pct))
        source = SERIES_LABEL.get(indicator.get("name"), "Dashboard adapter")
        if indicator.get("latest") is None:
            source = source + " - value not available"
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(indicator.get('name') or '')}</strong>"
            f"<div class='v04-muted'>{html.escape(indicator.get('desc') or '')}</div>"
            f"<div class='v04-source'>Data: {html.escape(source)}</div></td>"
            f"<td>{unit_fmt(indicator.get('latest'), indicator.get('unit'))}<div class='v04-muted'>{html.escape(indicator.get('date') or '')}</div></td>"
            f"<td>{fmt(indicator.get('delta'))}</td>"
            f"<td><div class='v04-bar'><span style='width:{width:.0f}%;background:{color}'></span><b>{fmt(pct,0)}</b></div></td>"
            f"<td><span class='v04-tag' style='border-color:{color};color:{color}'>{html.escape(label)}</span></td>"
            f"<td>{spark(indicator.get('spark'))}</td>"
            "</tr>"
        )
    checklist = [
        ("No price too high", "Warm", "Qualitative read: valuation and price heat are above normal in several proxies."),
        ("FOMO / fear of being left behind", "Warm", "Theme and semiconductor heat remain visible; this is not a direct API score."),
        ("Eager lending / cheap risk", "Warm", "Credit-spread data suggests risk appetite is still elevated."),
        ("Absence of skepticism / this time is different", "Warm", "AI narrative still needs valuation discipline and source-backed checks."),
        ("Hot IPO / new-product proliferation", "Cool", "Not in numeric score yet; needs an IPO/new-issuance adapter."),
    ]
    checks = "".join(
        f"<div class='v04-check'><span></span><strong>{html.escape(name)}</strong><em>{html.escape(signal)}</em><p>{html.escape(text)}</p></div>"
        for name, signal, text in checklist
    )
    return f'''
<!-- v04-macro-section:start -->
<section class="v04-dark">
  <div class="v04-head"><div><h2>Macro Monitor - Froth & Cycle</h2><p>ภาษาไทย/English mix. Data rows below are calculated from actual source series where available; qualitative checklists are labelled separately.</p></div><div class="v04-asof">data as of<br><strong>{html.escape(payload.get("data_anchor",""))}</strong></div></div>
  <div class="v04-posture"><span>Suggested posture - aggressive vs defensive</span><h3>Lean Defensive</h3><p>คะแนนรวมยังอยู่โซนร้อน ควรเพิ่ม margin of safety, ไม่ไล่ราคา, และเตรียม cash buffer สำหรับจังหวะ forced selling.</p><div class="v04-temp"><i style="left:{scores.get('froth',0)}%"></i></div></div>
  <div class="v04-gauge-grid">
    {gauge("Froth / Bubble Gauge", "Valuation - credit - liquidity - complacency", scores.get("froth", 0), "Higher score means hotter risk appetite; it is not a timing signal.")}
    {gauge("Recession-Risk Gauge", "Yield curve - spread - policy tightness", scores.get("recession", 0), "Use this for downside protection, not as a single recession forecast.")}
    {gauge("Long-Term Debt Cycle", "Credit stress - liquidity - real policy", scores.get("debt", 0), "Reflects debt/liquidity-cycle pressure.")}
  </div>
  <div class="v04-card"><h3>Bubble Psychology - Howard Marks' Checklist</h3><p class="v04-muted">Qualitative overlay only. These bullets are a human-read checklist, not direct numeric data.</p><div class="v04-check-grid">{checks}</div></div>
  <div class="v04-card"><h3>Froth Gauge - Components</h3><p class="v04-muted">The rows below are data-driven when a value is shown. Percentile is computed from the available history in the dashboard payload.</p><table class="v04-table"><thead><tr><th>Indicator</th><th>Latest</th><th>1Y change</th><th>Percentile</th><th>Signal</th><th>5Y trend</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
  <div class="v04-card v04-ai"><div>{gauge("AI Chip Bubble Risk", "Semis - themes - credit - sentiment", scores.get("chip", 0), "Derived from theme/sector heat plus macro credit/liquidity scores.")}</div><div><h3>AI / Semiconductor Cycle Monitor</h3><p>This panel is derived, not a direct physical-supply API. It uses semiconductor/theme price heat plus dashboard macro stress. Next step should add direct data for capex, GPU rental prices, HBM/CoWoS lead times, and vendor-financing exposure.</p><div class="v04-tier"><b>{scores.get('chip1',0)}</b><span>Tier 1 - Bell-ringers</span><em>Theme/semiconductor heat proxy</em></div><div class="v04-tier"><b>{scores.get('chip2',0)}</b><span>Tier 2 - Financing & cycle stress</span><em>Credit/liquidity pressure</em></div><div class="v04-tier"><b>{scores.get('chip3',0)}</b><span>Tier 3 - Valuation & sentiment</span><em>Theme heat plus sentiment proxy</em></div></div></div>
</section>
<!-- v04-macro-section:end -->
'''


READABILITY_CSS = '''
<!-- v04-readability-css:start -->
.v04-dark,.v04-dark h2,.v04-dark h3,.v04-dark strong,.v04-dark td,.v04-dark th{color:#eef3fb}.v04-dark p,.v04-muted{color:#b9c8dc}.v04-source{color:#7fb0e8;font-size:12px;margin-top:5px}.v04-score{color:#f4f7fb;text-shadow:0 1px 8px rgba(0,0,0,.55)}.v04-card h3{color:#eef3fb}.v04-table td{vertical-align:top}.v04-check strong{color:#eef3fb}.v04-check p{color:#b9c8dc}
<!-- v04-readability-css:end -->
'''


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    html_text = HTML.read_text(encoding="utf-8")
    html_text = strip_marker(html_text, "v04-macro-section")
    html_text = strip_marker(html_text, "v04-readability-css")
    html_text = html_text.replace("</style>", READABILITY_CSS + "\n</style>", 1)
    html_text = html_text.replace("<main>", "<main>\n" + render_macro(payload), 1)
    HTML.write_text(html_text, encoding="utf-8")
    print("clean macro section rebuilt")


if __name__ == "__main__":
    main()
