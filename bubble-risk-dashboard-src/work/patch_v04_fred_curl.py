from pathlib import Path


path = Path("work/enhance_dashboard_v04.py")
text = path.read_text(encoding="utf-8")

if "import subprocess" not in text:
    text = text.replace("import re\nimport time\n", "import re\nimport subprocess\nimport time\n")

old = '''def fred_series(series_id: str, start: date = START_1990) -> list[dict]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    raw = request_text(url, {"User-Agent": UA, "Accept": "text/csv"})
    out_dir = RAW / "fred_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{series_id}.csv").write_text(raw, encoding="utf-8")
    rows = []
'''

new = '''def fred_series(series_id: str, start: date = START_1990) -> list[dict]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    out_dir = RAW / "fred_v04"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / f"{series_id}.csv"
    try:
        proc = subprocess.run(
            ["curl.exe", "-L", "--silent", "--show-error", "--max-time", "45", url],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        raw = proc.stdout
        if "observation_date" not in raw[:200]:
            raise RuntimeError(f"unexpected FRED CSV header for {series_id}")
        cache.write_text(raw, encoding="utf-8")
    except Exception:
        if cache.exists() and cache.stat().st_size > 100:
            raw = cache.read_text(encoding="utf-8", errors="replace")
        else:
            raw = request_text(url, {"User-Agent": UA, "Accept": "text/csv"}, timeout=20)
            cache.write_text(raw, encoding="utf-8")
    rows = []
'''

if old not in text:
    raise SystemExit("original fred_series block not found")

text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("patched_v04_fred_curl")
