from pathlib import Path
import re


HTML = Path("outputs/dashboard/index.html")
h = HTML.read_text(encoding="utf-8")

h = h.replace(
    '<section class="ai-direct" id="ai-semiconductor-direct">',
    '<section class="ai-direct" id="ai-semiconductor-direct" style="margin-bottom:64px;padding-bottom:28px;clear:both;">',
)

h = re.sub(r'\n?<div class="after-ai-spacer"[^>]*></div>\n?', "\n", h)
marker = "<!-- v04-macro-section:end -->"
if marker in h:
    h = h.replace(
        marker,
        marker + '\n<div class="after-ai-spacer" aria-hidden="true" style="height:84px;clear:both;"></div>',
        1,
    )

HTML.write_text(h, encoding="utf-8")
print("inserted spacer between AI direct section and score tiles")
