from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "outputs" / "dashboard" / "index.html"
DATA_PATH = ROOT / "outputs" / "dashboard" / "data.json"
JS_PATH = ROOT / "work" / "ai_direct_inline.js"


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if "????" in html:
        raise SystemExit("Found question-mark mojibake in HTML")
    bad_tokens = ["เธ", "เน", "โ€”"]
    found_bad = [token for token in bad_tokens if token in html]
    if found_bad:
        raise SystemExit(f"Found mojibake tokens: {found_bad}")
    if "ai_semiconductor_direct_v08" not in data:
        raise SystemExit("Missing ai_semiconductor_direct_v08 in data.json")
    model_match = re.search(
        r'<script id="ai-direct-data" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not model_match:
        raise SystemExit("Missing ai-direct-data script")
    model = json.loads(model_match.group(1))
    script_match = re.search(
        r'<script>\s*\(function\(\)\{\s*var dataEl = document\.getElementById\(\'ai-direct-data\'\);.*?</script>',
        html,
        re.S,
    )
    if not script_match:
        raise SystemExit("Missing AI direct interactive script")
    if model.get("generated_at") != data["ai_semiconductor_direct_v08"].get("generated_at"):
        raise SystemExit("Embedded AI model is not aligned with data.json v08")
    rows = [
        (
            group["id"],
            sum(len(series["points"]) for series in group["series"]),
            len(group.get("observations", [])),
            group["badge"],
        )
        for group in model["groups"]
    ]
    print("html_size", HTML_PATH.stat().st_size)
    print("window", model["window_start"], model["window_end"])
    print("cards", len(model["groups"]))
    for row in rows:
        print("card", row[0], "points", row[1], "observations", row[2], "badge", row[3])
    print("interactive_script_chars", len(script_match.group(0)))


if __name__ == "__main__":
    main()
