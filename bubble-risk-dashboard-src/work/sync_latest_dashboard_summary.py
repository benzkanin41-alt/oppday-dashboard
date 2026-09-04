from __future__ import annotations

import html
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


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
            return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    return 50.0


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


def fmt_num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}%"


def now_bangkok() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S Bangkok")


def indicator_map(payload: dict) -> dict[str, dict]:
    return {
        item.get("name"): item
        for item in payload.get("macro_v04", {}).get("indicators", [])
        if item.get("name")
    }


def synchronize_payload(payload: dict) -> dict:
    indicators = indicator_map(payload)
    required = (
        "VIX complacency",
        "High Yield OAS",
        "Yield Curve 10Y-2Y",
        "Real Policy Proxy",
        "Fed Assets YoY",
    )
    missing = [name for name in required if indicators.get(name, {}).get("latest") is None]
    if missing:
        raise RuntimeError(f"Cannot synchronize current summary; missing indicators: {missing}")

    vix = indicators["VIX complacency"]
    hy_oas = indicators["High Yield OAS"]
    curve = indicators["Yield Curve 10Y-2Y"]
    real_policy = indicators["Real Policy Proxy"]
    fed_assets = indicators["Fed Assets YoY"]

    sentiment_score = clamp(
        interp_score(vix["latest"], [(10, 92), (14, 80), (18, 60), (25, 35), (35, 18), (50, 5)])
    )
    credit_score = clamp(
        interp_score(hy_oas["latest"], [(2.0, 92), (3.0, 78), (4.5, 55), (6.0, 35), (8.5, 15), (12, 5)])
    )
    curve_score = interp_score(curve["latest"], [(-1.5, 75), (-0.5, 62), (0, 50), (1.0, 42), (2.0, 35)])
    real_rate_score = interp_score(real_policy["latest"], [(-2.0, 90), (0.0, 72), (1.0, 55), (2.0, 38), (3.5, 20)])
    liquidity_score = interp_score(fed_assets["latest"], [(-15, 20), (-5, 35), (0, 50), (5, 65), (15, 84), (30, 95)])
    macro_liquidity_score = clamp(statistics.fmean([curve_score, real_rate_score, liquidity_score]))

    macro = payload.setdefault("macro", {})
    macro.update(
        {
            "vix": vix["latest"],
            "vix_as_of": vix["date"],
            "hy_oas": hy_oas["latest"],
            "hy_oas_as_of": hy_oas["date"],
            "yield_curve_10y_2y": curve["latest"],
            "yield_curve_as_of": curve["date"],
            "real_policy_proxy": real_policy["latest"],
            "real_policy_as_of": real_policy["date"],
            "fed_assets_1y_change": fed_assets["latest"],
            "fed_assets_as_of": fed_assets["date"],
            "sentiment_score": sentiment_score,
            "credit_score": credit_score,
            "macro_liquidity_score": macro_liquidity_score,
        }
    )

    overall = payload.setdefault("overall", {})
    price_score = float(overall.get("price_score", 50))
    sector_score = float(overall.get("sector_score", 50))
    theme_score = float(overall.get("theme_score", 50))
    credit_liquidity_score = statistics.fmean([credit_score, macro_liquidity_score])
    overall_score = clamp(
        price_score * 0.30
        + sector_score * 0.23
        + theme_score * 0.17
        + sentiment_score * 0.12
        + credit_score * 0.10
        + macro_liquidity_score * 0.08
    )
    drivers = [
        ("price heat", price_score),
        ("sector heat", sector_score),
        ("Nasdaq theme heat", theme_score),
        ("sentiment", sentiment_score),
        ("credit/liquidity", credit_liquidity_score),
    ]
    top_driver = max(drivers, key=lambda item: item[1])
    overall.update(
        {
            "score": overall_score,
            "band": risk_band(overall_score),
            "driver": f"Top live driver in this build: {top_driver[0]} ({top_driver[1]:.0f}/100).",
            "credit_liquidity_score": credit_liquidity_score,
        }
    )

    scores = payload.setdefault("macro_v04", {}).setdefault("scores", {})
    chip1 = round(theme_score * 0.55 + sector_score * 0.45)
    chip2 = round(credit_score * 0.65 + macro_liquidity_score * 0.35)
    chip3 = round(theme_score * 0.45 + sentiment_score * 0.55)
    scores.update(
        {
            "chip1": chip1,
            "chip2": chip2,
            "chip3": chip3,
            "chip": round(chip1 * 0.5 + chip2 * 0.3 + chip3 * 0.2),
        }
    )

    refreshed_at = now_bangkok()
    payload["generated_at"] = refreshed_at
    payload["dashboard_refreshed_at"] = refreshed_at
    return {
        "generated_at": refreshed_at,
        "vix": vix["latest"],
        "vix_as_of": vix["date"],
        "overall_score": overall_score,
        "overall_band": overall["band"],
        "sentiment_score": sentiment_score,
        "credit_liquidity_score": credit_liquidity_score,
        "chip_score": scores["chip"],
    }


def kpi_card(title: str, value: str, description: str, score: float) -> str:
    color = score_color(score)
    return f'''<section class="kpi-card">
      <div class="kpi-head"><span>{html.escape(title)}</span><span class="mini-score" style="--score-color:{color};">{html.escape(value)}</span></div>
      <strong>{html.escape(value)}</strong>
      <p>{html.escape(description)}</p>
    </section>'''


def render_hero(payload: dict) -> str:
    overall = payload["overall"]
    macro = payload["macro"]
    confidence = payload["confidence"]
    return f'''<section class="hero-grid">
      <div class="score-hero">
        <div class="score-big">{overall['score']:.0f}</div>
        <div class="band">{html.escape(overall['band'])}</div>
        <p class="driver">{html.escape(overall['driver'])}</p>
      </div>
      {kpi_card("Price Heat", f"{overall['price_score']:.0f}", "Composite from index ETF proxies and FRED market history.", overall['price_score'])}
      {kpi_card("Sector Heat", f"{overall['sector_score']:.0f}", "S&P 500 sector ETF heat score.", overall['sector_score'])}
      {kpi_card("Sentiment", f"{macro['sentiment_score']:.0f}", f"VIX {fmt_num(macro['vix'])} as of {macro['vix_as_of']}", macro['sentiment_score'])}
      {kpi_card("Data Confidence", f"{confidence['score']:.0f}", confidence['summary'], confidence['score'])}
    </section>'''


def render_macro_table(payload: dict) -> str:
    macro = payload["macro"]
    return f'''<table>
          <tbody>
            <tr><th>VIX</th><td>{fmt_num(macro['vix'])}</td><td>{html.escape(macro['vix_as_of'])}</td></tr>
            <tr><th>HY OAS</th><td>{fmt_num(macro['hy_oas'])}</td><td>{html.escape(macro['hy_oas_as_of'])}</td></tr>
            <tr><th>10Y-2Y curve</th><td>{fmt_num(macro['yield_curve_10y_2y'])} pp</td><td>{html.escape(macro['yield_curve_as_of'])}</td></tr>
            <tr><th>Real policy proxy</th><td>{fmt_num(macro['real_policy_proxy'])} pp</td><td>{html.escape(macro['real_policy_as_of'])}; EFFR - 10Y breakeven</td></tr>
            <tr><th>Fed assets 1Y</th><td>{fmt_pct(macro['fed_assets_1y_change'])}</td><td>{html.escape(macro['fed_assets_as_of'])}; FRED WALCL</td></tr>
          </tbody>
        </table>'''


def synchronize_html(payload: dict) -> None:
    page = HTML.read_text(encoding="utf-8")

    freshness_start = page.index('<div class="freshness">')
    freshness_end = page.index("</div>", freshness_start) + len("</div>")
    freshness = (
        f'<div class="freshness">Generated: {html.escape(payload["generated_at"])}<br>'
        f'Data anchor: market data through {html.escape(payload["data_anchor"])}</div>'
    )
    page = page[:freshness_start] + freshness + page[freshness_end:]

    hero_start = page.index('<section class="hero-grid">')
    hero_end = page.index('<section class="section two-col">', hero_start)
    page = page[:hero_start] + render_hero(payload) + "\n\n    " + page[hero_end:]

    macro_heading = page.index("<h2>Macro Snapshot</h2>")
    table_start = page.index("<table>", macro_heading)
    table_end = page.index("</table>", table_start) + len("</table>")
    page = page[:table_start] + render_macro_table(payload) + page[table_end:]
    HTML.write_text(page, encoding="utf-8")


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    result = synchronize_payload(payload)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    synchronize_html(payload)
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
