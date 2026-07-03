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

## Live v0.2 Thailand And Yield-Curve Extension

SET official pages:

- SET Index overview: latest SET Index level and daily change snapshot.
- mai Index overview: latest mai Index level and daily change snapshot.
- Treat these as latest snapshots until a historical/valuation adapter from SETSMART, TradingView, or another licensed primary source is available.

ThaiBMA:

- Government Bond Yield Curve: Thailand 2Y, 5Y, 10Y, and 30Y government bond yield history and latest rates.
- Keep raw API downloads in `work/raw/thaibma/`.

FRED Treasury curve:

- DGS2, DGS5, DGS10, and DGS30 for U.S. 2Y, 5Y, 10Y, and 30Y Treasury yield charts.

Coverage gaps to keep visible:

- Europe, Japan, China/HK, India, and South Korea still need primary 2Y/5Y/10Y/30Y curve adapters.
- Earnings yield gap needs primary P/E data before computing the gap; show `n/a` rather than estimating.

## Live v0.3 Interactive Thailand, Valuation, And Charts Extension

SET official pages:

- SET Market Overview supplies latest SET and mai trailing P/E, P/BV, market yield, index EPS, index levels, and market statistics snapshots.
- SET Market Statistics lists long-run Market Index and P/E monthly files from Apr 1975 to present, but direct Excel download can be blocked by web protection in automated runs. Record this as a source gap and do not fabricate historical SET/mai prices or valuation.

Valuation:

- Separate Trailing P/E and Forward P/E in the dashboard.
- Use Trailing P/E only for earnings-yield-gap calculations.
- Forward P/E is display-only unless a source-backed adapter is wired.

Interactive chart coverage:

- FRED DGS2, DGS5, DGS10, and DGS30 provide U.S. 2Y/5Y/10Y/30Y daily Treasury history.
- ThaiBMA Government Bond Yield Curve interpolation provides Thailand 2Y/5Y/10Y/30Y history.
- Nasdaq historical quote API provides ETF proxy price-history charts, but the public endpoint may cap history below the requested 20-year window. Show the actual first and last dates in validation notes.
