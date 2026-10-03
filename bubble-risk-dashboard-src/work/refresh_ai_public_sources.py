from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from retain_dashboard_history import merge_points, merge_rows


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "dashboard" / "data.json"
MANIFEST = DATA.with_name("source-manifest.json")
RAW = ROOT / "work" / "raw" / "ai_direct_v06"
LEDGER = RAW / "gpu_public_history.json"
GPU_KEYS = {"h100-neo": "NeoCloud H100", "h100-hs": "Hyperscaler H100", "b200-neo": "NeoCloud B200"}
MICRON_URL = "https://www.sec.gov/Archives/edgar/data/723125/000072312526000018/a2026q4ex991-pressrelease.htm"


class PublicHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.script = None
        self.tables = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script = []
        elif tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif self.stack and tag == "tr":
            self.stack[-1]["row"] = []
        elif self.stack and tag in {"td", "th"}:
            self.stack[-1]["cell"] = []
        elif self.stack and tag == "br" and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(" ")

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None
        elif self.stack and tag in {"td", "th"}:
            table = self.stack[-1]
            if table["row"] is not None and table["cell"] is not None:
                table["row"].append(" ".join("".join(table["cell"]).split()))
            table["cell"] = None
        elif self.stack and tag == "tr":
            table = self.stack[-1]
            if table["row"]:
                table["rows"].append(table["row"])
            table["row"] = None
        elif self.stack and tag == "table":
            self.tables.append(self.stack.pop()["rows"])


def walk_json(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_gpu_cards(raw: str, url: str) -> dict[str, list[dict]]:
    document = PublicHTML()
    document.feed(raw)
    result = {}
    decoder = json.JSONDecoder()
    for script in document.scripts:
        for match in re.finditer(r"self\.__next_f\.push\(", script):
            packet, _ = decoder.raw_decode(script, match.end())
            if len(packet) < 2 or not isinstance(packet[1], str):
                continue
            for line in packet[1].splitlines():
                encoded = line.partition(":")[2]
                if not encoded.startswith(("[", "{")):
                    continue
                try:
                    value = json.loads(encoded)
                except json.JSONDecodeError:
                    continue
                for card in walk_json(value):
                    if not isinstance(card, dict) or card.get("key") not in GPU_KEYS or "points" not in card:
                        continue
                    points = []
                    for row in card["points"]:
                        day = date.fromisoformat(row["date"])
                        price = float(row["price"])
                        if day > date.today() or not 0 < price < 100:
                            raise ValueError("invalid public GPU observation")
                        points.append({
                            "date": day.isoformat(), "value": price,
                            "source": "Silicon Data official public index reading",
                            "source_url": url,
                            "basis": "Published dated observation; no interpolation",
                        })
                    points = merge_points([], points)
                    if not points or abs(points[-1]["value"] - float(card["rawValue"])) > 0.001:
                        raise ValueError("GPU headline and dated chart disagree")
                    result[GPU_KEYS[card["key"]]] = points
    if not result:
        raise ValueError("no structured public GPU chart data")
    return result


def fetch_document(url: str, path: Path) -> tuple[str, str]:
    try:
        request = Request(url, headers={"User-Agent": "Codex BubbleRiskDashboard user@example.com"})
        with urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8")
    except Exception as first_error:
        executable = shutil.which("curl.exe") or shutil.which("curl")
        proc = subprocess.run(
            [executable, "--fail", "--location", "--silent", "--show-error", "--max-time", "35", "--user-agent", "Codex BubbleRiskDashboard user@example.com", url],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
        ) if executable else None
        if not proc or proc.returncode:
            if path.exists():
                return path.read_text(encoding="utf-8"), "cache"
            raise RuntimeError(f"public source fetch failed: {url}: {first_error}")
        raw = proc.stdout
    path.write_text(raw, encoding="utf-8")
    return raw, "live"


def micron_release_points(raw: str) -> dict[str, dict]:
    document = PublicHTML()
    document.feed(raw)
    values = {}
    wanted = {"revenue": ("MU revenue", 5), "inventories": ("MU inventory", 3), "expenditures for property, plant, and equipment": ("MU capex", 5)}
    for rows in document.tables:
        table_text = " ".join(" ".join(row) for row in rows)
        if "September 3" not in table_text or "2026" not in table_text:
            continue
        for row in rows:
            label = row[0].casefold().strip() if row else ""
            if label not in wanted:
                continue
            name, minimum = wanted[label]
            amounts = [float(match.group().replace(",", "")) for cell in row[1:] for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", cell)]
            if len(amounts) >= minimum:
                values.setdefault(name, amounts[0] / 1000)
    if set(values) != {"MU revenue", "MU inventory", "MU capex"}:
        raise ValueError("Micron Q4 release quarterly/balance-sheet rows missing")
    return {
        name: {
            "date": "2026-09-03", "value": value,
            "source": "Micron FY2026 Q4 official earnings release, SEC Exhibit 99.1",
            "source_url": MICRON_URL, "source_kind": "SEC 8-K earnings release",
            "form": "8-K Exhibit 99.1", "filed": "2026-09-30",
            "accn": "0000723125-26-000018",
            "basis": "Quarterly gross cash capex" if name == "MU capex" else ("Quarterly revenue" if name == "MU revenue" else "Period-end inventory"),
        } for name, value in values.items()
    }


def upsert_source(payload: dict, entry: dict) -> None:
    for source in payload.setdefault("sources", []):
        if source.get("name") == entry["name"]:
            source.update(entry)
            return
    payload["sources"].append(entry)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    ai = payload["ai_semiconductor_direct_v06"]
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    status = {"attempted_at": datetime.now().isoformat(), "sources": [], "errors": {}}
    for gpu in ("h100", "b200"):
        url = f"https://www.silicondata.com/products/silicon-index/{gpu}"
        try:
            raw, mode = fetch_document(url, RAW / f"silicon_{gpu}.html")
            series = parse_gpu_cards(raw, url)
            for name, points in series.items():
                ledger[name] = merge_points(ledger.get(name, []), points)
            latest = max(point["date"] for points in series.values() for point in points)
            upsert_source(payload, {"name": f"Silicon Data official {gpu.upper()} rental index", "url": url,
                "publication_date": f"Observations through {latest}; refresh mode: {mode}",
                "used_for": "Published public 7-day GPU rental readings, accumulated without deleting prior observations; not licensed full history."})
            status["sources"].append({"name": gpu, "mode": mode, "latest": latest})
        except Exception as exc:
            status["errors"][gpu] = str(exc)
    for name, points in ledger.items():
        ai["gpu_rental"][name] = merge_points(ai["gpu_rental"].get(name, []), points)
    LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    try:
        raw, mode = fetch_document(MICRON_URL, RAW / "micron_q4_2026.html")
        release = micron_release_points(raw)
        for name, point in release.items():
            existing = next((item for item in ai["micron"][name] if item["date"] == point["date"]), None)
            if not existing or existing.get("form") not in {"10-K", "10-Q"}:
                ai["micron"][name] = merge_points(ai["micron"][name], [point])
        upsert_source(payload, {"name": "Micron FY2026 Q4 official earnings release", "url": MICRON_URL,
            "publication_date": f"Published 2026-09-30; period ended 2026-09-03; refresh mode: {mode}",
            "used_for": "Quarterly revenue, period-end inventory and gross cash capex until SEC Company Facts includes the period. Not HBM-only capacity or net capex."})
        status["sources"].append({"name": "micron_q4_2026", "mode": mode, "period_end": "2026-09-03"})
    except Exception as exc:
        status["errors"]["micron_q4_2026"] = str(exc)
    seeds = RAW / "public_ai_seed_observations.json"
    if seeds.exists():
        additions = json.loads(seeds.read_text(encoding="utf-8"))
        for name, points in additions.get("gpu_rental", {}).items():
            ai["gpu_rental"][name] = merge_points(points, ai["gpu_rental"].get(name, []))
        ai["vendor_events"] = merge_rows(ai.get("vendor_events", []), additions.get("vendor_events", []))
        for entry in additions.get("sources", []):
            upsert_source(payload, entry)
    for name, error in status["errors"].items():
        payload.setdefault("source_failures", []).append({"source": f"AI public refresh: {name}", "status": f"Live source unavailable; retained dated observations. {error}"})
    for item in status["sources"]:
        if item["mode"] == "cache":
            payload.setdefault("source_failures", []).append({"source": f"AI public refresh: {item['name']}", "status": "Used cached source; observation/filing date has not been advanced."})
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST.write_text(json.dumps(payload["sources"], ensure_ascii=False, indent=2), encoding="utf-8")
    (RAW / "public_refresh_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
