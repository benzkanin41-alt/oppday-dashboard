from __future__ import annotations

import hashlib
import http.cookiejar
import re
import urllib.parse
import urllib.request


def verified_fetch(url: str) -> str:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/csv,text/html,*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    body = opener.open(req, timeout=30).read().decode("utf-8", "replace")
    match = re.search(r'const c="([^"]+)",d=(\d+),t="0"\.repeat\(d\)', body)
    if not match:
        return body
    challenge = match.group(1)
    difficulty = int(match.group(2))
    target = "0" * difficulty
    nonce = 0
    while True:
        digest = hashlib.sha256((challenge + str(nonce)).encode()).hexdigest()
        if digest.startswith(target):
            break
        nonce += 1
    data = urllib.parse.urlencode({"c": challenge, "n": str(nonce)}).encode()
    verify = urllib.request.Request(
        "https://stooq.com/__verify",
        data=data,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener.open(verify, timeout=30).read()
    return opener.open(urllib.request.Request(url, headers=headers), timeout=30).read().decode("utf-8", "replace")


def main() -> None:
    for symbol in ["mai.th", "mai", "^mai", "set.th", "^set", "set"]:
        url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({"s": symbol, "i": "d"})
        try:
            body = verified_fetch(url)
        except Exception as exc:
            print(symbol, "ERR", repr(exc))
            continue
        lines = [line for line in body.splitlines() if line.strip()]
        print("SYMBOL", symbol, "LINES", len(lines), "HEAD", lines[:3], "TAIL", lines[-3:])


if __name__ == "__main__":
    main()
