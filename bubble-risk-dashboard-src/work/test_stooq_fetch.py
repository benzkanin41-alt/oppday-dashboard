from __future__ import annotations

import hashlib
import re
import sys
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


def fetch(url: str) -> str:
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodexDashboard/0.1",
        "Accept": "text/csv,text/html,*/*",
    }
    body = opener.open(Request(url, headers=headers), timeout=20).read().decode("utf-8", errors="replace")
    if "__verify" not in body:
        return body

    c_match = re.search(r'const c="([^"]+)"', body)
    d_match = re.search(r",d=(\d+),", body)
    if not c_match or not d_match:
        raise RuntimeError("Could not parse Stooq browser verification challenge")
    c = c_match.group(1)
    d = int(d_match.group(1))
    prefix = "0" * d
    n = 0
    while True:
        digest = hashlib.sha256(f"{c}{n}".encode("utf-8")).hexdigest()
        if digest.startswith(prefix):
            break
        n += 1
    verify_data = urlencode({"c": c, "n": str(n)}).encode("ascii")
    opener.open(
        Request(
            "https://stooq.com/__verify",
            data=verify_data,
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://stooq.com",
                "Referer": url,
            },
            method="POST",
        ),
        timeout=20,
    ).read()
    return opener.open(Request(url, headers=headers), timeout=20).read().decode("utf-8", errors="replace")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://stooq.com/q/d/l/?s=xlk.us&i=d&d1=20210101&d2=20260702"
    print(fetch(target)[:1000])
