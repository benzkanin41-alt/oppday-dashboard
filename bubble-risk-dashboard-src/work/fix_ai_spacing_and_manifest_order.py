from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "outputs" / "dashboard" / "index.html"
RENDERER_PATH = ROOT / "work" / "rebuild_ai_direct_layout_v08.py"

LAYOUT_CSS = """
<!-- layout-fix-v09:start -->
.ai-direct{margin-bottom:64px!important;padding-bottom:28px!important;clear:both}
.ai-direct:after{content:"";display:block;clear:both}
.ai-grid-cards{align-items:start!important;margin-bottom:24px!important}
.ai-card{align-self:start!important}
.ai-chart-svg{min-height:310px!important}
.ai-selected-detail{margin-top:18px!important}
.ai-small-table{margin-top:18px!important}
.ai-direct + .section,.ai-direct + section,.ai-direct + .score-grid,.ai-direct + .grid{margin-top:52px!important}
<!-- layout-fix-v09:end -->
"""


def strip_marker(text: str, marker: str) -> str:
    return re.sub(
        rf"\n?<!-- {re.escape(marker)}:start -->.*?<!-- {re.escape(marker)}:end -->\n?",
        "\n",
        text,
        flags=re.S,
    )


def move_source_manifest_to_bottom(html: str) -> str:
    heading = "<h2>Source Manifest</h2>"
    idx = html.find(heading)
    if idx == -1:
        return html
    start = html.rfind("<section", 0, idx)
    end = html.find("</section>", idx)
    if start == -1 or end == -1:
        return html
    end += len("</section>")
    section = html[start:end].strip()
    html = html[:start] + html[end:]
    main_end = html.rfind("</main>")
    if main_end == -1:
        body_end = html.rfind("</body>")
        main_end = body_end if body_end != -1 else len(html)
    return html[:main_end].rstrip() + "\n\n" + section + "\n" + html[main_end:]


def patch_html() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    html = strip_marker(html, "layout-fix-v09")
    html = html.replace("</style>", LAYOUT_CSS + "\n</style>", 1)
    html = html.replace('viewBox="0 0 720 330"', 'viewBox="0 0 720 360"')
    html = html.replace("var height = 330;", "var height = 360;")
    html = html.replace("var margin = {left: 54, right: 22, top: 22, bottom: 70};", "var margin = {left: 54, right: 22, top: 22, bottom: 90};")
    html = html.replace("var railY = height - 43;", "var railY = height - 48;")
    html = html.replace("y: height - 12", "y: height - 14")
    html = move_source_manifest_to_bottom(html)
    HTML_PATH.write_text(html, encoding="utf-8")


def patch_renderer() -> None:
    text = RENDERER_PATH.read_text(encoding="utf-8")
    text = text.replace('viewBox="0 0 720 330"', 'viewBox="0 0 720 360"')
    text = text.replace("var height = 330;", "var height = 360;")
    text = text.replace("var margin = {left: 54, right: 22, top: 22, bottom: 70};", "var margin = {left: 54, right: 22, top: 22, bottom: 90};")
    text = text.replace("var railY = height - 43;", "var railY = height - 48;")
    text = text.replace("y: height - 12", "y: height - 14")
    text = text.replace(
        ".ai-direct{background:#0f1520;color:#eef3fb;border:1px solid #273247;border-radius:8px;margin-top:14px;padding:18px}",
        ".ai-direct{background:#0f1520;color:#eef3fb;border:1px solid #273247;border-radius:8px;margin-top:14px;margin-bottom:64px;padding:18px 18px 28px;clear:both}",
    )
    text = text.replace(".ai-grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px}", ".ai-grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px;align-items:start;margin-bottom:24px}")
    text = text.replace(".ai-chart-svg{display:block;width:100%;height:auto;min-height:280px}", ".ai-chart-svg{display:block;width:100%;height:auto;min-height:310px}")
    RENDERER_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    patch_html()
    patch_renderer()
    print("patched AI chart spacing and moved Source Manifest to the bottom")


if __name__ == "__main__":
    main()
