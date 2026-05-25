from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WEB = ROOT / "web"

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
    }
    if include_markdown:
        markdown = ""
        markdown_id = item.get("primaryMarkdownId")
        if markdown_id:
            file_entry = next((entry for entry in item["files"] if entry["id"] == markdown_id), None)
            if file_entry:
                markdown = server.read_text_file(Path(file_entry["path"]))
        safe["markdown"] = markdown
    return safe


def build() -> dict:
    built = server.build_index()

    if DOCS.exists():
        shutil.rmtree(DOCS)
    (DOCS / "static").mkdir(parents=True)
    (DOCS / "data" / "items").mkdir(parents=True)

    shutil.copy2(WEB / "index.html", DOCS / "index.html")
    shutil.copy2(WEB / "styles.css", DOCS / "static" / "styles.css")
    shutil.copy2(WEB / "app.js", DOCS / "static" / "app.js")

    public_items = []
    for item in built["items"]:
        public_items.append(public_item(item, include_markdown=False))
        write_json(DOCS / "data" / "items" / f"{item['id']}.json", {"item": public_item(item, include_markdown=True)})

    write_json(
        DOCS / "data" / "index.json",
        {
            "mode": "static",
            "updatedAt": built["updated_at"],
            "stats": built["stats"],
            "items": public_items,
        },
    )

    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
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
