from urllib.request import Request,urlopen
from urllib.parse import urlencode
import json
headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Accept':'application/json, text/plain, */*','Origin':'https://www.nasdaq.com','Referer':'https://www.nasdaq.com/market-activity/etf/spy'}
for sym in ['SPY','QQQ','SMH']:
  params=urlencode({'assetclass':'etf','fromdate':'2006-07-02','todate':'2026-07-02','limit':'9999'})
  url=f'https://api.nasdaq.com/api/quote/{sym}/historical?{params}'
  data=urlopen(Request(url,headers=headers),timeout=60).read().decode('utf-8','replace')
  payload=json.loads(data)
  rows=(((payload.get('data') or {}).get('tradesTable') or {}).get('rows') or [])
  print(sym, len(rows), rows[-1]['date'] if rows else None, rows[0]['date'] if rows else None)
