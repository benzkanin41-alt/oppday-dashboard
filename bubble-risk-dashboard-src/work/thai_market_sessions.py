from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


class QuoteMismatchError(RuntimeError):
    pass


def completed_daily_points(points: list[dict], today: str | None = None) -> list[dict]:
    today = today or (datetime.now(timezone.utc) + timedelta(hours=7)).date().isoformat()
    accepted = []
    previous = ""
    for point in points:
        day = point["date"]
        datetime.strptime(day, "%Y-%m-%d")
        value = float(point["value"])
        if day <= previous or not math.isfinite(value) or value <= 0 or day > today:
            raise ValueError("Invalid, unordered or future Thai daily observation")
        previous = day
        # A live daily candle is not a completed exchange-session close.
        if day < today:
            accepted.append(point)
    return accepted


def cached_completed_points(cache: dict) -> list[dict]:
    fetched_at = cache.get("fetched_at")
    if fetched_at:
        retrieved = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if retrieved.tzinfo is None:
            retrieved = retrieved.replace(tzinfo=timezone.utc)
        cutoff = (retrieved.astimezone(timezone.utc) + timedelta(hours=7)).date().isoformat()
        points = completed_daily_points(cache.get("points") or [], cutoff)
    else:
        # A legacy trailing candle with no retrieval evidence is not a final close.
        points = completed_daily_points(cache.get("points") or [])[:-1]
    watermark = cache.get("completed_through")
    return [point for point in points if not watermark or point["date"] <= watermark]


def reconcile_quote(item: dict, points: list[dict]) -> dict:
    if not points:
        raise RuntimeError("Thai completed daily history is empty")
    history_day = points[-1]["date"]
    session = item.get("quote_session_date")
    state = "session_unresolved"
    if session and item.get("quote_is_final"):
        comparable = next((point for point in points if point["date"] == session), None)
        if comparable is not None:
            if abs(float(comparable["value"]) - float(item["metrics"]["latest"])) > 0.011:
                raise QuoteMismatchError("Thai daily close disagrees with the official completed-session quote")
            state = "official_completed_extension" if comparable.get("source_kind") == "Official SET verified completed-session close" else "matched_completed"
        elif session > history_day:
            state = "history_lag"
    elif session:
        state = "intraday_not_close_comparable"
    return {"state": state, "history_as_of": history_day,
            "history_latest": float(points[-1]["value"]),
            "quote_session_date": session,
            "note": "Daily history and official quote are separate; page-update time is not evidence of the quote's trading session."}


def apply_reconciliation(item: dict, points: list[dict]) -> dict:
    status = reconcile_quote(item, points)
    item["quote_history_reconciliation"] = status
    item["history_as_of"] = status["history_as_of"]
    item["history_latest"] = status["history_latest"]
    if status["state"] in {"matched_completed", "official_completed_extension"}:
        item["market_session_date"] = item["quote_session_date"]
    else:
        item.pop("market_session_date", None)
    return status
