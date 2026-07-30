from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

import PyPDF2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "dashboard"
DATA = OUT / "data.json"
MANIFEST = OUT / "source-manifest.json"
RAW = ROOT / "work" / "raw" / "ai_direct_v06" / "meta_ir_capex_q2_2026.json"
RELEASE_URL = "https://s21.q4cdn.com/399680738/files/doc_financials/2026/q2/Meta-06-30-2026-Exhibit-99-1-FINAL.pdf"
RELEASE_PAGE = "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Second-Quarter-2026-Results/default.aspx"
PERIOD_END = "2026-06-30"
FILED = "2026-07-29"
ACCESSION = "0001628280-26-050596"


def fetch_release_point() -> dict:
    request = Request(RELEASE_URL, headers={"User-Agent": "Mozilla/5.0 Codex bubble-risk-dashboard"})
    raw = urlopen(request, timeout=45).read()
    text = " ".join((page.extract_text() or "") for page in PyPDF2.PdfReader(io.BytesIO(raw)).pages)
    text = re.sub(r"\s+", " ", text)
    match = re.search(
        r"Purchases of property and equipment\s*\(?([0-9,]+)\)?\s*\(?([0-9,]+)\)?\s*\(?([0-9,]+)\)?\s*\(?([0-9,]+)\)?",
        text,
    )
    if not match:
        raise RuntimeError("Meta Q2 release PP&E row not found")
    value = int(match.group(1).replace(",", "")) / 1000
    if not 20 <= value <= 50:
        raise RuntimeError(f"Meta Q2 release PP&E value out of range: {value}")
    return {
        "date": PERIOD_END,
        "value": round(value, 3),
        "source": "Meta Q2 2026 earnings release (official Investor Relations; furnished as SEC 8-K Exhibit 99.1)",
        "tag": "PurchasesOfPropertyAndEquipment",
        "form": "8-K Exhibit 99.1",
        "filed": FILED,
        "accn": ACCESSION,
    }


def read_or_fetch() -> tuple[dict, str]:
    try:
        point = fetch_release_point()
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(
            json.dumps({"fetched_at": datetime.now().isoformat(), "url": RELEASE_URL, "point": point}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return point, "live"
    except Exception:
        if RAW.exists() and RAW.stat().st_size:
            return json.loads(RAW.read_text(encoding="utf-8"))["point"], "cache"
        raise


def upsert_source(sources: list[dict]) -> None:
    entry = {
        "name": "Meta Q2 2026 earnings release",
        "url": RELEASE_PAGE,
        "publication_date": "Published 2026-07-29; accessed by daily dashboard refresh",
        "used_for": "META Q2 2026 purchases of property and equipment ($30.116B) until SEC Company Facts includes the new quarter.",
    }
    for source in sources:
        if source.get("name") == entry["name"]:
            source.update(entry)
            return
    sources.append(entry)


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    ai = payload.get("ai_semiconductor_direct_v06") or {}
    capex = ai.get("capex") or {}
    if "META" not in capex:
        raise RuntimeError("META capex series missing")
    point, mode = read_or_fetch()
    capex["META"] = sorted(
        [item for item in capex["META"] if item.get("date") != PERIOD_END] + [point],
        key=lambda item: item["date"],
    )[-10:]
    sources = payload.setdefault("sources", [])
    upsert_source(sources)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "mode": mode, "meta_q2_capex_b": point["value"], "period_end": point["date"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
