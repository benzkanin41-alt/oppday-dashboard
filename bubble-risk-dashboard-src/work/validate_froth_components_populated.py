from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"

payload = json.loads(DATA.read_text(encoding="utf-8"))
indicators = (payload.get("macro_v04") or {}).get("indicators") or []
missing = [
    item.get("name", "<unnamed>")
    for item in indicators
    if item.get("latest") is None or not item.get("date") or not item.get("spark")
]

if len(indicators) < 7:
    raise SystemExit(f"expected at least 7 Froth Components, found {len(indicators)}")
if missing:
    raise SystemExit(f"Froth Components still missing live values: {missing}")

html_text = HTML.read_text(encoding="utf-8")
section_start = html_text.find("Froth Gauge - Components")
section_end = html_text.find("AI Chip Bubble Risk", section_start)
section = html_text[section_start:section_end if section_end > section_start else None]
if section.count(">n/a<") >= 7:
    raise SystemExit("Froth Components HTML still appears to show n/a for all rows")

print(
    "froth_components",
    {
        item["name"]: {
            "latest": item.get("latest"),
            "date": item.get("date"),
            "pct": item.get("pct"),
        }
        for item in indicators
    },
)
