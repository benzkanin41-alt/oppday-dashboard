from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from patch_mai_tradingview_history import add_source_once
from retain_dashboard_history import correct_snapshot_date, merge_points
from tv_fetch_history import fetch_history
from thai_market_sessions import completed_daily_points, cached_completed_points, reconcile_quote, apply_reconciliation, QuoteMismatchError


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
RAW = ROOT / "work" / "raw" / "tradingview" / "SET_SET_daily.json"
SOURCE_URL = "https://www.tradingview.com/symbols/SET-SET/"


def verified_session(item: dict, points: list[dict]) -> str:
    reconcile_quote(item, points)
    return points[-1]["date"]


def normalize_snapshot(item: dict, points: list[dict]) -> str:
    apply_reconciliation(item, points)
    return points[-1]["date"]


def read_or_fetch(item: dict | None = None) -> tuple[list[dict], str]:
    try:
        points = completed_daily_points(fetch_history("SET:SET", 1000))
        if len(points) < 500:
            raise RuntimeError("SET daily history returned too few points")
        if item is not None:
            reconcile_quote(item, points)
        RAW.parent.mkdir(parents=True, exist_ok=True)
        temp = RAW.with_suffix(".json.tmp")
        temp.write_text(json.dumps({
            "source": "TradingView chart websocket",
            "symbol": "SET:SET",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 2,
            "completed_through": points[-1]["date"],
            "points": points,
        }, indent=2), encoding="utf-8")
        temp.replace(RAW)
        return points, "live"
    except QuoteMismatchError:
        raise
    except Exception as exc:
        if not RAW.exists():
            raise
        cached = json.loads(RAW.read_text(encoding="utf-8"))
        points = cached_completed_points(cached)
        if item is not None:
            reconcile_quote(item, points)
        return points, f"cached; last successful retrieval {cached.get('fetched_at', 'unknown')}; refresh failed: {exc}"


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    item = next(row for row in payload["indices"] if row["symbol"] == "SET")
    points, mode = read_or_fetch(item)
    session = normalize_snapshot(item, points)
    history = payload["price_histories_v04"]["SET"]
    stored = history.get("points", [])
    valid = []
    for point in stored:
        unverified = point.get("source_kind") in {"Unverified official SET overview snapshot", "Official SET latest close"}
        if point["date"] > session and unverified:
            # An overview snapshot appended upstream is not a dated daily close.
            correct_snapshot_date("SET", point, None, SOURCE_URL)
        else:
            valid.append(point)
    current = [{
        "date": point["date"], "value": point["value"],
        "source_url": SOURCE_URL, "source_kind": "TradingView daily SET Index history",
    } for point in points]
    history["points"] = merge_points(valid, current)
    apply_reconciliation(item, history["points"])
    session = history["points"][-1]["date"]
    history["source"] = "SET Index daily history: Yahoo Finance plus TradingView SET:SET; official quote separate"
    history["source_urls"] = [history["source_url"], SOURCE_URL, item["source_url"]]
    history["history_fetch_mode"] = mode
    history["market_session_date"] = session
    snapshot = payload.get("price_histories_v03", {}).get("SET")
    if snapshot:
        snapshot["points"] = [history["points"][-1]]
    for row in payload.get("top_watchlist_v03", []):
        if row.get("symbol") == "SET":
            row["as_of"] = item["as_of"]
    add_source_once(payload, {
        "name": "TradingView SET:SET daily history",
        "url": SOURCE_URL,
        "publication_date": f"Refresh {datetime.now().date().isoformat()} ({mode}); latest exchange session {session}",
        "used_for": f"Completed SET daily observations; official quote kept separate. Reconciliation: {item['quote_history_reconciliation']['state']}.",
    })
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "mode": mode, "session": session, "retained_points": len(history["points"])}))


if __name__ == "__main__":
    main()
