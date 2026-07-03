from pathlib import Path
p = Path('work/enhance_dashboard_interactive_v03.py')
s = p.read_text(encoding='utf-8')
s = s.replace("    data_json = json.dumps(chart_data, ensure_ascii=False, separators=(',', ':'))\n", "    data_json = json.dumps(chart_data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')\n")
s = s.replace('<script id="v03-data" type="application/json">{html.escape(data_json)}</script>', '<script id="v03-data" type="application/json">{data_json}</script>')
p.write_text(s, encoding='utf-8')
print('patched json embedding')
