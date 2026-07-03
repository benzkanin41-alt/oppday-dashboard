from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def fetch(url: str, timeout: int = 30) -> tuple[int, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/csv,text/plain,text/html,*/*",
            "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(5000000).decode("utf-8", "replace")
            return resp.status, resp.headers.get("content-type", ""), body
    except Exception as exc:
        return 0, type(exc).__name__, str(exc)


def probe_yahoo(symbol: str) -> dict:
    period2 = int(datetime(2026, 7, 4, tzinfo=timezone.utc).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol, safe="")
        + f"?period1=946684800&period2={period2}&interval=1d&events=history"
    )
    status, ctype, body = fetch(url)
    out = {"kind": "yahoo", "symbol": symbol, "status": status, "ctype": ctype, "url": url}
    try:
        data = json.loads(body)
        result = (data.get("chart", {}).get("result") or [{}])[0]
        ts = result.get("timestamp") or []
        closes = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
        meta = result.get("meta", {})
        out.update({"points": len([x for x in closes if x is not None]), "first_ts": ts[0] if ts else None, "last_ts": ts[-1] if ts else None, "meta_symbol": meta.get("symbol"), "currency": meta.get("currency")})
    except Exception as exc:
        out.update({"error": repr(exc), "sample": body[:300]})
    return out


def probe_stooq(symbol: str) -> dict:
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({"s": symbol, "i": "d"})
    status, ctype, body = fetch(url)
    lines = [line for line in body.splitlines() if line.strip()]
    return {"kind": "stooq", "symbol": symbol, "status": status, "ctype": ctype, "lines": len(lines), "head": lines[:3], "tail": lines[-3:], "url": url}


def probe_set_page() -> dict:
    url = "https://www.set.or.th/en/market/index/mai/overview"
    status, ctype, body = fetch(url)
    snippets = sorted(set(re.findall(r"/api/[^\"'<> ]{1,180}", body)))[:40]
    return {"kind": "set_page", "status": status, "ctype": ctype, "api_snippets": snippets[:20], "has_next": "__NEXT_DATA__" in body, "url": url}


def probe_set_api(url: str) -> dict:
    status, ctype, body = fetch(url)
    return {"kind": "set_api", "status": status, "ctype": ctype, "url": url, "sample": body[:500].replace("\n", " ")}


def main() -> None:
    urls = [
        "https://www.set.or.th/api/set/index/MAI/historical-trading?lang=en&fromDate=01/07/2024&toDate=03/07/2026",
        "https://www.set.or.th/api/set/index/mai/historical-trading?lang=en&fromDate=01/07/2024&toDate=03/07/2026",
        "https://www.set.or.th/api/set/index/MAI/chart-quotation?lang=en&period=5Y",
        "https://www.set.or.th/api/set/index/MAI/overview?lang=en",
        "https://www.set.or.th/api/set/stock/MAI/historical-trading?lang=en&fromDate=01/07/2024&toDate=03/07/2026",
    ]
    results = []
    for symbol in ["^MAI.BK", "MAI.BK", "^MAI", "MAI"]:
        results.append(probe_yahoo(symbol))
    for symbol in ["mai.th", "^mai", "mai", "mai.bk", "set.th", "^set"]:
        results.append(probe_stooq(symbol))
    results.append(probe_set_page())
    for url in urls:
        results.append(probe_set_api(url))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
