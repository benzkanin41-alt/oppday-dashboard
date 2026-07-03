from pathlib import Path

h = Path("outputs/dashboard/index.html").read_text(encoding="utf-8")
tokens = [
    "AI Chip Bubble Risk",
    'id="ai-semiconductor-direct"',
    '<section class="sources">',
    '<section class="v04-dark">',
]
for token in tokens:
    print(token, h.find(token))
chip = h.find("AI Chip Bubble Risk")
ai = h.find('id="ai-semiconductor-direct"')
print("--- chip ---")
print(h[max(0, chip - 200) : chip + 400])
print("--- ai ---")
print(h[max(0, ai - 160) : ai + 240])
