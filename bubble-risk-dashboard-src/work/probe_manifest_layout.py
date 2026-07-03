from pathlib import Path

h = Path("outputs/dashboard/index.html").read_text(encoding="utf-8")
tokens = [
    "<h2>Source Manifest</h2>",
    "<h2>Source Gaps</h2>",
    'id="ai-semiconductor-direct"',
    "<main>",
    "</main>",
    "</body>",
]
for token in tokens:
    print(token, h.find(token))
idx = h.find("<h2>Source Manifest</h2>")
print("--- manifest ---")
print(h[max(0, idx - 300) : idx + 500] if idx != -1 else "not found")
idx = h.find("<h2>Source Gaps</h2>")
print("--- gaps ---")
print(h[max(0, idx - 200) : idx + 300] if idx != -1 else "not found")
