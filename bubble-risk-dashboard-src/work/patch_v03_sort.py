from pathlib import Path
p = Path('work/enhance_dashboard_interactive_v03.py')
s = p.read_text(encoding='utf-8')
s = s.replace('    return out\n\n\ndef nasdaq_history_20y', '    return sorted(out, key=lambda row: row[\'date\'])\n\n\ndef nasdaq_history_20y')
p.write_text(s, encoding='utf-8')
print('patched nasdaq sort')
