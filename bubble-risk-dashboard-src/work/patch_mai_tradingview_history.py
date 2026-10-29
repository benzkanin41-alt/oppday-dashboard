from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from thai_market_sessions import completed_daily_points, cached_completed_points, reconcile_quote, apply_reconciliation, QuoteMismatchError
from retain_dashboard_history import load_archive, merge_points, filter_quarantined


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
HTML = OUT / "index.html"
RAW_TV = ROOT / "work" / "raw" / "tradingview" / "SET_MAI_daily.json"
TV_SOURCE_URL = "https://www.tradingview.com/symbols/SET-MAI/"
SYMBOL = "SET:MAI"
RANGES = [("1M", 31), ("3M", 93), ("6M", 186), ("1Y", 366), ("5Y", 366 * 5), ("10Y", 366 * 10), ("MAX", None)]


def load_tv_fetcher():
    spec = importlib.util.spec_from_file_location("tv_fetch_history", ROOT / "work" / "tv_fetch_history.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def add_source_once(payload: dict, source: dict) -> None:
    sources = payload.setdefault("sources", [])
    key = (source.get("name"), source.get("url"))
    for item in sources:
        if (item.get("name"), item.get("url")) == key:
            item.update(source)
            return
    sources.append(source)


def remove_stale_mai_failures(payload: dict) -> None:
    failures = payload.setdefault("source_failures", [])
    stale_terms = (
        "mai long-run price history",
        "mai historical daily index prices",
    )
    payload["source_failures"] = [
        item
        for item in failures
        if not any(term in str(item.get("source") or item.get("name") or "").lower() for term in stale_terms)
    ]
    if not any((item.get("source") == "SET direct mai historical API") for item in payload["source_failures"]):
        payload["source_failures"].append(
            {
                "source": "SET direct mai historical API",
                "status": "Direct SET historical API remained blocked in this run; Top Watchlist mai chart uses TradingView SET:MAI daily history with SET as the underlying exchange source.",
            }
        )


def read_or_fetch_points(item: dict | None = None) -> tuple[list[dict], dict]:
    attempted = datetime.now(timezone.utc).isoformat()
    try:
        mod = load_tv_fetcher()
        points = completed_daily_points(mod.fetch_history(SYMBOL, 10000))
        if len(points) < 1000:
            raise RuntimeError(f"TradingView SET:MAI returned too few points: {len(points)}")
        if item is not None:
            reconcile_quote(item, points)
        RAW_TV.parent.mkdir(parents=True, exist_ok=True)
        temp = RAW_TV.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(
                {
                    "source": "TradingView chart websocket",
                    "symbol": SYMBOL,
                    "fetched_at": attempted,
                    "schema_version": 2,
                    "completed_through": points[-1]["date"],
                    "points": points,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temp.replace(RAW_TV)
        return points, {"mode": "live", "fetched_at": attempted, "attempted_at": attempted}
    except QuoteMismatchError:
        raise
    except Exception as exc:
        if RAW_TV.exists() and RAW_TV.stat().st_size > 1000:
            payload = json.loads(RAW_TV.read_text(encoding="utf-8"))
            points = cached_completed_points(payload)
            if item is not None:
                reconcile_quote(item, points)
            return points, {"mode": "cache", "fetched_at": payload.get("fetched_at"), "attempted_at": attempted, "error": str(exc)}
        raise


def verify_official_close(item: dict, points: list[dict]) -> None:
    apply_reconciliation(item, points)


def compute_price_metrics(points: list[dict]) -> dict:
    points = [p for p in points if p.get("value") is not None]
    if not points:
        return {}
    latest = float(points[-1]["value"])
    ret_1y = None
    if len(points) > 252:
        base = float(points[-253]["value"])
        if base:
            ret_1y = (latest / base - 1) * 100
    dist_200dma = None
    if len(points) >= 200:
        ma = sum(float(p["value"]) for p in points[-200:]) / 200
        if ma:
            dist_200dma = (latest / ma - 1) * 100
    last_year = points[-252:] if len(points) >= 252 else points
    high = max(float(p["value"]) for p in last_year) if last_year else None
    drawdown = (latest / high - 1) * 100 if high else None
    return {
        "latest": latest,
        "ret_1y": ret_1y,
        "dist_200dma": dist_200dma,
        "drawdown_1y": drawdown,
        "sparkline": points[-180:],
    }


def update_chart_json(html_text: str, payload: dict) -> str:
    chart_data = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M local"),
        "ranges": {key: value for key, value in RANGES},
        "yieldCurves": payload.get("yield_curves", []),
        "priceSeries": payload.get("price_histories_v04") or {},
        "eygRows": payload.get("earnings_yield_gap", []),
    }
    data_json = json.dumps(chart_data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    html_text, count = re.subn(
        r'(<script id="v03-data" type="application/json">)(.*?)(</script>)',
        lambda m: m.group(1) + data_json + m.group(3),
        html_text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not locate v03-data script tag")
    html_text, option_count = re.subn(
        r"(<option value='mai'>)(.*?)(</option>)",
        r"\1mai Index - SET:MAI\3",
        html_text,
        count=1,
        flags=re.S,
    )
    if option_count != 1:
        raise RuntimeError("Could not locate mai option label")
    return html_text


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    item = next(item for item in payload["indices"] if item.get("symbol") == "mai")
    points, fetch_status = read_or_fetch_points(item)
    if len(points) < 1000:
        raise RuntimeError(f"TradingView SET:MAI returned too few points: {len(points)}")
    archive = load_archive()
    old = archive.get("prices", {}).get("mai", {})
    if old.get("chart_symbol") == SYMBOL:
        points = filter_quarantined("mai", merge_points(old.get("points", []), points), archive)
    verify_official_close(item, points)
    snapshot = payload.get("price_histories_v03", {}).get("mai")
    if snapshot:
        snapshot["points"] = [{"date": points[-1]["date"], "value": float(points[-1]["value"])}]

    price_histories = payload.setdefault("price_histories_v04", {})
    price_histories["mai"] = {
        "label": "mai Index",
        "symbol": "mai",
        "chart_symbol": SYMBOL,
        "source": "TradingView chart history for SET:MAI",
        "source_url": TV_SOURCE_URL,
        "note": f"TradingView SET:MAI completed daily history through {points[-1]['date']}; official quote displayed separately. Reconciliation: {item['quote_history_reconciliation']['state']}. Refresh mode: {fetch_status['mode']}; last successful retrieval: {fetch_status.get('fetched_at') or 'unknown'}.",
        "history_fetch_mode": fetch_status["mode"],
        "history_fetch_status": fetch_status,
        "market_session_date": points[-1]["date"],
        "points": [{"date": p["date"], "value": p["value"]} for p in points],
    }

    metrics = compute_price_metrics(price_histories["mai"]["points"])
    for item in payload.get("indices", []):
        if item.get("symbol") == "mai":
            item.setdefault("metrics", {}).update({key: value for key, value in metrics.items() if key != "latest"})
            item["metrics"]["history_as_of"] = points[-1]["date"]
            item["source_note"] = price_histories["mai"]["note"]
            item.pop("latest_only", None)
            break

    for row in payload.get("top_watchlist_v03", []):
        if row.get("symbol") == "mai":
            row["as_of"] = item["as_of"]
            break

    add_source_once(
        payload,
        {
            "name": "TradingView SET:MAI daily history",
            "url": TV_SOURCE_URL,
            "publication_date": f"Refresh mode: {fetch_status['mode']}; last successful retrieval {fetch_status.get('fetched_at') or 'unknown'}; latest observation {points[-1]['date']}",
            "used_for": "mai Index daily price-history chart in Top Watchlist Price Charts.",
        },
    )
    remove_stale_mai_failures(payload)
    if fetch_status["mode"] != "live":
        payload.setdefault("source_failures", []).append({"source": "TradingView SET:MAI refresh", "status": f"Used dated cache; last successful retrieval {fetch_status.get('fetched_at') or 'unknown'}. {fetch_status.get('error', '')}"})
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "source-manifest.json").write_text(json.dumps(payload.get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")

    html_text = HTML.read_text(encoding="utf-8")
    html_text = update_chart_json(html_text, payload)
    HTML.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "mai_points": len(points), "first": points[0]["date"], "last": points[-1]["date"], "chart_symbol": SYMBOL}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
