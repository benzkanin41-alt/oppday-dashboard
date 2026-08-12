from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
HTML = ROOT / "outputs" / "dashboard" / "index.html"


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.{digits}f}"


def render_rows(rows: list[dict]) -> str:
    rendered = []
    for row in rows:
        status = (
            "Computed from Trailing P/E minus latest local 10Y yield"
            if row.get("gap_pp") is not None
            else "Valuation is available, but local 10Y yield or forward source is still missing"
        )
        row["status"] = status
        rendered.append(
            "<tr>"
            f"<td>{html.escape(row.get('name') or '')}<div class='row-meta'>{html.escape(row.get('symbol') or '')} - {html.escape(row.get('region') or '')}</div></td>"
            f"<td>{fmt(row.get('trailing_pe'))}</td>"
            f"<td>{fmt(row.get('forward_pe'))}</td>"
            f"<td>{fmt(row.get('earnings_yield'))}%</td>"
            f"<td>{fmt(row.get('ten_year_yield'))}%</td>"
            f"<td>{fmt(row.get('gap_pp'))} pp</td>"
            f"<td>{html.escape(status)}<div class='row-meta'>Trailing: {html.escape(row.get('source') or 'n/a')}<br>Forward: {html.escape(row.get('forward_source') or 'source gap')}</div></td>"
            "</tr>"
        )
    return "\n".join(rendered)


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    latest_10y = {
        curve.get("country"): {
            "value": (curve.get("latest") or {}).get("10Y"),
            "as_of": curve.get("as_of"),
        }
        for curve in payload.get("yield_curves", [])
    }

    changed = []
    rows = payload.get("earnings_yield_gap", [])
    for row in rows:
        country = "Thailand" if row.get("region") == "Thailand" else "United States" if row.get("region") == "US" else None
        anchor = latest_10y.get(country) if country else None
        earnings_yield = row.get("earnings_yield")
        if not anchor or anchor.get("value") is None or earnings_yield is None:
            continue
        old_yield = row.get("ten_year_yield")
        row["ten_year_yield"] = anchor["value"]
        row["yield_as_of"] = anchor.get("as_of")
        row["gap_pp"] = float(earnings_yield) - float(anchor["value"])
        row["status"] = "Computed from Trailing P/E minus latest local 10Y yield"
        changed.append(
            {
                "symbol": row.get("symbol"),
                "old_10y": old_yield,
                "new_10y": anchor["value"],
                "yield_as_of": anchor.get("as_of"),
                "gap_pp": row["gap_pp"],
            }
        )

    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    html_text = HTML.read_text(encoding="utf-8")
    embedded_match = re.search(
        r'(<script id="v03-data" type="application/json">)(.*?)(</script>)',
        html_text,
        re.S,
    )
    if not embedded_match:
        raise RuntimeError("Could not locate embedded v03-data")
    embedded = json.loads(embedded_match.group(2))
    embedded["eygRows"] = rows
    embedded_json = json.dumps(embedded, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    html_text = (
        html_text[: embedded_match.start()]
        + embedded_match.group(1)
        + embedded_json
        + embedded_match.group(3)
        + html_text[embedded_match.end() :]
    )

    table_pattern = (
        r'(<h2>Earnings Yield Gap</h2>.*?<tbody>)(.*?)(</tbody></table></section>)'
    )
    html_text, count = re.subn(
        table_pattern,
        lambda match: match.group(1) + render_rows(rows) + match.group(3),
        html_text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not locate Earnings Yield Gap table")
    HTML.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "changed": changed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
