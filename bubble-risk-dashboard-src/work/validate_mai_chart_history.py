from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
HTML = ROOT / "outputs" / "dashboard" / "index.html"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_session(payload: dict, points: list[dict]) -> None:
    indices = {item.get("symbol"): item for item in payload.get("indices", [])}
    item = indices.get("mai", {})
    state = item.get("quote_history_reconciliation", {})
    require(state.get("state") in {"matched_completed", "official_completed_extension", "session_unresolved", "history_lag", "intraday_not_close_comparable"}, "mai quote/history reconciliation missing")
    require(bool(points) and points[-1]["date"] == item.get("history_as_of"), "mai history date differs from disclosed history_as_of")
    require(abs(float(points[-1]["value"]) - float(item["history_latest"])) <= 0.011, "mai historical close differs from disclosed history_latest")
    if state["state"] == "matched_completed":
        comparable = next((point for point in points if point["date"] == item.get("quote_session_date")), None)
        require(comparable is not None and abs(float(comparable["value"]) - float(item["metrics"]["latest"])) <= 0.011, "mai verified completed-session close mismatch")


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    html = HTML.read_text(encoding="utf-8")
    mai = (payload.get("price_histories_v04") or {}).get("mai") or {}
    points = mai.get("points") or []
    require(mai.get("chart_symbol") == "SET:MAI", f"mai chart_symbol is {mai.get('chart_symbol')}")
    require(len(points) >= 1000, f"mai history has only {len(points)} points")
    require(points[0]["date"] <= "2005-01-01", f"mai history starts too late: {points[0]['date']}")
    verify_session(payload, points)
    require("mai Index - SET:MAI" in html, "HTML select label still does not show SET:MAI")
    match = re.search(r'<script id="v03-data" type="application/json">(.*?)</script>', html, re.S)
    require(match is not None, "v03-data script missing")
    chart_data = json.loads(match.group(1))
    chart_mai = (chart_data.get("priceSeries") or {}).get("mai") or {}
    require(chart_mai.get("chart_symbol") == "SET:MAI", "v03-data mai chart_symbol not SET:MAI")
    require(chart_mai.get("points") == points, "v03-data mai points do not exactly match payload")
    print(json.dumps({"status": "ok", "mai_points": len(points), "first": points[0]["date"], "last": points[-1]["date"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
