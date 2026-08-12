from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "work" / "raw" / "ai_direct_v06"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
HTML = ROOT / "outputs" / "dashboard" / "index.html"
MANIFEST = ROOT / "outputs" / "dashboard" / "source-manifest.json"
ADAPTER = ROOT / "work" / "add_ai_semiconductor_direct_data.py"
UA = "Codex bubble-risk-dashboard contact: user@example.com"

CIKS = {
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "AMZN": "0001018724",
    "ORCL": "0001341439",
    "CRWV": "0001769628",
    "MU": "0000723125",
}


def fetch_companyfacts(ticker: str, cik: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    raw = urlopen(request, timeout=45).read()
    data = json.loads(raw.decode("utf-8"))
    if not data.get("facts") or str(data.get("cik", "")).zfill(10) != cik:
        raise RuntimeError(f"invalid SEC Company Facts response for {ticker}")
    return data


def load_adapter():
    spec = importlib.util.spec_from_file_location("ai_direct_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    fetched: list[str] = []
    cache_fallback: list[str] = []
    errors: dict[str, str] = {}

    for ticker, cik in CIKS.items():
        path = RAW / f"sec_companyfacts_{ticker}.json"
        try:
            data = fetch_companyfacts(ticker, cik)
            temp = path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(data), encoding="utf-8")
            temp.replace(path)
            fetched.append(ticker)
        except Exception as exc:
            errors[ticker] = str(exc)
            if path.is_file() and path.stat().st_size:
                cache_fallback.append(ticker)
            else:
                raise RuntimeError(f"SEC fetch failed with no cache for {ticker}: {exc}") from exc

    adapter = load_adapter()
    adapter.main()

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    access_date = datetime.now().date().isoformat()
    for source in payload.get("sources", []):
        if source.get("name") == "SEC Company Facts API":
            source["publication_date"] = f"Data fetched {access_date}"
            if cache_fallback:
                source["publication_date"] += f"; cache fallback: {', '.join(cache_fallback)}"

    if cache_fallback:
        payload.setdefault("source_failures", []).append(
            {
                "source": "SEC Company Facts API refresh",
                "status": "Live refresh failed for "
                + ", ".join(cache_fallback)
                + "; retained the last non-empty cache.",
            }
        )

    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST.write_text(json.dumps(payload.get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")
    html_text = adapter.patch_source_manifest_table(
        HTML.read_text(encoding="utf-8"), payload.get("sources", [])
    )
    HTML.write_text(html_text, encoding="utf-8")

    refresh_status = {
        "refreshed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S local"),
        "fetched": fetched,
        "cache_fallback": cache_fallback,
        "errors": errors,
    }
    (RAW / "refresh_status.json").write_text(
        json.dumps(refresh_status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"status": "ok", **refresh_status}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
