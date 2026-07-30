from __future__ import annotations

import html
import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"
MANIFEST = OUT / "source-manifest.json"


def load_thailand_patch():
    path = ROOT / "work" / "patch_thailand_heat_mai_treasury.py"
    spec = importlib.util.spec_from_file_location("thailand_patch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def merge_latest_snapshot(item: dict, history: dict) -> list[dict]:
    points = [
        {"date": str(point.get("date")), "value": float(point["value"])}
        for point in (history.get("points") or [])
        if point.get("date") and point.get("value") is not None
    ]
    points.sort(key=lambda point: point["date"])
    metrics = item.get("metrics") or {}
    latest = metrics.get("latest")
    as_of = str(item.get("as_of") or metrics.get("as_of") or "")[:10]
    if latest is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        current = {"date": as_of, "value": float(latest)}
        if points and points[-1]["date"] == as_of:
            points[-1] = current
        elif not points or points[-1]["date"] < as_of:
            points.append(current)
    history["points"] = points
    return points


def item_lookup(payload: dict) -> dict:
    return {
        item.get("symbol"): item
        for bucket in ("indices", "sectors", "themes")
        for item in payload.get(bucket, [])
        if item.get("symbol")
    }


def enrich_thailand(payload: dict, thailand) -> dict:
    histories = payload.get("price_histories_v04") or {}
    lookup = item_lookup(payload)
    result = {}
    for symbol in ("SET", "mai"):
        item = lookup.get(symbol)
        history = histories.get(symbol)
        if not item or not history:
            raise RuntimeError(f"{symbol} item/history missing")
        points = merge_latest_snapshot(item, history)
        if len(points) < 252:
            raise RuntimeError(f"{symbol} history has only {len(points)} points")
        computed = thailand.compute_price_metrics(points)
        metrics = item.setdefault("metrics", {})
        for key in ("latest", "ret_1y", "dist_200dma", "drawdown_1y", "sparkline"):
            metrics[key] = computed.get(key)
        history.pop("render_mode", None)
        if symbol == "SET":
            history["note"] = (
                "Yahoo Finance ^SET.BK daily history; the latest same-day point is cross-checked "
                "and replaced by the official SET overview snapshot when available."
            )
        else:
            history["note"] = (
                "TradingView SET:MAI daily history; the latest point is cross-checked against "
                "the official SET mai overview snapshot."
            )
        result[symbol] = {
            "points": len(points),
            "first": points[0]["date"],
            "last": points[-1]["date"],
            "ret_1y": metrics["ret_1y"],
            "dist_200dma": metrics["dist_200dma"],
            "drawdown_1y": metrics["drawdown_1y"],
        }

    for row in payload.get("top_watchlist_v03", []):
        item = lookup.get(row.get("symbol"))
        if item:
            row["metrics"] = item.get("metrics") or {}
            row["as_of"] = item.get("as_of") or row.get("as_of")

    payload["source_failures"] = [
        gap
        for gap in payload.get("source_failures", [])
        if "mai historical daily index prices"
        not in str(gap.get("source") or gap.get("name") or "").lower()
    ]
    for gap in payload["source_failures"]:
        if gap.get("source") == "SET historical/valuation data":
            gap["source"] = "Official SET historical download adapter"
            gap["status"] = (
                "Official SET historical downloads remained blocked; the dashboard uses "
                "disclosed Yahoo Finance ^SET.BK and TradingView SET:MAI daily histories, "
                "with current levels and trailing P/E cross-checked from official SET pages."
            )
        elif gap.get("source") == "Earnings yield gap valuation inputs":
            gap["status"] = (
                "SET/mai trailing P/E is sourced from the official SET Market Overview; "
                "other markets remain n/a unless a source-backed valuation is available."
            )
    return result


def render_top_watchlist(payload: dict, thailand) -> str:
    lookup = item_lookup(payload)
    rows = []
    for row in payload.get("top_watchlist_v03", []):
        item = lookup.get(row.get("symbol"), row)
        metrics = item.get("metrics") or row.get("metrics") or {}
        score = float(item.get("score") if item.get("score") is not None else 50)
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.get('name') or '')}<div class='row-meta'>{html.escape(item.get('symbol') or '')} - {html.escape(item.get('region') or '')}</div></td>"
            f"<td>{html.escape(item.get('bucket') or '')}</td>"
            f"<td><span class='score-pill' style='--pill:{thailand.score_color(score)}'>{score:.0f}</span></td>"
            f"<td>{thailand.fmt_pct(metrics.get('ret_1y'))}</td>"
            f"<td>{thailand.fmt_pct(metrics.get('dist_200dma'))}</td>"
            f"<td>{thailand.fmt_pct(metrics.get('drawdown_1y'))}</td>"
            f"<td>{html.escape(item.get('as_of') or row.get('as_of') or 'n/a')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Name</th><th>Bucket</th><th>Score</th>"
        "<th>1Y</th><th>vs 200DMA</th><th>1Y Drawdown</th><th>As of</th>"
        "</tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"
    )


def patch_top_watchlist(html_text: str, payload: dict, thailand) -> str:
    pattern = r'(<h2>Top Watchlist</h2>\s*)<table>.*?</table>'
    patched, count = re.subn(
        pattern,
        lambda match: match.group(1) + render_top_watchlist(payload, thailand),
        html_text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not locate Top Watchlist table")
    return patched


def main() -> None:
    thailand = load_thailand_patch()
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    result = enrich_thailand(payload, thailand)
    html_text = HTML.read_text(encoding="utf-8")
    html_text = thailand.patch_market_heat_grid(html_text, payload)
    html_text = patch_top_watchlist(html_text, payload, thailand)
    html_text = thailand.update_v03_json(html_text, payload)
    html_text = thailand.patch_single_point_chart_js(html_text)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST.write_text(json.dumps(payload.get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")
    HTML.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "thailand": result, "top_watchlist_drawdown": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
