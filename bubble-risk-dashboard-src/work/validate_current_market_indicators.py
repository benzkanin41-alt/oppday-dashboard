from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
LATEST = ROOT / "work" / "raw" / "current_market" / "latest_sources.json"


def indicator_map(payload: dict) -> dict:
    return {item.get("name"): item for item in payload.get("macro_v04", {}).get("indicators", [])}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    latest = json.loads(LATEST.read_text(encoding="utf-8"))
    indicators = indicator_map(payload)

    vix = indicators.get("VIX complacency")
    curve = indicators.get("Yield Curve 10Y-2Y")
    real_policy = indicators.get("Real Policy Proxy")

    require(vix is not None, "VIX complacency indicator missing")
    require(curve is not None, "Yield Curve 10Y-2Y indicator missing")
    require(real_policy is not None, "Real Policy Proxy indicator missing")

    require(vix.get("date") == latest["cboe_vix"]["date"], f"VIX stale: payload {vix.get('date')} vs source {latest['cboe_vix']['date']}")
    require(
        curve.get("date") == latest["treasury_curve_10y2y"]["date"],
        f"Yield curve stale: payload {curve.get('date')} vs source {latest['treasury_curve_10y2y']['date']}",
    )
    require(
        real_policy.get("date") == latest["real_policy_proxy"]["date"],
        f"Real policy stale: payload {real_policy.get('date')} vs source {latest['real_policy_proxy']['date']}",
    )
    require(vix.get("latest") is not None and vix.get("pct") is not None, "VIX value/percentile missing")
    require(curve.get("latest") is not None and curve.get("pct") is not None, "Yield-curve value/percentile missing")
    require(real_policy.get("latest") is not None and real_policy.get("pct") is not None, "Real-policy value/percentile missing")

    print(
        json.dumps(
            {
                "status": "ok",
                "vix": {"date": vix.get("date"), "latest": vix.get("latest")},
                "yield_curve_10y_2y": {"date": curve.get("date"), "latest": curve.get("latest")},
                "real_policy_proxy": {"date": real_policy.get("date"), "latest": real_policy.get("latest")},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
