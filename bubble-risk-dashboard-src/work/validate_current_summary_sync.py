from __future__ import annotations

import json
import math
from pathlib import Path

from sync_latest_dashboard_summary import indicator_map, synchronize_payload


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"


def close(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    page = HTML.read_text(encoding="utf-8")
    indicators = indicator_map(payload)
    macro = payload["macro"]
    overall = payload["overall"]

    pairs = (
        ("VIX complacency", "vix", "vix_as_of"),
        ("High Yield OAS", "hy_oas", "hy_oas_as_of"),
        ("Yield Curve 10Y-2Y", "yield_curve_10y_2y", "yield_curve_as_of"),
        ("Real Policy Proxy", "real_policy_proxy", "real_policy_as_of"),
        ("Fed Assets YoY", "fed_assets_1y_change", "fed_assets_as_of"),
    )
    for indicator_name, value_key, date_key in pairs:
        indicator = indicators[indicator_name]
        assert close(macro[value_key], indicator["latest"]), (indicator_name, value_key)
        assert macro[date_key] == indicator["date"], (indicator_name, date_key)

    expected = json.loads(json.dumps(payload))
    result = synchronize_payload(expected)
    assert close(overall["score"], expected["overall"]["score"])
    assert overall["band"] == expected["overall"]["band"]
    assert overall["driver"] == expected["overall"]["driver"]
    assert payload["generated_at"] in page
    assert payload["data_anchor"] in page
    assert f"VIX {macro['vix']:.1f} as of {macro['vix_as_of']}" in page
    assert f"{macro['fed_assets_1y_change']:+.1f}%" in page
    assert f'<div class="score-big">{overall["score"]:.0f}</div>' in page
    assert f'<div class="band">{overall["band"]}</div>' in page

    print(
        json.dumps(
            {
                "status": "ok",
                "generated_at": payload["generated_at"],
                "data_anchor": payload["data_anchor"],
                "overall_score": overall["score"],
                "overall_band": overall["band"],
                "vix": macro["vix"],
                "vix_as_of": macro["vix_as_of"],
                "fed_assets_yoy": macro["fed_assets_1y_change"],
                "fed_assets_as_of": macro["fed_assets_as_of"],
                "chip_score": result["chip_score"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
