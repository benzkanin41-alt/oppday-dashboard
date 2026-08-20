from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"
MANIFEST = OUT / "source-manifest.json"
UPDATE_LOG = ROOT / "work" / "last_dashboard_update.json"


def fail(message: str) -> None:
    raise SystemExit(message)


for path in (DATA, HTML, MANIFEST, UPDATE_LOG):
    if not path.is_file() or path.stat().st_size == 0:
        fail(f"missing or empty required artifact: {path}")

payload = json.loads(DATA.read_text(encoding="utf-8"))
html = HTML.read_text(encoding="utf-8")
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
update_log = json.loads(UPDATE_LOG.read_text(encoding="utf-8"))

update_status = update_log.get("status")
if update_status not in {"ok", "running"}:
    fail(f"updater status is not valid: {update_status!r}")
if update_status == "running":
    completed_scripts = {
        step.get("script")
        for step in update_log.get("steps", [])
        if isinstance(step, dict) and step.get("returncode") == 0
    }
    if "work/validate_final_dashboard.py" not in completed_scripts:
        fail("in-process updater has not completed the final dashboard validation")

v04 = payload.get("price_histories_v04") or {}
v03 = payload.get("price_histories_v03") or {}
if not v04 or not v03:
    fail("price history payload is missing")

empty_v04 = sorted(symbol for symbol, series in v04.items() if not (series or {}).get("points"))
empty_v03 = sorted(symbol for symbol, series in v03.items() if not (series or {}).get("points"))
if empty_v04 or empty_v03:
    fail(f"empty payload price histories: v04={empty_v04}, v03={empty_v03}")

match = re.search(
    r'<script id="v03-data" type="application/json">(.*?)</script>',
    html,
    re.S,
)
if not match:
    fail("embedded v03-data payload is missing")
embedded = json.loads(match.group(1))
price_series = embedded.get("priceSeries") or {}
empty_embedded = sorted(
    symbol for symbol, series in price_series.items() if not (series or {}).get("points")
)
if not price_series or empty_embedded:
    fail(f"embedded priceSeries is missing or empty: {empty_embedded}")

data_sources = payload.get("sources") or []
if data_sources != manifest:
    fail(
        "source-manifest.json does not exactly match data.json sources "
        f"(data={len(data_sources)}, manifest={len(manifest)})"
    )
manifest_sections = len(re.findall(r"<h2>\s*Source Manifest\s*</h2>", html, re.I))
if manifest_sections != 1:
    fail(f"HTML must contain exactly one Source Manifest section; found {manifest_sections}")

year = datetime.now().year
treasury_url = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    f"pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
proc = subprocess.run(
    [
        "curl.exe",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--max-time",
        "90",
        treasury_url,
    ],
    cwd=ROOT,
    text=True,
    encoding="utf-8",
    errors="replace",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    timeout=100,
)
if proc.returncode != 0:
    fail(f"live U.S. Treasury XML fetch failed: {proc.stderr.strip()}")

treasury_dates = re.findall(r"<d:NEW_DATE[^>]*>(\d{4}-\d{2}-\d{2})", proc.stdout)
if not treasury_dates:
    fail("live U.S. Treasury XML contained no observation dates")
treasury_latest = max(treasury_dates)

us_curve = next(
    (curve for curve in payload.get("yield_curves", []) if curve.get("country") == "United States"),
    None,
)
if not us_curve:
    fail("United States yield curve is missing")
if us_curve.get("as_of") != treasury_latest:
    fail(
        "U.S. yield curve is behind the live Treasury XML: "
        f"dashboard={us_curve.get('as_of')}, treasury={treasury_latest}"
    )

summary = {
    "status": "ok",
    "updater_status": update_status,
    "updater_completed_at": update_log.get("completed_at"),
    "updater_updated_at": update_log.get("updated_at"),
    "v04_price_series": len(v04),
    "v03_price_series": len(v03),
    "embedded_price_series": len(price_series),
    "min_v04_points": min(len(series["points"]) for series in v04.values()),
    "min_v03_points": min(len(series["points"]) for series in v03.values()),
    "min_embedded_points": min(len(series["points"]) for series in price_series.values()),
    "treasury_xml_latest": treasury_latest,
    "dashboard_us_yield_as_of": us_curve.get("as_of"),
    "manifest_sources": len(manifest),
    "manifest_exact_match": True,
    "source_manifest_sections": manifest_sections,
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
