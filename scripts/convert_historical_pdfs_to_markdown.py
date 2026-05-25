from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def markdown_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".md")


def target_items(include_quarters: set[str] | None = None) -> list[dict]:
    built = server.build_index()
    items: list[dict] = []
    for item in built["items"]:
        quarter = item.get("quarter", "")
        if quarter == "1Q69":
            continue
        if include_quarters and quarter not in include_quarters:
            continue
        if not item.get("hasPdf") or item.get("hasMarkdown"):
            continue
        pdf_id = item.get("primaryPdfId")
        pdf_file = next((file for file in item["files"] if file["id"] == pdf_id), None)
        if not pdf_file:
            continue
        pdf_path = Path(pdf_file["path"])
        if not pdf_path.exists():
            continue
        items.append({"item": item, "pdf_file": pdf_file, "pdf_path": pdf_path})
    return items


def convert_one(pdf_path: Path, item: dict, overwrite: bool = False) -> tuple[str, Path]:
    md_path = markdown_path_for(pdf_path)
    if md_path.exists() and not overwrite:
        return "skipped", md_path

    extracted = server.read_pdf_as_markdown(pdf_path)
    content = "\n".join(
        [
            f"# {item['symbol']} {item['quarter']}",
            "",
            f"- Source PDF: `{pdf_path.name}`",
            f"- Quarter: `{item['quarter']}`",
            f"- Event date: `{item.get('eventDate') or '-'}`",
            "",
            "---",
            "",
            extracted,
            "",
        ]
    )
    md_path.write_text(content, encoding="utf-8")
    return "created", md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert historical OPPDAY PDF-only items to Markdown beside source PDFs.")
    parser.add_argument("--dry-run", action="store_true", help="List conversion targets without writing files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing sibling Markdown files.")
    parser.add_argument("--limit", type=int, default=0, help="Convert at most N files.")
    parser.add_argument("--quarter", action="append", default=[], help="Only convert a specific quarter, e.g. 4Q68. Repeatable.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary.")
    args = parser.parse_args()

    quarters = {q.upper() for q in args.quarter} or None
    items = target_items(quarters)
    if args.limit:
        items = items[: args.limit]

    summary = {
        "targets": len(items),
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "files": [],
    }

    for idx, entry in enumerate(items, start=1):
        item = entry["item"]
        pdf_path = entry["pdf_path"]
        md_path = markdown_path_for(pdf_path)
        record = {
            "index": idx,
            "symbol": item["symbol"],
            "quarter": item["quarter"],
            "pdf": str(pdf_path),
            "markdown": str(md_path),
        }
        if args.dry_run:
            status = "dry_run"
        else:
            try:
                status, md_path = convert_one(pdf_path, item, args.overwrite)
                record["markdown"] = str(md_path)
            except Exception as exc:  # Keep the batch resumable.
                status = "failed"
                record["error"] = str(exc)
        record["status"] = status
        summary["files"].append(record)
        if status == "created":
            summary["created"] += 1
        elif status == "skipped":
            summary["skipped"] += 1
        elif status == "failed":
            summary["failed"] += 1

        if not args.json:
            print(f"[{idx}/{len(items)}] {status}: {item['quarter']} {item['symbol']} -> {md_path}")

    if args.json:
        print(json.dumps({k: v for k, v in summary.items() if k != "files"}, ensure_ascii=False))
    else:
        print(json.dumps({k: v for k, v in summary.items() if k != "files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
