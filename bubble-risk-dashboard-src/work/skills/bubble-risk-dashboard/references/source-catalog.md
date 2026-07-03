# Source Catalog And Expansion Plan

## Live v0.1 Sources

FRED graph CSV / FRED API candidates:

- SP500: S&P 500 index history
- NASDAQCOM: Nasdaq Composite history
- VIXCLS: Cboe VIX close
- DGS10: US 10-year Treasury yield
- DGS2: US 2-year Treasury yield
- FEDFUNDS: Effective federal funds rate
- T10YIE: 10-year breakeven inflation rate
- BAMLH0A0HYM2: ICE BofA US High Yield Option-Adjusted Spread
- WALCL: Federal Reserve total assets

Nasdaq historical quote API:

- ETF proxy histories for indices, S&P 500 sectors, and Nasdaq-related themes.
- Keep raw JSON in `work/raw/nasdaq/` and cite the endpoint in the source manifest.

## Planned Primary Sources

SEC EDGAR:

- Use companyfacts and submissions to build constituent-level valuation, revenue growth, margin, buyback, dilution, leverage, and accrual signals.
- Aggregate by index and sector after mapping constituents.

BIS:

- CBPOL for central-bank policy rates.
- CBTA for central-bank total assets.
- Use for global rates/liquidity panels across US, Europe, Japan, China, India, and South Korea where available.

TradingView Remix MCP:

- Search the available tool registry first.
- If a callable market-data MCP exists, use it for global index prices, sector/index constituents, and cross-market chart data.
- If it is not exposed, record the gap explicitly.

Yahoo Finance / yfinance:

- Treat as a convenience fallback, not the sole source.
- Yahoo endpoints can rate-limit; record rate limits in `source_failures`.

Fear and Greed:

- Add an adapter only when a stable source is available.
- Prefer component-level inputs rather than a black-box headline number when possible.

## Universe Priority

Start with index-level coverage:

- US: S&P 500, Nasdaq 100, Russell 2000
- Europe: STOXX Europe 600, Euro Stoxx 50, DAX, CAC, FTSE 100
- Japan: Nikkei 225, TOPIX
- China/HK: CSI 300, Shanghai Composite, Hang Seng, Hang Seng Tech
- India: Nifty 50, Sensex
- South Korea: KOSPI, KOSDAQ
- Global: MSCI World / ACWI when licensing permits

Then expand:

- S&P 500 sectors via the 11 GICS sectors.
- Nasdaq 100 industry/theme groups: semiconductors, software, cloud, cybersecurity, biotech, consumer internet, platforms, and mega-cap concentration.
- Constituent-level valuation and concentration once EDGAR/index constituent mapping is available.
