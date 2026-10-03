from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
AMZN_RAW = ROOT / "work" / "raw" / "ai_direct_v06" / "sec_companyfacts_AMZN.json"
START = date(2024, 7, 1)


def load_renderer():
    spec = importlib.util.spec_from_file_location("ai_direct_renderer", ROOT / "work" / "add_ai_semiconductor_direct_data.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def amzn_productive_assets_quarterly() -> list[dict]:
    data = json.loads(AMZN_RAW.read_text(encoding="utf-8"))
    return load_renderer().quarterly_cashflow(data, ["PaymentsToAcquireProductiveAssets"])


def main() -> None:
    renderer = load_renderer()
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    ai = payload["ai_semiconductor_direct_v06"]
    ai["capex"]["AMZN"] = amzn_productive_assets_quarterly()
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    html_text = HTML.read_text(encoding="utf-8")
    html_text = renderer.strip_marker(html_text, "ai-direct-section")
    macro_end = "<!-- v04-macro-section:end -->"
    section = renderer.render_section(ai)
    if macro_end in html_text:
        html_text = html_text.replace(macro_end, macro_end + "\n" + section, 1)
    else:
        html_text = html_text.replace("<main>", "<main>\n" + section, 1)
    HTML.write_text(html_text, encoding="utf-8")
    print(json.dumps({"AMZN": ai["capex"]["AMZN"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
