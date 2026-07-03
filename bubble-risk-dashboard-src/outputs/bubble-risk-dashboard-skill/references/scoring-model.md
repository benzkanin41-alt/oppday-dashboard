# Bubble Risk Dashboard Scoring Model

## Core Principle

Score each input from 0 to 100, where higher means hotter and more bubble-prone. The score is not a timing signal. It is a structured way to ask whether price, credit, liquidity, sentiment, and valuation are all pointing in the same speculative direction.

## Overall Score

Default v0.1 weights:

- Price heat: 30%
- S&P 500 sector heat: 23%
- Nasdaq/theme heat: 17%
- Sentiment: 12%
- Credit stress/complacency: 10%
- Macro liquidity and policy pressure: 8%

Use a direct weighted sum. Do not average already-weighted components again.

## Components

Price heat blends 1-year return, 3-year return, distance from the 200-day moving average, and 1-year drawdown recovery.

Sector and theme heat use the same price framework plus a smaller volume heat input. In early builds, sector/theme proxies are acceptable; later builds should replace them with constituent-level valuation and concentration.

Sentiment starts with VIX. Low VIX raises complacency heat; high VIX lowers bubble heat and raises fear/regime-stress interpretation.

Credit and liquidity combine high-yield option-adjusted spreads, 10Y-2Y yield curve, real policy proxy, and central-bank balance-sheet change.

Valuation should be added as a first-class component once EDGAR/index valuation feeds are available: trailing/forward P/E, EV/sales, free-cash-flow yield, earnings yield versus bonds, margin cycle, and dispersion.

## Banding

- 0-24: Fear / cheap watch
- 25-49: Normal
- 50-64: Warm
- 65-79: Frothy
- 80-89: Bubble risk
- 90-100: Mania

## Interpretation Lens

Howard Marks style: emphasize cycle temperature, risk appetite, credit availability, and whether investors are paying too much for optimistic expectations.

Ray Dalio style: emphasize liquidity, rates, debt/credit cycle pressure, policy constraints, and cross-asset confirmation.

Warren Buffett style: emphasize valuation discipline, owner earnings, cash yield versus interest rates, balance-sheet durability, and whether broad market prices imply unrealistic future returns.

## Earnings Yield Gap Extension

Earnings yield = 100 / P/E. Earnings yield gap = earnings yield minus the local 10-year sovereign yield, expressed in percentage points.

Only compute the gap when both inputs are source-backed: a primary P/E or valuation source for the index/sector and a local 10-year sovereign yield. If P/E is missing, preserve the row with `n/a` and state that the valuation adapter is pending.

### Trailing P/E And Forward P/E

Trailing P/E and Forward P/E must be displayed separately when both are available. Earnings yield is computed from Trailing P/E only. Forward P/E is useful context about market expectations, but it must not be used in the earnings-yield-gap formula unless the model is deliberately changed and labeled.
