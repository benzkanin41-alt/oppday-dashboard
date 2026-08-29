from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import os
import re
import threading
import time
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree
from urllib.parse import parse_qs, unquote, urlparse


HOST = "127.0.0.1"
PORT_ENV = os.environ.get("OPPDAY_DASHBOARD_PORT")
PORT = int(PORT_ENV) if PORT_ENV else None
OPPDAY_ROOT = Path(os.environ.get("OPPDAY_ROOT", r"D:\OneDrive\stock\OPPDAY"))
PAST_ROOT = Path(os.environ.get("OPPDAY_PAST_ROOT", str(OPPDAY_ROOT / "PAST")))
SUMMARY_DIR_NAME = "\u0e2a\u0e23\u0e38\u0e1b oppday"
# Compatibility alias for the older one-quarter conversion helper. Indexing no
# longer depends on this path; every canonical quarter folder is discovered.
CURRENT_ROOT = Path(
    os.environ.get(
        "OPPDAY_CURRENT_ROOT",
        str(OPPDAY_ROOT / "1Q69" / "Oppday" / SUMMARY_DIR_NAME),
    )
)
WEB_ROOT = Path(__file__).resolve().parent / "web"
ALLOWED_EXTENSIONS = {".docx", ".md", ".pdf", ".txt"}
COMPLETED_CONCLUSION_STATUSES = {"done", "done_transcript_only", "conclusion_done"}
QUARTER_RE = re.compile(r"^[1-4]Q\d{2}$", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CURRENT_FILE_RE = re.compile(
    r"^(?P<symbol>.+?)-Earning call-(?P<quarter>[1-4]Q\d{2})$",
    re.IGNORECASE,
)
OPPDAY_FILE_RE = re.compile(
    r"oppday-\d+-\d+-(?P<period>Q[1-4]_\d{4})-(?P<symbol>.+)$",
    re.IGNORECASE,
)

cache_lock = threading.RLock()
cache = {
    "items": [],
    "by_item_id": {},
    "by_file_id": {},
    "updated_at": None,
    "stats": {},
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()


def file_id(path: Path) -> str:
    return sha1_text(str(path.resolve()).lower())


def item_id(parts: list[str]) -> str:
    return sha1_text("|".join(parts).lower())


def quarter_rank(quarter: str) -> int:
    match = re.match(r"([1-4])Q(\d{2})$", quarter.upper())
    if not match:
        return -1
    q = int(match.group(1))
    yy = int(match.group(2))
    return yy * 10 + q


def normalise_symbol(symbol: str) -> str:
    value = symbol.strip()
    value = re.sub(r"\s+", " ", value)
    return value.upper()


def row_value(row: dict, *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def read_workflow_status(path: Path) -> dict:
    empty = {"authoritative": False, "by_key": {}, "by_ticker": {}}
    if not path.exists():
        return empty

    text = ""
    for encoding in ("utf-8-sig", "utf-8", "cp874"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except OSError:
            return empty
    if not text.strip():
        return empty

    reader = csv.DictReader(text.splitlines())
    fieldnames = {str(name).strip().lower() for name in (reader.fieldnames or [])}
    status_column = next(
        (name for name in ("conclusion_status", "agent6_status") if name in fieldnames),
        "",
    )
    if not status_column:
        # A legacy status file must not hide summaries simply because its schema
        # predates the Agent 6 readiness contract.
        return empty

    by_key: dict[tuple[str, str], dict] = {}
    by_ticker: dict[str, list[dict]] = {}
    for raw_row in reader:
        row = {
            str(key).strip().lower(): (str(value).strip() if value is not None else "")
            for key, value in raw_row.items()
            if key is not None
        }
        ticker = normalise_symbol(row_value(row, "ticker", "symbol"))
        if not ticker:
            continue
        event_date = row_value(row, "event_date", "eventdate", "oppday_date", "date")
        conclusion_status = row_value(row, status_column).lower()
        record = {
            **row,
            "_ticker": ticker,
            "_event_date": event_date,
            "_conclusion_status": conclusion_status,
            "_run_id": row_value(row, "run_id", "runid"),
            "_registration_id": row_value(row, "registration_id", "registrationid"),
        }
        by_key[(ticker, event_date)] = record
        by_ticker.setdefault(ticker, []).append(record)

    return {
        "authoritative": True,
        "by_key": by_key,
        "by_ticker": by_ticker,
    }


def find_workflow_row(status_index: dict, symbol: str, event_date: str) -> dict | None:
    ticker = normalise_symbol(symbol)
    exact = status_index["by_key"].get((ticker, event_date))
    if exact:
        return exact
    candidates = status_index["by_ticker"].get(ticker, [])
    if len(candidates) == 1:
        return candidates[0]
    return None


def discover_summary_roots(oppday_root: Path | None = None):
    root = oppday_root or OPPDAY_ROOT
    if not root.exists():
        return
    try:
        quarter_dirs = [path for path in root.iterdir() if path.is_dir() and QUARTER_RE.match(path.name)]
    except OSError:
        return
    for quarter_dir in sorted(quarter_dirs, key=lambda path: quarter_rank(path.name), reverse=True):
        quarter = quarter_dir.name.upper()
        oppday_dir = quarter_dir / "Oppday"
        summary_root = oppday_dir / SUMMARY_DIR_NAME
        if summary_root.exists():
            yield quarter, summary_root, oppday_dir / f"workflow_status_{quarter}.csv"


def event_date_from_path(path: Path, summary_root: Path | None = None) -> str:
    if summary_root is not None:
        try:
            parts = path.relative_to(summary_root).parts[:-1]
        except ValueError:
            parts = path.parts[:-1]
    else:
        parts = path.parts[:-1]
    return next((part for part in parts if ISO_DATE_RE.match(part)), path.parent.name)


def detect_current_file(
    path: Path,
    quarter: str | None = None,
    summary_root: Path | None = None,
    status_row: dict | None = None,
) -> dict | None:
    stem = path.stem
    match = CURRENT_FILE_RE.match(stem)
    if not match:
        return None
    symbol = normalise_symbol(match.group("symbol"))
    file_quarter = match.group("quarter").upper()
    if quarter and file_quarter != quarter.upper():
        return None
    resolved_quarter = (quarter or file_quarter).upper()
    event_date = event_date_from_path(path, summary_root)
    meta = {
        "symbol": symbol,
        "quarter": resolved_quarter,
        "period": resolved_quarter,
        "eventDate": event_date,
        "source": resolved_quarter,
        "sourceFolder": str(summary_root or path.parent),
        "stem": stem,
    }
    if status_row:
        meta.update(
            {
                "workflowStatus": status_row.get("_conclusion_status", ""),
                "runId": status_row.get("_run_id", ""),
                "registrationId": status_row.get("_registration_id", ""),
            }
        )
    return meta


def detect_past_file(path: Path, quarter: str, past_root: Path | None = None) -> dict | None:
    stem = path.stem
    match = OPPDAY_FILE_RE.match(stem)
    if match:
        symbol = normalise_symbol(match.group("symbol"))
        period = match.group("period").upper()
    else:
        lower_stem = stem.lower()
        is_oppday_doc = "oppday" in lower_stem or "opp day" in lower_stem or "opportunity" in lower_stem
        if path.suffix.lower() == ".docx" and not is_oppday_doc:
            return None

        clean = re.sub(r"^สรุป\s*", "", stem.strip(), flags=re.IGNORECASE)
        doc_match = re.match(
            r"(?P<symbol>[A-Za-z0-9&.\-]+(?:\s+[A-Za-z0-9&.\-]+)?)\s*(?=OPPDAY|OPP DAY|OPPORTUNITY)",
            clean,
            flags=re.IGNORECASE,
        )
        if doc_match:
            symbol = normalise_symbol(doc_match.group("symbol"))
        else:
            # Fallback for older folders with less regular names.
            token = re.split(r"[\s_-]+", clean, maxsplit=1)[0]
            if not token:
                return None
            symbol = normalise_symbol(token)

        if re.match(r"^[1-4]Q\d{2}$", quarter, flags=re.IGNORECASE):
            period = quarter
        else:
            period_match = re.search(r"Q([1-4])[-_ ]?(\d{2})", stem, flags=re.IGNORECASE)
            period = f"{period_match.group(1)}Q{period_match.group(2)}" if period_match else quarter
        if not re.search(r"[A-Z0-9]", symbol):
            return None

    parts = path.parts
    event_date = ""
    if len(parts) >= 2:
        event_date = path.parent.name

    return {
        "symbol": symbol,
        "quarter": quarter,
        "period": period,
        "eventDate": event_date,
        "source": "PAST",
        "sourceFolder": str((past_root or PAST_ROOT) / quarter),
        "stem": stem,
    }


def file_payload(path: Path) -> dict:
    stat = path.stat()
    return {
        "id": file_id(path),
        "name": path.name,
        "path": str(path),
        "extension": path.suffix.lower(),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def add_group(groups: dict, meta: dict, path: Path) -> None:
    group_id = item_id(
        [
            meta["source"],
            meta["quarter"],
            meta["symbol"],
            meta.get("eventDate") or "",
            meta["stem"],
        ]
    )
    group = groups.setdefault(
        group_id,
        {
            "id": group_id,
            "symbol": meta["symbol"],
            "quarter": meta["quarter"],
            "period": meta["period"],
            "eventDate": meta.get("eventDate") or "",
            "source": meta["source"],
            "sourceFolder": meta["sourceFolder"],
            "title": f"{meta['symbol']} {meta['quarter']}",
            "files": [],
            "searchText": "",
            "hasMarkdown": False,
            "hasPdf": False,
            "latestModified": "",
            "workflowStatus": meta.get("workflowStatus", ""),
            "runId": meta.get("runId", ""),
            "registrationId": meta.get("registrationId", ""),
        },
    )

    payload = file_payload(path)
    group["files"].append(payload)
    group["hasMarkdown"] = group["hasMarkdown"] or payload["extension"] in {".docx", ".md", ".txt"}
    group["hasPdf"] = group["hasPdf"] or payload["extension"] == ".pdf"
    group["latestModified"] = max(group["latestModified"], payload["modified"])
    group["searchText"] = " ".join(
        [
            group["symbol"],
            group["quarter"],
            group["period"],
            group["eventDate"],
            group["source"],
            group.get("workflowStatus", ""),
            group.get("runId", ""),
            path.name,
        ]
    ).lower()


def iter_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
            yield path


def build_index(oppday_root: Path | None = None, past_root: Path | None = None) -> dict:
    resolved_oppday_root = oppday_root or OPPDAY_ROOT
    resolved_past_root = past_root or PAST_ROOT
    groups: dict[str, dict] = {}

    if resolved_past_root.exists():
        for quarter_dir in sorted([p for p in resolved_past_root.iterdir() if p.is_dir()], key=lambda p: p.name):
            quarter = quarter_dir.name.upper()
            scan_root = quarter_dir / "OPPDAY"
            if not scan_root.exists():
                scan_root = quarter_dir
            for path in iter_files(scan_root):
                if "\\Analyst\\" in str(path):
                    continue
                meta = detect_past_file(path, quarter, resolved_past_root)
                if meta:
                    add_group(groups, meta, path)

    current_roots = []
    workflow_status_files = []
    for quarter, summary_root, status_path in discover_summary_roots(resolved_oppday_root):
        current_roots.append(str(summary_root))
        status_index = read_workflow_status(status_path)
        if status_path.exists():
            workflow_status_files.append(str(status_path))
        for path in iter_files(summary_root):
            meta = detect_current_file(path, quarter, summary_root)
            if not meta:
                continue
            status_row = find_workflow_row(status_index, meta["symbol"], meta["eventDate"])
            if status_index["authoritative"]:
                if not status_row or status_row.get("_conclusion_status") not in COMPLETED_CONCLUSION_STATUSES:
                    continue
            if status_row:
                meta = detect_current_file(path, quarter, summary_root, status_row)
            if meta:
                add_group(groups, meta, path)

    items = list(groups.values())
    for item in items:
        item["files"].sort(
            key=lambda f: (
                f["extension"] != ".md",
                f["name"].lower(),
                f["modified"],
                f["size"],
                f["id"],
            )
        )
        item["primaryMarkdownId"] = next(
            (f["id"] for f in item["files"] if f["extension"] in {".docx", ".md", ".txt"}),
            None,
        )
        item["primaryPdfId"] = next((f["id"] for f in item["files"] if f["extension"] == ".pdf"), None)

    items.sort(
        key=lambda item: (
            quarter_rank(item["quarter"]),
            item["eventDate"],
            item["symbol"],
            item["latestModified"],
        ),
        reverse=True,
    )

    quarters = sorted({item["quarter"] for item in items}, key=quarter_rank, reverse=True)
    symbols = sorted({item["symbol"] for item in items})
    sources = sorted({item["source"] for item in items}, key=quarter_rank, reverse=True)
    by_file_id = {
        file_entry["id"]: file_entry
        for item in items
        for file_entry in item["files"]
    }

    return {
        "items": items,
        "by_item_id": {item["id"]: item for item in items},
        "by_file_id": by_file_id,
        "updated_at": now_iso(),
        "stats": {
            "items": len(items),
            "symbols": len(symbols),
            "quarters": quarters,
            "sources": sources,
            "tickerSet": symbols,
            "markdownItems": sum(1 for item in items if item["hasMarkdown"]),
            "pdfItems": sum(1 for item in items if item["hasPdf"]),
            "pastRootExists": resolved_past_root.exists(),
            "currentRootExists": bool(current_roots),
            "currentRoots": current_roots,
            "workflowStatusFiles": workflow_status_files,
        },
    }


def filtered_items(items: list[dict], params: dict[str, list[str]] | None = None) -> list[dict]:
    params = params or {}

    def parameter(*names: str) -> str:
        for name in names:
            values = params.get(name)
            if values and values[0].strip():
                return values[0].strip()
        return ""

    quarter = parameter("quarter").upper()
    event_date = parameter("event_date", "eventDate")
    run_id = parameter("run_id", "runId")
    conclusion_status = parameter("conclusion_status", "workflowStatus").lower()
    return [
        item
        for item in items
        if (not quarter or item["quarter"] == quarter)
        and (not event_date or item["eventDate"] == event_date)
        and (not run_id or item.get("runId") == run_id)
        and (not conclusion_status or item.get("workflowStatus") == conclusion_status)
    ]


def index_payload(params: dict[str, list[str]] | None = None) -> dict:
    params = params or {}
    selected = filtered_items(cache["items"], params)
    ticker_set = sorted({item["symbol"] for item in selected})
    quarters = sorted({item["quarter"] for item in selected}, key=quarter_rank, reverse=True)
    sources = sorted({item["source"] for item in selected}, key=quarter_rank, reverse=True)
    stats = {
        **cache["stats"],
        "items": len(selected),
        "symbols": len(ticker_set),
        "quarters": quarters,
        "sources": sources,
        "tickerSet": ticker_set,
        "markdownItems": sum(1 for item in selected if item["hasMarkdown"]),
        "pdfItems": sum(1 for item in selected if item["hasPdf"]),
    }
    payload = {
        "updatedAt": cache["updated_at"],
        "stats": stats,
        "items": selected,
    }
    raw_expected = params.get("manifest_tickers") or params.get("manifestTickers")
    if raw_expected:
        expected = sorted(
            {
                normalise_symbol(ticker)
                for value in raw_expected
                for ticker in value.split(",")
                if ticker.strip()
            }
        )
        expected_set = set(expected)
        actual_set = set(ticker_set)
        payload["manifestCheck"] = {
            "matches": expected_set == actual_set,
            "expected": expected,
            "actual": ticker_set,
            "missing": sorted(expected_set - actual_set),
            "unexpected": sorted(actual_set - expected_set),
        }
    return payload


def refresh_cache() -> dict:
    built = build_index()
    with cache_lock:
        cache.clear()
        cache.update(built)
        return {
            "updatedAt": cache["updated_at"],
            "stats": cache["stats"],
        }


def ensure_cache(max_age_seconds: int = 900) -> None:
    with cache_lock:
        updated_at = cache.get("updated_at")
    if not updated_at:
        refresh_cache()
        return
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        refresh_cache()
        return
    if datetime.now() - updated > timedelta(seconds=max_age_seconds):
        refresh_cache()


def read_text_file(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return read_docx_as_markdown(path)
    if path.suffix.lower() == ".pdf":
        return read_pdf_as_markdown(path)
    for encoding in ("utf-8-sig", "utf-8", "cp874"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_pdf_as_markdown(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader
    except Exception as exc:
        return f"# {path.stem}\n\nไม่สามารถโหลดตัวอ่าน PDF ได้: {exc}"

    try:
        reader = PdfReader(str(path))
        chunks = [f"# {path.stem}", ""]
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if text:
                chunks.append(f"## Page {idx}")
                chunks.append("")
                chunks.append(text)
                chunks.append("")
        if len(chunks) <= 2:
            chunks.append("ไม่พบข้อความที่ extract ได้จาก PDF นี้")
        return "\n".join(chunks).strip()
    except Exception as exc:
        return f"# {path.stem}\n\nไม่สามารถอ่านข้อความจาก PDF นี้ได้: {exc}"


def read_docx_as_markdown(path: Path) -> str:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path) as docx:
            xml_bytes = docx.read("word/document.xml")
        root = ElementTree.fromstring(xml_bytes)
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
        return f"# {path.stem}\n\nไม่สามารถอ่านข้อความจาก DOCX นี้ได้: {exc}"
    chunks: list[str] = [f"# {path.stem}", ""]

    for element in root.iter():
        if element.tag == f"{{{namespace['w']}}}p":
            texts = [node.text or "" for node in element.findall(".//w:t", namespace)]
            paragraph = "".join(texts).strip()
            if paragraph:
                chunks.append(paragraph)
                chunks.append("")
        elif element.tag == f"{{{namespace['w']}}}tbl":
            rows = []
            for row in element.findall(".//w:tr", namespace):
                cells = []
                for cell in row.findall("./w:tc", namespace):
                    cell_text = "".join(node.text or "" for node in cell.findall(".//w:t", namespace)).strip()
                    cells.append(cell_text)
                if cells:
                    rows.append(cells)
            if rows:
                header = rows[0]
                chunks.append("| " + " | ".join(header) + " |")
                chunks.append("| " + " | ".join(["---"] * len(header)) + " |")
                for row in rows[1:]:
                    chunks.append("| " + " | ".join(row) + " |")
                chunks.append("")

    return "\n".join(chunks).strip()


def daily_refresh_loop() -> None:
    while True:
        now = datetime.now()
        next_run = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        time.sleep(max(30, (next_run - now).total_seconds()))
        try:
            refresh_cache()
        except Exception as exc:
            print(f"[{now_iso()}] scheduled refresh failed: {exc}", flush=True)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "OppdayDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{now_iso()}] {self.address_string()} {fmt % args}", flush=True)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)

        if route == "/":
            self.send_static(WEB_ROOT / "index.html")
            return

        if route.startswith("/static/"):
            rel = route.removeprefix("/static/").strip("/")
            target = (WEB_ROOT / rel).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                self.send_error(403)
                return
            self.send_static(target)
            return

        if route == "/api/index":
            params = parse_qs(parsed.query)
            if params.get("refresh", ["0"])[0] == "1":
                refresh_cache()
            else:
                ensure_cache()
            with cache_lock:
                self.send_json(index_payload(params))
            return

        if route.startswith("/api/item/"):
            ensure_cache()
            requested = route.removeprefix("/api/item/")
            with cache_lock:
                item = cache["by_item_id"].get(requested)
                by_file = dict(cache["by_file_id"])
            if not item:
                self.send_error(404)
                return
            payload = dict(item)
            markdown_id = item.get("primaryMarkdownId")
            if markdown_id and markdown_id in by_file:
                payload["markdown"] = read_text_file(Path(by_file[markdown_id]["path"]))
            self.send_json({"item": payload})
            return

        if route.startswith("/file/"):
            ensure_cache()
            requested = route.removeprefix("/file/")
            with cache_lock:
                entry = cache["by_file_id"].get(requested)
            if not entry:
                self.send_error(404)
                return
            path = Path(entry["path"])
            if not path.exists() or not path.is_file():
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
            self.end_headers()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 512)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/refresh":
            try:
                payload = refresh_cache()
                self.send_json({"ok": True, **payload})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_error(404)


def main() -> None:
    if PORT is None:
        raise RuntimeError(
            "OPPDAY_DASHBOARD_PORT is required. Start this service through the "
            "registered 'Start Oppday Dashboard.ps1' launcher; no fallback port is allowed."
        )
    refresh_cache()
    thread = threading.Thread(target=daily_refresh_loop, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Oppday dashboard: http://{HOST}:{PORT}", flush=True)
    print(f"Indexed {cache['stats']['items']} items from OPPDAY folders.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
