from pathlib import Path
import json
import html
import re

out = Path('outputs/dashboard')
sources = json.loads((out / 'source-manifest.json').read_text(encoding='utf-8'))
rows = '\n'.join(
    f'<tr><td>{html.escape(s["name"])}</td><td>{html.escape(s["used_for"])}</td><td>{html.escape(s["publication_date"])}</td><td><a href="{html.escape(s["url"])}">source</a></td></tr>'
    for s in sources
)
p = out / 'index.html'
text = p.read_text(encoding='utf-8')
pattern = r'(<h2>Source Manifest</h2>\s*<table>\s*<thead><tr><th>Source</th><th>Used For</th><th>Publication / Access Date</th><th>Link</th></tr></thead>\s*)<tbody>.*?</tbody>'
new = re.sub(pattern, r'\1<tbody>' + rows + '</tbody>', text, flags=re.S)
if new == text:
    raise SystemExit('source manifest table not patched')
p.write_text(new, encoding='utf-8')
print('source manifest rows', len(sources))
