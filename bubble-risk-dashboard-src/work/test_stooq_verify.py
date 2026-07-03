from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.parse import urlencode
from http.cookiejar import CookieJar
import re, hashlib

cj = CookieJar()
opener = build_opener(HTTPCookieProcessor(cj))
headers = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
url = 'https://stooq.com/q/d/l/?s=spy.us&i=d&d1=20060702&d2=20260702'
resp = opener.open(Request(url, headers=headers), timeout=25).read().decode('utf-8','replace')
print('first', len(resp), resp[:80])
if 'requires JavaScript' in resp:
    c = re.search(r'const c="([^"]+)"', resp).group(1)
    d = int(re.search(r'd=(\d+)', resp).group(1))
    pref = '0'*d
    n = 0
    while True:
        h = hashlib.sha256((c + str(n)).encode()).hexdigest()
        if h.startswith(pref):
            break
        n += 1
    body = urlencode({'c': c, 'n': str(n)}).encode()
    verify_headers = {'User-Agent': headers['User-Agent'], 'Content-Type':'application/x-www-form-urlencoded', 'Referer':'https://stooq.com/'}
    v = opener.open(Request('https://stooq.com/__verify', data=body, headers=verify_headers), timeout=25)
    print('verify', v.status, n)
    resp = opener.open(Request(url, headers=headers), timeout=25).read().decode('utf-8','replace')
print('second', len(resp), resp[:300])
