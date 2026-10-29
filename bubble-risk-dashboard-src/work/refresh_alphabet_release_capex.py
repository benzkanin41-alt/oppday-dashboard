from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from refresh_ai_public_sources import PublicHTML, fetch_document, upsert_source
from retain_dashboard_history import merge_points


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs/dashboard/data.json"
RAW = ROOT / "work/raw/ai_direct_v06/alphabet_q3_2026.html"
URL = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm"


def parse_release(raw: str) -> dict:
    document = PublicHTML()
    document.feed(raw)
    for rows in document.tables:
        text = " ".join(" ".join(row) for row in rows)
        if not all(token in text for token in ("Quarter Ended September 30", "Year To Date September 30", "2025", "2026")):
            continue
        for row in rows:
            if not row or row[0].casefold().strip() != "purchases of property and equipment":
                continue
            amounts = [float(match.group().replace(",", "")) for cell in row[1:]
                       for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", cell)]
            if len(amounts) != 4 or not all(0 < amount < 1_000_000 for amount in amounts):
                raise ValueError("Alphabet cash PP&E quarter/YTD columns invalid")
            header = text[:text.casefold().index("purchases of property and equipment")]
            years = re.findall(r"\b202[56]\b", header)
            if years[:4] != ["2025", "2026", "2025", "2026"]:
                raise ValueError("Alphabet cash-flow column order changed")
            return {"date": "2026-09-30", "period_start": "2026-07-01",
                    "value": amounts[1] / 1000, "ytd_value": amounts[3] / 1000,
                    "tag": "PurchasesOfPropertyAndEquipment", "basis": "Reported quarter; gross cash PP&E, not guidance",
                    "form": "8-K Exhibit 99.1", "filed": "2026-10-28", "accn": "0001652044-26-000080",
                    "source": "Alphabet official Q3 2026 earnings release, SEC Exhibit 99.1",
                    "source_url": URL, "source_kind": "SEC earnings-release bridge"}
    raise ValueError("Alphabet Q3 2026 quarterly cash-flow row missing")


def reconcile_capex(points: list[dict], release: dict) -> list[dict]:
    previous_ytd = [point for point in points if point.get("date") == "2026-06-30"]
    if previous_ytd:
        derived = previous_ytd[0].get("derived_from") or []
        ytd = next((row["val"] / 1e9 for row in derived if row.get("start") == "2026-01-01" and row.get("end") == "2026-06-30"), None)
        if ytd is not None and abs(release["ytd_value"] - ytd - release["value"]) > 0.001:
            raise ValueError("Alphabet quarter disagrees with YTD difference")
    existing = next((point for point in points if point["date"] == release["date"]), None)
    if existing and existing.get("form") in {"10-Q", "10-K"}:
        if abs(existing["value"] - release["value"]) > 0.001:
            raise ValueError("Alphabet SEC fact and earnings release disagree")
        return points
    return merge_points(points, [release])


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    status = {"attempted_at": datetime.now(timezone.utc).isoformat()}
    try:
        raw, mode = fetch_document(URL, RAW, parse_release)
        release = parse_release(raw)
        capex = payload["ai_semiconductor_direct_v06"]["capex"]
        capex["GOOGL"] = reconcile_capex(capex["GOOGL"], release)
        status.update(mode=mode, period_end=release["date"], value=release["value"])
        upsert_source(payload, {"name": "Alphabet Q3 2026 cash CAPEX earnings release", "url": URL,
            "publication_date": f"Published 2026-10-28; quarter ended 2026-09-30; refresh mode: {mode}",
            "used_for": "GOOGL quarterly cash PP&E from the official cash-flow table, separated from YTD and guidance; reconciled to Company Facts when available."})
        if mode == "cache":
            payload.setdefault("source_failures", []).append({"source": "Alphabet Q3 earnings release refresh", "status": "Used validated cached official release; original period/publication date retained."})
    except Exception as exc:
        if isinstance(exc, ValueError) and "disagree" in str(exc):
            raise
        status.update(mode="unavailable", error=str(exc))
        payload.setdefault("source_failures", []).append({"source": "Alphabet Q3 earnings release", "status": f"Official release refresh unavailable; retained sourced Company Facts periods. {exc}"})
    payload.setdefault("source_refresh_status", {})["alphabet_q3_release"] = status
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA.with_name("source-manifest.json").write_text(json.dumps(payload["sources"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
