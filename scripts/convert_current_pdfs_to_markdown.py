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


def fallback_meta(pdf_path: Path) -> dict:
    symbol = pdf_path.stem.split("-Earning call-", 1)[0].strip().upper()
    return {
        "symbol": symbol or pdf_path.stem.upper(),
        "quarter": "1Q69",
        "eventDate": pdf_path.parent.name,
    }


def target_pdfs(folder: Path, recursive: bool = False) -> list[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(path for path in folder.glob(pattern) if path.is_file())


def convert_one(pdf_path: Path, overwrite: bool = False) -> tuple[str, Path]:
    md_path = markdown_path_for(pdf_path)
    if md_path.exists() and not overwrite:
        return "skipped", md_path

    meta = server.detect_current_file(pdf_path) or fallback_meta(pdf_path)
    extracted = server.read_pdf_as_markdown(pdf_path)
    content = "\n".join(
        [
            f"# {meta['symbol']} {meta['quarter']}",
            "",
            f"- Source PDF: `{pdf_path.name}`",
            f"- Quarter: `{meta['quarter']}`",
            f"- Event date: `{meta.get('eventDate') or '-'}`",
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
    parser = argparse.ArgumentParser(description="Convert current-quarter OPPDAY PDFs to sibling Markdown files.")
    parser.add_argument(
        "--folder",
        default=str(server.CURRENT_ROOT),
        help="Folder containing current-quarter PDF files. Defaults to the 1Q69 OPPDAY root.",
    )
    parser.add_argument("--recursive", action="store_true", help="Search PDF files recursively under --folder.")
    parser.add_argument("--dry-run", action="store_true", help="List conversion targets without writing files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing sibling Markdown files.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary.")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        raise SystemExit(f"Folder not found: {folder}")

    pdfs = target_pdfs(folder, recursive=args.recursive)
    summary = {
        "folder": str(folder),
        "targets": len(pdfs),
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "files": [],
    }

    for idx, pdf_path in enumerate(pdfs, start=1):
        md_path = markdown_path_for(pdf_path)
        record = {
            "index": idx,
            "pdf": str(pdf_path),
            "markdown": str(md_path),
        }
        if args.dry_run:
            status = "dry_run"
        else:
            try:
                status, md_path = convert_one(pdf_path, args.overwrite)
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
            print(f"[{idx}/{len(pdfs)}] {status}: {pdf_path.name} -> {md_path}")

    compact = {k: v for k, v in summary.items() if k != "files"}
    if args.json:
        print(json.dumps(compact, ensure_ascii=False))
    else:
        print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
