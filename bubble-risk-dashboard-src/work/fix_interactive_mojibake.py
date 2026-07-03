from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"


def recover(segment: str) -> str:
    # The v04 generator inherited Thai strings that were UTF-8 bytes decoded as cp874.
    # Ignore a few already-correct non-cp874 glyphs (mostly em dashes) so the Thai text recovers.
    return segment.encode("cp874", errors="ignore").decode("utf-8", errors="ignore")


text = HTML.read_text(encoding="utf-8")
start = "<!-- v03-interactive-section:start -->"
end = "<!-- v03-interactive-section:end -->"
if start not in text or end not in text:
    raise SystemExit("interactive marker not found")
a = text.index(start)
b = text.index(end, a) + len(end)
text = text[:a] + recover(text[a:b]) + text[b:]
HTML.write_text(text, encoding="utf-8")
print("interactive mojibake fixed")
