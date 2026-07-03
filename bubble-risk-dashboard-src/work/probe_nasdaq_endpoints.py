from urllib.request import Request, urlopen
base = 'https://api.nasdaq.com/api/quote/SPY/'
endpoints = ['financials?assetclass=etf','fundamentals?assetclass=etf','info?assetclass=etf','institutional-holdings?assetclass=etf','summary?assetclass=etf']
headers = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Accept':'application/json, text/plain, */*','Origin':'https://www.nasdaq.com','Referer':'https://www.nasdaq.com/market-activity/etf/spy'}
for ep in endpoints:
    try:
        data = urlopen(Request(base + ep, headers=headers), timeout=25).read().decode('utf-8','replace')
        print('---', ep, len(data), data[:1000].replace('\n', ' '))
    except Exception as e:
        print('ERR', ep, repr(e))
