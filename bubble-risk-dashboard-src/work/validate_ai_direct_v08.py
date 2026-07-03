from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "outputs" / "dashboard" / "index.html"
DATA_PATH = ROOT / "outputs" / "dashboard" / "data.json"
JS_PATH = ROOT / "work" / "ai_direct_v08_inline.js"


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    bad_tokens = ["เน€เธ", "เน€เธย", "เนโฌโ€", "????"]
    found = [token for token in bad_tokens if token in html]
    if found:
        raise SystemExit(f"Found bad text tokens in HTML: {found}")
    ai_pos = html.find('id="ai-semiconductor-direct"')
    chip_pos = html.find("AI Chip Bubble Risk")
    if not (chip_pos != -1 and ai_pos != -1 and chip_pos < ai_pos):
        raise SystemExit("AI direct section is not under AI Chip Bubble Risk")
    if "+<!-- ai-direct-css:end -->" in html:
        raise SystemExit("Found stray plus sign before ai-direct-css:end marker")
    model_match = re.search(
        r'<script id="ai-direct-data" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not model_match:
        raise SystemExit("Missing ai-direct-data")
    model = json.loads(model_match.group(1))
    if "ai_semiconductor_direct_v08" not in payload:
        raise SystemExit("Missing ai_semiconductor_direct_v08 in data.json")
    script_match = re.search(
        r"<script>\s*\(function\(\)\{.*?var dataEl = document\.getElementById\('ai-direct-data'\);.*?</script>",
        html,
        re.S,
    )
    if not script_match:
        raise SystemExit("Missing AI v08 inline script")
    JS_PATH.write_text(
        script_match.group(0).replace("<script>", "").replace("</script>", ""),
        encoding="utf-8",
    )
    print("html_size", HTML_PATH.stat().st_size)
    print("ai_position_ok", True)
    print("generated_at", model["generated_at"])
    for group in model["groups"]:
        points = sum(len(series["points"]) for series in group["series"])
        observations = len(group.get("observations", []))
        print("card", group["id"], "points", points, "observations", observations, "sparse", group.get("sparse"))
    for item in payload.get("source_failures", []):
        if item.get("source") in {"GPU rental dense historical API", "CoWoS monthly capacity history"}:
            print("source_gap", item["source"], item["status"])
    print("js_extract", JS_PATH)


if __name__ == "__main__":
    main()

