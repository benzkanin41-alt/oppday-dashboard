from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from patch_mai_tradingview_history import add_source_once
from retain_dashboard_history import correct_snapshot_date, merge_points
from tv_fetch_history import fetch_history


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
RAW = ROOT / "work" / "raw" / "tradingview" / "SET_SET_daily.json"
SOURCE_URL = "https://www.tradingview.com/symbols/SET-SET/"


def verified_session(item: dict, points: list[dict]) -> str:
    if not points:
        raise RuntimeError("SET daily session history is empty")
    latest = float(item["metrics"]["latest"])
    if abs(float(points[-1]["value"]) - latest) > 0.011:
        raise RuntimeError("SET daily last close disagrees with the official SET overview snapshot")
    return points[-1]["date"]


def normalize_snapshot(item: dict, points: list[dict]) -> str:
    session = verified_session(item, points)
    item["page_updated_at"] = item.get("page_updated_at") or item.get("as_of")
    item["market_session_date"] = session
    item["as_of"] = session
    item["metrics"]["as_of"] = session
    return session


def read_or_fetch() -> tuple[list[dict], str]:
    try:
        points = fetch_history("SET:SET", 1000)
        if len(points) < 500:
            raise RuntimeError("SET daily history returned too few points")
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(json.dumps({
            "source": "TradingView chart websocket",
            "symbol": "SET:SET",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "points": points,
        }, indent=2), encoding="utf-8")
        return points, "live"
    except Exception as exc:
        if not RAW.exists():
            raise
        cached = json.loads(RAW.read_text(encoding="utf-8"))
        return cached["points"], f"cached; refresh failed: {exc}"


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    points, mode = read_or_fetch()
    item = next(row for row in payload["indices"] if row["symbol"] == "SET")
    session = normalize_snapshot(item, points)
    history = payload["price_histories_v04"]["SET"]
    stored = history.get("points", [])
    valid = []
    for point in stored:
        if point["date"] > session:
            if abs(float(point["value"]) - float(item["metrics"]["latest"])) > 0.011:
                raise RuntimeError("Unverified SET point after the latest exchange session")
            correct_snapshot_date("SET", point, session, SOURCE_URL)
        else:
            valid.append(point)
    current = [{
        "date": point["date"], "value": point["value"],
        "source_url": SOURCE_URL, "source_kind": "TradingView daily SET Index history",
    } for point in points]
    history["points"] = merge_points(valid, current)
    history["source"] = "SET Index history: Yahoo Finance plus TradingView SET:SET; official SET latest close"
    history["source_urls"] = [history["source_url"], SOURCE_URL, item["source_url"]]
    history["history_fetch_mode"] = mode
    history["market_session_date"] = session
    snapshot = payload.get("price_histories_v03", {}).get("SET")
    if snapshot:
        snapshot["points"] = [{"date": session, "value": float(item["metrics"]["latest"])}]
    for row in payload.get("top_watchlist_v03", []):
        if row.get("symbol") == "SET":
            row["as_of"] = session
    add_source_once(payload, {
        "name": "TradingView SET:SET daily history",
        "url": SOURCE_URL,
        "publication_date": f"Refresh {datetime.now().date().isoformat()} ({mode}); latest exchange session {session}",
        "used_for": "Source-backed recent SET daily observations and trading-date verification, cross-checked against the official SET latest close.",
    })
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "mode": mode, "session": session, "retained_points": len(history["points"])}))


if __name__ == "__main__":
    main()
