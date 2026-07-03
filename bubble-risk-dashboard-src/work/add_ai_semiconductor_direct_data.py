from __future__ import annotations

import html
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
HTML = OUT / "index.html"
DATA = OUT / "data.json"
MANIFEST = OUT / "source-manifest.json"
RAW = ROOT / "work" / "raw" / "ai_direct_v06"
UA = "Codex bubble-risk-dashboard contact: user@example.com"
START = date(2024, 7, 1)

CIKS = {
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "AMZN": "0001018724",
    "ORCL": "0001341439",
    "CRWV": "0001769628",
    "MU": "0000723125",
}


def request_json(url: str) -> dict:
    raw = urlopen(Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30).read()
    return json.loads(raw.decode("utf-8"))


def sec_companyfacts(ticker: str) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"sec_companyfacts_{ticker}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = request_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIKS[ticker]}.json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def usd_rows(facts: dict, tag: str) -> list[dict]:
    return (((facts.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}).get("units", {}).get("USD", [])


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def dedupe_duration_rows(rows: list[dict]) -> list[dict]:
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row.get("form") not in {"10-Q", "10-K", "20-F"}:
            continue
        start, end = row.get("start"), row.get("end")
        if not start or not end or row.get("val") is None:
            continue
        key = (start, end)
        old = best.get(key)
        if old is None or (row.get("filed") or "") >= (old.get("filed") or ""):
            best[key] = row
    return sorted(best.values(), key=lambda r: (r["end"], r["start"], r.get("filed") or ""))


def quarterly_cashflow(facts: dict, tag_candidates: list[str]) -> list[dict]:
    raw_rows: list[dict] = []
    tag_used = None
    for tag in tag_candidates:
        raw_rows = usd_rows(facts, tag)
        if raw_rows:
            tag_used = tag
            break
    if not raw_rows:
        return []
    rows = dedupe_duration_rows(raw_rows)
    by_start: dict[str, list[dict]] = {}
    for row in rows:
        by_start.setdefault(row["start"], []).append(row)
    points = []
    for start, group in by_start.items():
        group = sorted(group, key=lambda r: r["end"])
        previous_val = 0
        previous_end = None
        for row in group:
            start_d, end_d = parse_date(row["start"]), parse_date(row["end"])
            if not start_d or not end_d:
                continue
            days = (end_d - start_d).days + 1
            if days <= 110:
                quarter_val = row["val"]
            else:
                quarter_val = row["val"] - previous_val
            previous_val = row["val"]
            previous_end = end_d
            if end_d >= START and quarter_val is not None:
                points.append(
                    {
                        "date": end_d.isoformat(),
                        "value": round(abs(float(quarter_val)) / 1e9, 3),
                        "tag": tag_used,
                        "form": row.get("form"),
                        "filed": row.get("filed"),
                        "accn": row.get("accn"),
                    }
                )
    deduped: dict[str, dict] = {}
    for point in sorted(points, key=lambda p: (p["date"], p.get("filed") or "")):
        deduped[point["date"]] = point
    return list(deduped.values())[-10:]


def instant_series(facts: dict, tag_candidates: list[str]) -> list[dict]:
    raw_rows = []
    tag_used = None
    for tag in tag_candidates:
        raw_rows = usd_rows(facts, tag)
        if raw_rows:
            tag_used = tag
            break
    best: dict[str, dict] = {}
    for row in raw_rows:
        if row.get("form") not in {"10-Q", "10-K", "20-F"}:
            continue
        end_d = parse_date(row.get("end"))
        if not end_d or end_d < START or row.get("val") is None:
            continue
        old = best.get(end_d.isoformat())
        if old is None or (row.get("filed") or "") >= (old.get("filed") or ""):
            best[end_d.isoformat()] = row
    return [
        {
            "date": end,
            "value": round(float(row["val"]) / 1e9, 3),
            "tag": tag_used,
            "form": row.get("form"),
            "filed": row.get("filed"),
            "accn": row.get("accn"),
        }
        for end, row in sorted(best.items())
    ][-10:]


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault("sources", [])
    if not any(item.get("name") == source["name"] for item in sources):
        sources.append(source)


def strip_marker(text: str, marker: str) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    while start in text and end in text:
        a = text.index(start)
        b = text.index(end, a) + len(end)
        text = text[:a] + text[b:]
    return text


def series_latest(series: dict[str, list[dict]]) -> dict[str, float | None]:
    out = {}
    for key, points in series.items():
        out[key] = points[-1]["value"] if points else None
    return out


def chart_svg(series: dict[str, list[dict]], unit: str, height: int = 220) -> str:
    width = 760
    pad_l, pad_r, pad_t, pad_b = 54, 18, 22, 36
    colors = ["#69a7ff", "#47d18c", "#f2b84b", "#ef6a5b", "#b98cff", "#52d3d8", "#f08bd4"]
    all_points = [(name, p) for name, pts in series.items() for p in pts if p.get("value") is not None]
    if not all_points:
        return f'<svg class="ai-chart" viewBox="0 0 {width} {height}"><text x="20" y="40">No source-backed series yet</text></svg>'
    xs = [parse_date(p["date"]).toordinal() for _, p in all_points if parse_date(p["date"])]
    ys = [float(p["value"]) for _, p in all_points]
    x_min = min(xs + [START.toordinal()])
    x_max = max(xs + [date(2026, 7, 3).toordinal()])
    y_min, y_max = min(ys), max(ys)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    y_pad = (y_max - y_min) * 0.12
    y_min -= y_pad
    y_max += y_pad

    def x(date_text: str) -> float:
        d = parse_date(date_text) or START
        return pad_l + (d.toordinal() - x_min) / max(1, x_max - x_min) * (width - pad_l - pad_r)

    def y(value: float) -> float:
        return height - pad_b - (value - y_min) / max(1e-9, y_max - y_min) * (height - pad_t - pad_b)

    grid = []
    for i in range(4):
        yy = pad_t + i * (height - pad_t - pad_b) / 3
        grid.append(f'<line x1="{pad_l}" x2="{width-pad_r}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
    paths = []
    legend = []
    for idx, (name, pts) in enumerate(series.items()):
        clean = [p for p in pts if p.get("value") is not None]
        if not clean:
            continue
        color = colors[idx % len(colors)]
        d = " ".join(("M" if i == 0 else "L") + f"{x(p['date']):.1f},{y(float(p['value'])):.1f}" for i, p in enumerate(clean))
        paths.append(f'<path d="{d}" stroke="{color}" class="ai-line"/>')
        for p in clean:
            label = f"{name} | {p['date']} | {p['value']} {unit}"
            paths.append(f'<circle cx="{x(p["date"]):.1f}" cy="{y(float(p["value"])):.1f}" r="4" fill="{color}"><title>{html.escape(label)}</title></circle>')
        legend.append(f'<span><i style="background:{color}"></i>{html.escape(name)}</span>')
    return (
        f'<svg class="ai-chart" viewBox="0 0 {width} {height}"><g class="ai-grid">{"".join(grid)}</g>'
        f'{"".join(paths)}<g class="ai-axis"><text x="{pad_l}" y="{height-10}">2024-07</text>'
        f'<text x="{width-pad_r}" y="{height-10}" text-anchor="end">2026-07</text>'
        f'<text x="8" y="{pad_t+4}">{html.escape(unit)}</text></g></svg>'
        f'<div class="ai-legend">{"".join(legend)}</div>'
    )


def observation_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        body.append(
            f"<tr><td>{html.escape(row.get('date',''))}</td><td>{html.escape(row.get('metric',''))}</td>"
            f"<td>{html.escape(str(row.get('value','')))}</td><td>{html.escape(row.get('source',''))}</td></tr>"
        )
    return f'<table class="ai-small-table"><thead><tr><th>Date</th><th>Metric</th><th>Value</th><th>Source</th></tr></thead><tbody>{"".join(body)}</tbody></table>'


def render_card(title: str, subtitle: str, quality: str, source_type: str, chart: str, observations: str = "") -> str:
    return (
        '<article class="ai-card">'
        f'<div class="ai-card-head"><div><h3>{html.escape(title)}</h3><p>{html.escape(subtitle)}</p></div>'
        f'<span>{html.escape(quality)}</span></div>'
        f'<div class="ai-source-type">{html.escape(source_type)}</div>{chart}{observations}</article>'
    )


def build_data() -> dict:
    sec = {ticker: sec_companyfacts(ticker) for ticker in CIKS}
    capex = {
        ticker: quarterly_cashflow(sec[ticker], ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"])
        for ticker in ["MSFT", "GOOGL", "META", "AMZN", "ORCL"]
    }
    coreweave = {
        "CRWV capex": quarterly_cashflow(sec["CRWV"], ["PaymentsToAcquirePropertyPlantAndEquipment"]),
        "CRWV long-term debt": instant_series(sec["CRWV"], ["LongTermDebt", "DebtInstrumentCarryingAmount"]),
        "CRWV PP&E net": instant_series(sec["CRWV"], ["PropertyPlantAndEquipmentNet"]),
        "CRWV debt issuance": quarterly_cashflow(sec["CRWV"], ["ProceedsFromIssuanceOfLongTermDebt"]),
    }
    micron = {
        "MU revenue": quarterly_cashflow(sec["MU"], ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]),
        "MU inventory": instant_series(sec["MU"], ["InventoryNet"]),
        "MU capex": quarterly_cashflow(sec["MU"], ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    }
    gpu_rental = {
        "NeoCloud H100": [
            {"date": "2026-01-06", "value": 2.20, "source": "Silicon Data via Business Insider; start value inferred from reported 3-month move"},
            {"date": "2026-04-06", "value": 2.64, "source": "Silicon Data via Business Insider"},
        ],
        "NeoCloud B200": [
            {"date": "2026-01-06", "value": 4.40, "source": "Silicon Data via Business Insider; start value inferred from reported 3-month move"},
            {"date": "2026-04-06", "value": 5.35, "source": "Silicon Data via Business Insider"},
        ],
        "Hyperscaler H100": [
            {"date": "2025-08-11", "value": 8.00, "source": "TechRadar cited around $8/hour for hyperscaler H100 rental"},
            {"date": "2026-01-06", "value": 7.26, "source": "Silicon Data via Business Insider; start value inferred from reported 3-month move"},
            {"date": "2026-04-06", "value": 7.46, "source": "Silicon Data via Business Insider"},
        ],
    }
    hbm_observations = [
        {"date": "2025-12-03", "metric": "Micron consumer exit / AI-memory focus", "value": "strategic pivot", "source": "Micron press/news coverage"},
        {"date": "2026-06-28", "metric": "Micron HBM sold-out horizon", "value": "sold out through 2026; can meet ~50-66% of demand", "source": "The Times / Micron reporting"},
    ]
    cowos_series = {
        "Capacity index": [
            {"date": "2024-10-17", "value": 200, "source": "TSMC earnings coverage: CoWoS capacity to more than double by end-2024; index 2024 base=100"},
            {"date": "2026-04-02", "value": 360, "source": "Counterpoint/Tom's Hardware: advanced packaging capacity projected +80% YoY in 2026; normalized index"},
        ],
        "Demand/capacity ratio": [
            {"date": "2025-11-25", "value": 3.0, "source": "TSMC CEO comments reported by Tom's Hardware: advanced-node capacity about 3x short of demand"},
        ],
    }
    vendor_events = [
        {"date": "2024-05-17", "metric": "CoreWeave debt raise", "value": "$7.5B reported debt financing", "source": "WSJ/Bloomberg coverage"},
        {"date": "2025-03-10", "metric": "OpenAI-CoreWeave contract", "value": "~$11.9B / 5 years", "source": "Reuters / CoreWeave IPO coverage"},
        {"date": "2025-09-15", "metric": "NVIDIA-CoreWeave capacity backstop", "value": "$6.3B order / unused capacity backstop", "source": "CoreWeave SEC 8-K / market coverage"},
        {"date": "2026-01-01", "metric": "NVIDIA equity investment", "value": "$2B CoreWeave share purchase reported", "source": "Business Insider / company coverage"},
    ]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S Bangkok"),
        "lookback_start": START.isoformat(),
        "capex": capex,
        "coreweave": coreweave,
        "micron": micron,
        "gpu_rental": gpu_rental,
        "hbm_observations": hbm_observations,
        "cowos": cowos_series,
        "vendor_events": vendor_events,
    }


AI_CSS = """
<!-- ai-direct-css:start -->
.ai-direct{background:#0f1520;color:#eef3fb;border:1px solid #273247;border-radius:8px;margin-top:22px;padding:18px}.ai-direct h2{font-size:24px;color:#f5f8ff;margin:0}.ai-direct>p{color:#b9c8dc;margin:8px 0 16px}.ai-grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px}.ai-card{background:#151d2b;border:1px solid #29364d;border-radius:8px;padding:14px;min-width:0}.ai-card-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.ai-card h3{margin:0 0 5px;color:#f4f7ff;font-size:17px}.ai-card p{margin:0;color:#b7c8df;line-height:1.4}.ai-card-head span{border:1px solid #3e8edb;color:#9dccff;border-radius:999px;padding:4px 8px;font-size:12px;font-weight:800;white-space:nowrap}.ai-source-type{color:#84b8f2;font-size:12px;margin:8px 0 10px}.ai-chart{width:100%;height:auto;background:#101722;border:1px solid #243048;border-radius:6px}.ai-grid line{stroke:#25334a;stroke-width:1}.ai-line{fill:none;stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}.ai-axis text{fill:#9fb2ca;font-size:12px}.ai-legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;color:#c3d1e4;font-size:12px}.ai-legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.ai-small-table{font-size:12px;margin-top:10px}.ai-small-table th,.ai-small-table td{padding:6px 8px;border-bottom:1px solid #26344a;color:#d6e3f4}.ai-small-table th{color:#9eb3ce}.ai-note{color:#f0c36d;background:#211d12;border:1px solid #6b5222;border-radius:6px;padding:10px;margin:12px 0}.ai-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:14px 0}.ai-pill{background:#101722;border:1px solid #27364e;border-radius:8px;padding:10px}.ai-pill b{display:block;color:#fff;font-size:20px}.ai-pill span{color:#aabbd2;font-size:12px}
@media(max-width:760px){.ai-grid-cards{grid-template-columns:1fr}.ai-card-head{display:block}.ai-card-head span{display:inline-block;margin-top:8px}}
<!-- ai-direct-css:end -->
"""


def render_section(ai: dict) -> str:
    capex_latest = series_latest(ai["capex"])
    core_latest = series_latest(ai["coreweave"])
    gpu_latest = series_latest(ai["gpu_rental"])
    micron_latest = series_latest(ai["micron"])
    total_latest_capex = sum(v for v in capex_latest.values() if v is not None)
    summary = (
        '<div class="ai-summary">'
        f'<div class="ai-pill"><b>${total_latest_capex:,.1f}B</b><span>latest reported hyperscaler quarterly capex in SEC data</span></div>'
        f'<div class="ai-pill"><b>${(core_latest.get("CRWV long-term debt") or 0):,.1f}B</b><span>CoreWeave latest long-term debt, SEC facts</span></div>'
        f'<div class="ai-pill"><b>${(gpu_latest.get("NeoCloud H100") or 0):,.2f}/hr</b><span>NeoCloud H100 latest Silicon Data observation</span></div>'
        f'<div class="ai-pill"><b>${(micron_latest.get("MU inventory") or 0):,.1f}B</b><span>Micron latest inventory, SEC facts</span></div>'
        "</div>"
    )
    return f"""
<!-- ai-direct-section:start -->
<section class="ai-direct">
  <h2>AI / Semiconductor Direct Data Monitor</h2>
  <p>ส่วนนี้เพิ่มข้อมูลจริงแยกจาก derived score เดิม: SEC quarterly facts สำหรับ capex/debt/inventory/revenue และ source-backed observations สำหรับ GPU rental, HBM, CoWoS, vendor-financing events. กราฟทุกใบใช้ช่วงย้อนหลังประมาณ 2 ปี; จุดข้อมูลบางหมวดเป็น sparse observations เพราะ public source ไม่ได้ให้ daily/quarterly API.</p>
  <div class="ai-note">อ่านแบบนักลงทุน: capex และ CoreWeave debt เป็น hard filing data; GPU rental/HBM/CoWoS/vendor events เป็น source-backed observation series ไม่ใช่ licensed full time-series. ตัวเลขที่ไม่มี source จะไม่เติมเอง.</div>
  {summary}
  <div class="ai-grid-cards">
    {render_card("GPU Rental Price", "H100/B200 rental observations in $ per GPU-hour.", "Medium confidence", "Silicon Data via Business Insider + TechRadar observation", chart_svg(ai["gpu_rental"], "$/hr"))}
    {render_card("HBM / Memory Supply Proxy", "Micron revenue, inventory, capex from SEC; HBM sold-out status shown as observations.", "Medium confidence", "SEC hard data + HBM source observations", chart_svg(ai["micron"], "$B"), observation_table(ai["hbm_observations"]))}
    {render_card("CoWoS / Advanced Packaging", "Normalized source-backed capacity and demand-gap observations.", "Medium-low confidence", "TSMC/Counterpoint reported observations; not a full capacity API", chart_svg(ai["cowos"], "index / x"))}
    {render_card("Hyperscaler Capex", "Quarterly cash capex from SEC Company Facts.", "High confidence", "SEC XBRL Company Facts: MSFT, GOOGL, META, AMZN, ORCL", chart_svg(ai["capex"], "$B"))}
    {render_card("Vendor Financing / Neocloud Leverage", "CoreWeave debt, PP&E, capex, and debt issuance from SEC.", "High confidence", "SEC XBRL Company Facts: CoreWeave CRWV", chart_svg(ai["coreweave"], "$B"), observation_table(ai["vendor_events"]))}
  </div>
</section>
<!-- ai-direct-section:end -->
"""


def patch_source_manifest_table(html_text: str, sources: list[dict]) -> str:
    rows = "\n".join(
        f'<tr><td>{html.escape(s.get("name",""))}</td><td>{html.escape(s.get("used_for",""))}</td><td>{html.escape(s.get("publication_date",""))}</td><td><a href="{html.escape(s.get("url",""))}">source</a></td></tr>'
        for s in sources
    )
    pattern = r'(<h2>Source Manifest</h2>\s*<table>\s*<thead><tr><th>Source</th><th>Used For</th><th>Publication / Access Date</th><th>Link</th></tr></thead>\s*)<tbody>.*?</tbody>'
    return re.sub(pattern, r"\1<tbody>" + rows + "</tbody>", html_text, flags=re.S)


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    ai = build_data()
    payload["ai_semiconductor_direct_v06"] = ai
    add_source_once(payload, {"name": "SEC Company Facts API", "url": "https://data.sec.gov/api/xbrl/companyfacts/", "publication_date": "Data fetched 2026-07-03", "used_for": "Quarterly hyperscaler capex, Micron revenue/inventory/capex, and CoreWeave debt/PPE/capex/debt issuance."})
    add_source_once(payload, {"name": "Silicon Data GPU rental indexes via Business Insider", "url": "https://www.businessinsider.com/ai-demand-boosts-gpu-prices-silicon-data-ceo-carmen-li-2026-4", "publication_date": "Published 2026-04-06; accessed 2026-07-03", "used_for": "Sparse GPU rental price observations for NeoCloud H100, NeoCloud B200, and Hyperscaler H100."})
    add_source_once(payload, {"name": "TechRadar H100 cloud rental observation", "url": "https://www.techradar.com/pro/the-hidden-mathematics-of-ai-why-your-gpu-bills-dont-add-up", "publication_date": "Published 2025-08-11; accessed 2026-07-03", "used_for": "H100 hyperscaler rental observation around $8/hour."})
    add_source_once(payload, {"name": "Micron HBM sold-out reporting", "url": "https://www.thetimes.com/business/technology/article/micron-semiconductor-ai-stock-volatile-7ftpl8v2j", "publication_date": "Published 2026-06-28; accessed 2026-07-03", "used_for": "HBM sold-out horizon and demand-fulfillment observation."})
    add_source_once(payload, {"name": "TSMC / Counterpoint advanced packaging observations", "url": "https://www.tomshardware.com/tech-industry/global-semiconductor-foundry-market-hit-a-record-320-billion-in-2025", "publication_date": "Published 2026-04-02; accessed 2026-07-03", "used_for": "Advanced packaging capacity growth observation used in CoWoS normalized chart."})
    add_source_once(payload, {"name": "TSMC advanced-node capacity gap observation", "url": "https://www.tomshardware.com/tech-industry/semiconductors/tsmc-csays-advanced-node-capacity-falls-short-of-ai-demand", "publication_date": "Published 2025-11-25; accessed 2026-07-03", "used_for": "Demand/capacity gap observation for advanced-node bottleneck context."})
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST.write_text(json.dumps(payload.get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")

    html_text = HTML.read_text(encoding="utf-8")
    html_text = strip_marker(html_text, "ai-direct-section")
    html_text = strip_marker(html_text, "ai-direct-css")
    html_text = html_text.replace("</style>", AI_CSS + "\n</style>", 1)
    section = render_section(ai)
    macro_end = "<!-- v04-macro-section:end -->"
    if macro_end in html_text:
        html_text = html_text.replace(macro_end, macro_end + "\n" + section, 1)
    else:
        html_text = html_text.replace("<main>", "<main>\n" + section, 1)
    html_text = patch_source_manifest_table(html_text, payload.get("sources", []))
    HTML.write_text(html_text, encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "capex_latest": series_latest(ai["capex"]),
        "coreweave_latest": series_latest(ai["coreweave"]),
        "gpu_latest": series_latest(ai["gpu_rental"]),
        "micron_latest": series_latest(ai["micron"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
