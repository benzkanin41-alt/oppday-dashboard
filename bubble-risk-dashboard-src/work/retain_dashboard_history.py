from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
HTML = ROOT / "outputs" / "dashboard" / "index.html"
ARCHIVE = ROOT / "work" / "raw" / "dashboard_history.json"
AI_MAPS = ("capex", "coreweave", "micron", "gpu_rental", "cowos")
AI_ROWS = ("hbm_observations", "vendor_events", "cowos_observations")


def merge_points(old: list[dict], new: list[dict]) -> list[dict]:
    by_date = {point["date"]: point for point in old if point.get("date")}
    for point in new:
        if point.get("date"):
            by_date[point["date"]] = point
    return [by_date[day] for day in sorted(by_date)]


def merge_rows(old: list[dict], new: list[dict]) -> list[dict]:
    rows = {(row.get("date"), row.get("metric")): row for row in old + new}
    return [rows[key] for key in sorted(rows)]


def load_archive() -> dict:
    if ARCHIVE.exists():
        return json.loads(ARCHIVE.read_text(encoding="utf-8"))
    return {"schema_version": 1, "prices": {}, "curves": {}, "ai": {}}


def write_archive(archive: dict) -> None:
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    temp = ARCHIVE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(ARCHIVE)


def correct_snapshot_date(symbol: str, point: dict, session_date: str, source_url: str) -> None:
    archive = load_archive()
    stored = archive.get("prices", {}).get(symbol, {})
    stored["points"] = [row for row in stored.get("points", []) if row.get("date") != point["date"]]
    corrections = archive.setdefault("corrected_snapshots", [])
    correction = {
        "symbol": symbol,
        "original_point": point,
        "market_session_date": session_date,
        "source_url": source_url,
        "reason": "Webpage update timestamp was incorrectly used as a daily trading date.",
    }
    if correction not in corrections:
        corrections.append(correction)
    write_archive(archive)


def merge_history(payload: dict, archive: dict) -> dict:
    prices = payload.setdefault("price_histories_v04", {})
    for symbol, old in archive.get("prices", {}).items():
        current = prices.get(symbol)
        if current is None:
            prices[symbol] = old
        elif current.get("chart_symbol") == old.get("chart_symbol"):
            current["points"] = merge_points(old.get("points", []), current.get("points", []))
        else:
            raise RuntimeError(f"cannot merge different price instruments for {symbol}")

    curves = {curve["country"]: curve for curve in payload.get("yield_curves", [])}
    for country, old in archive.get("curves", {}).items():
        if country not in curves:
            curves[country] = old
        else:
            curves[country]["history"] = merge_points(
                old.get("history", []), curves[country].get("history", [])
            )
    payload["yield_curves"] = list(curves.values())

    ai = payload.setdefault("ai_semiconductor_direct_v06", {})
    for key in AI_MAPS:
        current_map = ai.setdefault(key, {})
        for name, old in archive.get("ai", {}).get(key, {}).items():
            current_map[name] = merge_points(old, current_map.get(name, []))
    for key in AI_ROWS:
        ai[key] = merge_rows(archive.get("ai", {}).get(key, []), ai.get(key, []))
    return payload


def capture_history(payload_path: Path = DATA) -> None:
    if not payload_path.exists():
        return
    old_archive = load_archive()
    payload = merge_history(json.loads(payload_path.read_text(encoding="utf-8")), old_archive)
    ai = payload.get("ai_semiconductor_direct_v06", {})
    archive = {
        "schema_version": 1,
        "snapshot_generated_at": payload.get("generated_at"),
        "prices": payload.get("price_histories_v04", {}),
        "curves": {curve["country"]: curve for curve in payload.get("yield_curves", [])},
        "ai": {key: ai.get(key, {} if key in AI_MAPS else []) for key in AI_MAPS + AI_ROWS},
        "corrected_snapshots": old_archive.get("corrected_snapshots", []),
    }
    write_archive(archive)


def assert_history_preserved(payload: dict) -> None:
    archive = load_archive()
    pairs = []
    for symbol, old in archive.get("prices", {}).items():
        pairs.append((symbol, old.get("points", []), payload.get("price_histories_v04", {}).get(symbol, {}).get("points", [])))
    curves = {curve["country"]: curve for curve in payload.get("yield_curves", [])}
    for country, old in archive.get("curves", {}).items():
        pairs.append((country, old.get("history", []), curves.get(country, {}).get("history", [])))
    ai = payload.get("ai_semiconductor_direct_v06", {})
    for key in AI_MAPS:
        for name, old in archive.get("ai", {}).get(key, {}).items():
            pairs.append((f"{key}/{name}", old, ai.get(key, {}).get(name, [])))
    for label, old, current in pairs:
        missing = {point["date"] for point in old} - {point["date"] for point in current}
        if missing:
            raise RuntimeError(f"historical dates lost for {label}: {sorted(missing)[:5]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    if args.capture:
        capture_history(args.capture)
        return
    payload = merge_history(json.loads(DATA.read_text(encoding="utf-8")), load_archive())
    assert_history_preserved(payload)
    payload["history_retention"] = {
        "status": "preserved",
        "price_series": len(payload["price_histories_v04"]),
        "archive": "work/raw/dashboard_history.json",
    }
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    text = HTML.read_text(encoding="utf-8")
    pattern = r'(<script id="v03-data" type="application/json">)(.*?)(</script>)'
    match = re.search(pattern, text, re.S)
    if not match:
        raise RuntimeError("missing chart data for history retention")
    embedded = json.loads(match.group(2))
    embedded["priceSeries"] = payload["price_histories_v04"]
    embedded["yieldCurves"] = payload["yield_curves"]
    encoded = json.dumps(embedded, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    text = re.sub(pattern, lambda m: m.group(1) + encoded + m.group(3), text, flags=re.S)
    HTML.write_text(text, encoding="utf-8")
    print(json.dumps(payload["history_retention"], indent=2))


if __name__ == "__main__":
    main()
