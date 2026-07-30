from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"
MANIFEST = OUT / "source-manifest.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    html = HTML.read_text(encoding="utf-8")
    lookup = {item.get("symbol"): item for item in payload.get("indices", [])}
    histories = payload.get("price_histories_v04") or {}
    result = {}
    for symbol in ("SET", "mai"):
        points = (histories.get(symbol) or {}).get("points") or []
        metrics = (lookup.get(symbol) or {}).get("metrics") or {}
        require(len(points) >= 252, f"{symbol} history has only {len(points)} points")
        for key in ("ret_1y", "dist_200dma", "drawdown_1y"):
            require(metrics.get(key) is not None, f"{symbol} {key} missing")
        require(len(metrics.get("sparkline") or []) >= 2, f"{symbol} sparkline missing")
        result[symbol] = {key: metrics[key] for key in ("ret_1y", "dist_200dma", "drawdown_1y")}

    heat = re.search(r'<div id="indices" class="tile-grid">(.*?)<div id="sectors"', html, re.S)
    require(heat is not None, "Market heat grid missing")
    for name in ("SET Index", "mai Index"):
        card_match = re.search(
            rf'<article class="market-tile">(?:(?!</article>).)*?<h3>{name}</h3>(?:(?!</article>).)*?</article>',
            heat.group(1),
            re.S,
        )
        require(card_match is not None, f"{name} heat card missing")
        card = card_match.group(0)
        require("1Y return" in card and "vs 200DMA" in card and "1Y drawdown" in card, f"{name} heat metrics incomplete")
        require("<circle cx=\"64\"" not in card, f"{name} still renders a single-point spark")

    watch = re.search(r'<h2>Top Watchlist</h2>\s*(<table>.*?</table>)', html, re.S)
    require(watch is not None and "1Y Drawdown" in watch.group(1), "Top Watchlist drawdown column missing")
    for name in ("SET Index", "mai Index"):
        row = re.search(rf"<tr><td>{name}.*?</tr>", watch.group(1), re.S)
        require(row is not None, f"{name} Top Watchlist row missing")
        require(row.group(0).count("n/a") == 0, f"{name} Top Watchlist row still has n/a")

    model = payload.get("ai_semiconductor_direct_v08") or {}
    capex_group = next((group for group in model.get("groups", []) if group.get("id") == "hyperscaler-capex"), None)
    require(capex_group is not None, "Hyperscaler capex group missing")
    meta = next((series for series in capex_group.get("series", []) if series.get("name") == "META"), None)
    require(meta is not None, "META capex series missing")
    q2 = next((point for point in meta.get("points", []) if point.get("date") == "2026-06-30"), None)
    require(q2 is not None and abs(float(q2["value"]) - 30.116) < 0.001, f"META Q2 capex wrong: {q2}")
    require("earnings release" in str(q2.get("source") or "").lower(), "META Q2 official release source missing")
    sources = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(any(source.get("name") == "Meta Q2 2026 earnings release" for source in sources), "Meta release missing from source manifest")
    print(json.dumps({"status": "ok", "thailand": result, "meta_q2_capex_b": q2["value"], "top_watchlist_drawdown": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
