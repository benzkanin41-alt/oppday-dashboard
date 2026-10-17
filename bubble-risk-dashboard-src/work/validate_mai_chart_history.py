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
    session = indices.get("SET", {}).get("market_session_date")
    require(bool(session), "Verified SET exchange session is missing")
    require(bool(points) and points[-1]["date"] == session, f"mai history session differs from verified SET session {session}")
    official = indices.get("mai", {}).get("metrics", {}).get("latest")
    require(official is not None and abs(float(points[-1]["value"]) - float(official)) <= 0.011, "mai history and official latest close differ")


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
    require(len(chart_mai.get("points") or []) == len(points), "v03-data mai point count does not match payload")
    print(json.dumps({"status": "ok", "mai_points": len(points), "first": points[0]["date"], "last": points[-1]["date"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
