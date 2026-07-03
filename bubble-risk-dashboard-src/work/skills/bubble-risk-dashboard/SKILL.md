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
