from __future__ import annotations

from pathlib import Path


HTML = Path("outputs/dashboard/index.html")
h = HTML.read_text(encoding="utf-8")

manifest = h.find("<h2>Source Manifest</h2>")
gaps = h.find("<h2>Source Gaps</h2>")
main_end = h.rfind("</main>")
ai = h.find('id="ai-semiconductor-direct"')

checks = {
    "manifest_exists": manifest != -1,
    "source_gaps_before_manifest": gaps != -1 and manifest != -1 and gaps < manifest,
    "manifest_before_main_end": manifest != -1 and main_end != -1 and manifest < main_end,
    "manifest_near_bottom": manifest != -1 and main_end != -1 and main_end - manifest < 30000,
    "ai_spacing_css": "layout-fix-v09:start" in h and "margin-bottom:64px" in h,
    "chart_viewbox_360": 'viewBox="0 0 720 360"' in h,
    "chart_height_360": "var height = 360;" in h,
    "bad_mojibake_absent": not any(token in h for token in ["????", "เธ", "เน", "โ€”"]),
    "ai_before_manifest": ai != -1 and manifest != -1 and ai < manifest,
}
for key, value in checks.items():
    print(key, value)
if not all(checks.values()):
    raise SystemExit("layout/order validation failed")
print("html_size", HTML.stat().st_size)
print("positions", {"ai": ai, "gaps": gaps, "manifest": manifest, "main_end": main_end})
