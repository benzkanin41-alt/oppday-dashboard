---
name: bubble-risk-dashboard
description: Build source-backed bubble risk dashboards for macro, indices, sectors, sentiment, liquidity, and valuation risk. Use when the user asks for a bubble index, market heat map, fear/greed dashboard, or Howard Marks / Ray Dalio / Warren Buffett style cycle-risk monitor.
---

# Bubble Risk Dashboard

## Overview

Use this skill to build a source-backed dashboard that scores bubble risk across macro, stock indices, sectors/themes, sentiment, credit, liquidity, and valuation inputs. The default deliverable is a portable HTML dashboard plus JSON data and a source manifest.

## Workflow

1. Confirm the requested universe from the user message. If not specified, start with major index proxies, S&P 500 sectors, Nasdaq-related themes, FRED macro series, and explicit source-gap reporting.
2. Search for current sources before answering or building. Prefer primary sources: FRED, SEC EDGAR, BIS, exchange/index-provider methodology pages, central-bank sources, and documented market-data APIs.
3. Check whether a TradingView Remix MCP or other market-data MCP is callable in the current tool registry. If it is missing, record that as a source gap rather than inventing data.
4. Run or adapt `scripts/build_bubble_dashboard.py` in the active workspace. Set `BUBBLE_DASHBOARD_ROOT` to the target workspace when running the script from the installed skill folder.
5. Produce `outputs/dashboard/index.html`, `outputs/dashboard/data.json`, and `outputs/dashboard/source-manifest.json`.
6. Validate that the HTML exists, the JSON parses, score bands render, source gaps are visible, and the dashboard contains live data rather than placeholders.
7. In the final answer, summarize the score, data anchor date, source coverage, source gaps, and validation performed.

## Dashboard Standards

- Higher score means higher bubble/mania risk, not an automatic sell signal.
- Always show source gaps openly. Missing valuation, fundamentals, or licensed data should reduce confidence, not be hidden.
- Keep the first screen usable: overall score, band, main drivers, data confidence, and the most important heat indicators.
- Include sector expansion early. For S&P 500 use the 11 GICS sector ETF proxies first; for Nasdaq use theme proxies until constituent-level industry grouping is available.
- Do not rely on a single price-only indicator. Balance price heat with sentiment, credit, liquidity, fundamentals, and valuation.
- Avoid overstating precision. Scores are decision-support signals and should be treated as a dashboard, not a deterministic forecast.

## Reusable Commands

From a workspace that should receive the dashboard:

```powershell
$env:BUBBLE_DASHBOARD_ROOT = (Get-Location).Path
python C:\Users\USER\.codex\skills\bubble-risk-dashboard\scripts\build_bubble_dashboard.py
```

If the bundled Codex runtime is needed, use its Python path and keep `BUBBLE_DASHBOARD_ROOT` pointed at the active workspace.

## References

- `references/scoring-model.md` explains the component score model and interpretation.
- `references/source-catalog.md` lists preferred source adapters, source gaps, and expansion priorities.
- `scripts/build_bubble_dashboard.py` is the current portable HTML dashboard builder.

## v0.2 Thailand And Rates Extension

After running `scripts/build_bubble_dashboard.py`, run `scripts/enhance_dashboard_thailand_rates.py` when the user asks for Thailand, SET Index, mai Index, sovereign yield curves, or earnings yield gap. The extension adds official SET/mai latest snapshots, FRED U.S. 2Y/5Y/10Y/30Y Treasury curves, ThaiBMA Thailand 2Y/5Y/10Y/30Y government bond curves, and an earnings-yield-gap table.

Do not fabricate P/E or earnings yield. If a primary P/E source is not wired, show `n/a` and list the adapter as a source gap.

## v0.3 Interactive Valuation And Chart Extension

After running `scripts/build_bubble_dashboard.py`, run `scripts/enhance_dashboard_interactive_v03.py` when the user asks for trailing P/E, forward P/E, earnings-yield gap, SET/mai in Top Watchlist, interactive bond-yield charts, or interactive Top Watchlist price charts.

The extension adds:

- SET Index and mai Index in Top Watchlist.
- Earnings Yield Gap with separate Trailing P/E and Forward P/E columns.
- Earnings-yield-gap calculation from Trailing P/E only: `100 / trailing P/E - local 10Y sovereign yield`.
- U.S. and Thailand 2Y/5Y/10Y/30Y government yield history with 1M/3M/6M/1Y/5Y filters and point tooltips.
- Top Watchlist price charts with 1M/3M/6M/1Y/5Y filters and point tooltips.

Keep source gaps explicit. In the current adapter, FRED and ThaiBMA provide 20-year yield histories; Nasdaq's public historical quote endpoint may cap ETF price history below 20 years; SET historical Excel downloads can be blocked by web protection, so SET/mai may fall back to latest official SET snapshots until a licensed/session-based adapter is available.
