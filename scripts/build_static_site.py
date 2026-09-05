from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WEB = ROOT / "web"
CACHE = ROOT / ".build_cache" / "text"
PDF_TEXT_FALLBACK_QUARTERS = {"1Q69"}
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/)[^\r\n`\"']+")
PUBLIC_LOCAL_PATH_PLACEHOLDER = "[local path removed]"

sys.path.insert(0, str(ROOT))
import server  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def public_file_entry(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "extension": entry["extension"],
        "size": entry["size"],
        "modified": entry["modified"],
    }


PUBLIC_STAT_KEYS = (
    "items",
    "symbols",
    "quarters",
    "sources",
    "tickerSet",
    "markdownItems",
    "pdfItems",
)


def public_stats(stats: dict) -> dict:
    return {key: stats[key] for key in PUBLIC_STAT_KEYS if key in stats}


def redact_local_paths(text: str) -> str:
    return WINDOWS_ABSOLUTE_PATH_RE.sub(PUBLIC_LOCAL_PATH_PLACEHOLDER, text)


def public_item(item: dict, include_markdown: bool = False) -> dict:
    safe = {
        "id": item["id"],
        "symbol": item["symbol"],
        "quarter": item["quarter"],
        "period": item["period"],
        "eventDate": item["eventDate"],
        "source": item["source"],
        "sourceFolder": item["source"],
        "title": item["title"],
        "files": [public_file_entry(file_entry) for file_entry in item["files"]],
        "searchText": item["searchText"],
        "hasMarkdown": item["hasMarkdown"],
        "hasPdf": item["hasPdf"],
        "latestModified": item["latestModified"],
        "primaryMarkdownId": item["primaryMarkdownId"],
        "primaryPdfId": None,
        "onlinePdfAvailable": False,
        "workflowStatus": item.get("workflowStatus", ""),
        "runId": item.get("runId", ""),
        "registrationId": item.get("registrationId", ""),
    }
    if include_markdown:
        markdown = ""
        markdown_id = item.get("primaryMarkdownId")
        file_entry = None
        if markdown_id:
            file_entry = next((entry for entry in item["files"] if entry["id"] == markdown_id), None)
        if file_entry:
            markdown = cached_text(Path(file_entry["path"]))
        elif item.get("primaryPdfId"):
            pdf_file = next((entry for entry in item["files"] if entry["id"] == item["primaryPdfId"]), None)
            filename = pdf_file["name"] if pdf_file else "PDF"
            if pdf_file and item.get("quarter") in PDF_TEXT_FALLBACK_QUARTERS:
                markdown = cached_text(Path(pdf_file["path"]))
            else:
                markdown = (
                    f"# {item['symbol']} {item['quarter']}\n\n"
                    f"รายการนี้เป็นไฟล์ PDF presentation: `{filename}`\n\n"
                    "เพื่อให้ GitHub Pages เปิดเร็วและ repo ไม่ใหญ่เกินไป dashboard online ยังไม่ publish PDF ต้นฉบับขึ้น GitHub "
                    "ให้อ่านไฟล์ PDF จาก local dashboard หรือ OneDrive ต้นทางแทน"
                )
        safe["markdown"] = redact_local_paths(markdown)
    return safe


def cache_key(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def cached_text(path: Path) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{cache_key(path)}.md"
    if target.exists():
        return target.read_text(encoding="utf-8", errors="replace")
    text = server.read_text_file(path)
    target.write_text(text, encoding="utf-8")
    return text


OPPDAY_OWNED_FILES = (
    Path(".nojekyll"),
    Path("index.html"),
    Path("static/app.js"),
    Path("static/styles.css"),
    Path("data/index.json"),
)
OPPDAY_ITEMS_DIR = Path("data/items")
OPPDAY_ITEM_FILE_RE = re.compile(r"^[0-9a-f]{40}\.json$", re.IGNORECASE)


def merge_oppday_stage(stage: Path, docs: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    for relative in OPPDAY_OWNED_FILES:
        source = stage / relative
        target = docs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    target_items = docs / OPPDAY_ITEMS_DIR
    target_items.mkdir(parents=True, exist_ok=True)
    # Item JSON is an OPPDAY-owned subtree. Remove only stale JSON files; never
    # delete docs/ or another co-hosted dashboard.
    for stale in target_items.glob("*.json"):
        if stale.is_file() and OPPDAY_ITEM_FILE_RE.fullmatch(stale.name):
            stale.unlink()
    for source in (stage / OPPDAY_ITEMS_DIR).glob("*.json"):
        shutil.copy2(source, target_items / source.name)


def build() -> dict:
    built = server.build_index()

    with tempfile.TemporaryDirectory(prefix=".oppday-static-", dir=ROOT) as temporary:
        stage = Path(temporary)
        (stage / "static").mkdir(parents=True)
        (stage / OPPDAY_ITEMS_DIR).mkdir(parents=True)

        shutil.copy2(WEB / "index.html", stage / "index.html")
        shutil.copy2(WEB / "styles.css", stage / "static" / "styles.css")
        shutil.copy2(WEB / "app.js", stage / "static" / "app.js")

        public_items = []
        for item in built["items"]:
            public_items.append(public_item(item, include_markdown=False))
            write_json(
                stage / OPPDAY_ITEMS_DIR / f"{item['id']}.json",
                {"item": public_item(item, include_markdown=True)},
            )

        write_json(
            stage / "data" / "index.json",
            {
                "mode": "static",
                "updatedAt": built["updated_at"],
                "stats": public_stats(built["stats"]),
                "items": public_items,
            },
        )
        (stage / ".nojekyll").write_text("", encoding="utf-8")
        merge_oppday_stage(stage, DOCS)
    return {
        "updatedAt": built["updated_at"],
        "items": built["stats"]["items"],
        "symbols": built["stats"]["symbols"],
        "quarters": built["stats"]["quarters"],
        "markdownItems": built["stats"]["markdownItems"],
        "pdfItems": built["stats"]["pdfItems"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static GitHub Pages site for OPPDAY dashboard.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON result.")
    args = parser.parse_args()

    result = build()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("Built docs/ static site")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
