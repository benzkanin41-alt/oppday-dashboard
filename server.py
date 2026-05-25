from __future__ import annotations

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
PORT = int(os.environ.get("OPPDAY_DASHBOARD_PORT", "8766"))
PAST_ROOT = Path(r"D:\OneDrive\stock\OPPDAY\PAST")
CURRENT_ROOT = Path(r"D:\OneDrive\stock\OPPDAY\1Q69\Oppday\สรุป oppday")
WEB_ROOT = Path(__file__).resolve().parent / "web"
ALLOWED_EXTENSIONS = {".docx", ".md", ".pdf", ".txt"}

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


def detect_current_file(path: Path) -> dict | None:
    stem = path.stem
    match = CURRENT_FILE_RE.match(stem)
    if not match:
        return None
    parent_date = path.parent.name
    symbol = normalise_symbol(match.group("symbol"))
    quarter = match.group("quarter").upper()
    return {
        "symbol": symbol,
        "quarter": quarter,
        "period": quarter,
        "eventDate": parent_date,
        "source": "1Q69",
        "sourceFolder": str(CURRENT_ROOT),
        "stem": stem,
    }


def detect_past_file(path: Path, quarter: str) -> dict | None:
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
        "sourceFolder": str(PAST_ROOT / quarter),
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
            path.name,
        ]
    ).lower()


def iter_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
            yield path


def build_index() -> dict:
    groups: dict[str, dict] = {}

    if PAST_ROOT.exists():
        for quarter_dir in sorted([p for p in PAST_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name):
            quarter = quarter_dir.name.upper()
            scan_root = quarter_dir / "OPPDAY"
            if not scan_root.exists():
                scan_root = quarter_dir
            for path in iter_files(scan_root):
                if "\\Analyst\\" in str(path):
                    continue
                meta = detect_past_file(path, quarter)
                if meta:
                    add_group(groups, meta, path)

    if CURRENT_ROOT.exists():
        for path in iter_files(CURRENT_ROOT):
            meta = detect_current_file(path)
            if meta:
                add_group(groups, meta, path)

    items = list(groups.values())
    for item in items:
        item["files"].sort(key=lambda f: (f["extension"] != ".md", f["name"].lower()))
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
            "markdownItems": sum(1 for item in items if item["hasMarkdown"]),
            "pdfItems": sum(1 for item in items if item["hasPdf"]),
            "pastRootExists": PAST_ROOT.exists(),
            "currentRootExists": CURRENT_ROOT.exists(),
        },
    }


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
                self.send_json(
                    {
                        "updatedAt": cache["updated_at"],
                        "stats": cache["stats"],
                        "items": cache["items"],
                    }
                )
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
    refresh_cache()
    thread = threading.Thread(target=daily_refresh_loop, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Oppday dashboard: http://{HOST}:{PORT}", flush=True)
    print(f"Indexed {cache['stats']['items']} items from OPPDAY folders.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
