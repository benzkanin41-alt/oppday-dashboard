from __future__ import annotations

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "dashboard" / "index.html"
DATA = ROOT / "outputs" / "dashboard" / "data.json"
FIELDS = ("trailing_pe", "forward_pe", "earnings_yield", "ten_year_yield", "gap_pp")


def row_map(rows: object, label: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise SystemExit(f"{label} is not a list")
    mapped = {row.get("symbol"): row for row in rows if isinstance(row, dict) and row.get("symbol")}
    if len(mapped) != len(rows):
        raise SystemExit(f"{label} contains a missing or duplicate symbol")
    return mapped


def equivalent(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
    return left == right


def main() -> None:
    dashboard_data = json.loads(DATA.read_text(encoding="utf-8"))
    text = HTML.read_text(encoding="utf-8")
    match = re.search(r'<script id="v03-data" type="application/json">(.*?)</script>', text, re.S)
    if not match:
        raise SystemExit("missing v03-data script")
    embedded = json.loads(match.group(1))

    payload_rows = row_map(dashboard_data.get("earnings_yield_gap"), "data earnings_yield_gap")
    rendered_rows = row_map(embedded.get("eygRows"), "embedded eygRows")
    if set(payload_rows) != set(rendered_rows):
        raise SystemExit("EYG symbol mismatch between data.json and rendered dashboard")

    for symbol in sorted(payload_rows):
        data_row = payload_rows[symbol]
        rendered_row = rendered_rows[symbol]
        for field in FIELDS:
            if not equivalent(data_row.get(field), rendered_row.get(field)):
                raise SystemExit(
                    f"EYG mismatch for {symbol} {field}: "
                    f"{data_row.get(field)!r} != {rendered_row.get(field)!r}"
                )
        trailing_pe = data_row.get("trailing_pe")
        if not isinstance(trailing_pe, (int, float)) or trailing_pe <= 0:
            raise SystemExit(f"invalid trailing P/E for {symbol}")
        if "forward_pe" not in data_row:
            raise SystemExit(f"missing forward P/E field for {symbol}")
        print(
            "eyg",
            symbol,
            "trailing",
            trailing_pe,
            "forward",
            data_row.get("forward_pe"),
            "gap_pp",
            data_row.get("gap_pp"),
        )

    print("eyg_rows", len(payload_rows))
    print("status", "ok")


if __name__ == "__main__":
    main()