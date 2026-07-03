from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
HTML = ROOT / "outputs" / "dashboard" / "index.html"


payload = json.loads(DATA.read_text(encoding="utf-8"))
html = HTML.read_text(encoding="utf-8")
macro = payload.get("macro_v04") or {}
scores = macro.get("scores") or {}
required = ["froth", "recession", "debt", "chip", "chip1", "chip2", "chip3"]
missing = [key for key in required if scores.get(key) is None]
zeros = [key for key in required if scores.get(key) == 0]
indicators = macro.get("indicators") or []

if missing or zeros:
    raise SystemExit(f"macro_v04 scores invalid; missing={missing}; zeros={zeros}; scores={scores}")
if len(indicators) < 5:
    raise SystemExit(f"macro_v04 indicators too few: {len(indicators)}")

section = re.search(r"<!-- v04-macro-section:start -->(.*?)<!-- v04-macro-section:end -->", html, re.S)
if not section:
    raise SystemExit("v04 macro section missing from HTML")
section_html = section.group(1)
for label in ["Froth / Bubble Gauge", "Recession-Risk Gauge", "Long-Term Debt Cycle", "AI Chip Bubble Risk"]:
    if label not in section_html:
        raise SystemExit(f"macro section missing label: {label}")
if re.search(r'<div class="v04-score">0</div>', section_html):
    raise SystemExit("macro section still contains a 0 gauge score")

print("macro_v04_scores", scores)
print("macro_v04_indicators", len(indicators))
