from __future__ import annotations

from pathlib import Path


HTML = Path("outputs/dashboard/index.html")
h = HTML.read_text(encoding="utf-8")


def has_mojibake(text: str) -> bool:
    if "????" in text or "โ€" in text or "เน€" in text:
        return True
    return any(0x80 <= ord(ch) <= 0x9F for ch in text)


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
    "bad_mojibake_absent": not has_mojibake(h),
    "ai_before_manifest": ai != -1 and manifest != -1 and ai < manifest,
}
for key, value in checks.items():
    print(key, value)
if not all(checks.values()):
    raise SystemExit("layout/order validation failed")
print("html_size", HTML.stat().st_size)
print("positions", {"ai": ai, "gaps": gaps, "manifest": manifest, "main_end": main_end})
