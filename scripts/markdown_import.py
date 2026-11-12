"""Explicit, additive imports of existing Earning call Markdown, not report QA."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_store as store
import server
from scripts import build_static_site as static

ACTION = "import_existing_earning_call_markdown"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def import_directory(import_id: str) -> Path:
    require(bool(store.RELEASE_ID_RE.fullmatch(import_id)), "Invalid Markdown import ID")
    directory = store.WORK / "markdown-imports" / import_id
    directory.resolve().relative_to((store.ROOT / ".oppday-work").resolve())
    directory.resolve().relative_to((store.WORK / "markdown-imports").resolve())
    return directory


def check_authorization(authorization: dict, import_id: str, quarter: str) -> None:
    require(authorization.get("action") == ACTION
            and authorization.get("importId") == import_id
            and authorization.get("quarter") == quarter
            and authorization.get("preserveOriginals") is True
            and authorization.get("preserveHistory") is True
            and authorization.get("revoked") is not True
            and bool(authorization.get("userRequest")),
            "Explicit current Markdown-only import authorization is required")


def summary_root(quarter: str) -> Path:
    require(bool(re.fullmatch(r"[1-4]Q\d{2}", quarter)), "Invalid Markdown import quarter")
    profile = store.read_json(store.PROFILE)
    return Path(profile["oppdayRoot"]) / quarter / "Oppday" / server.SUMMARY_DIR_NAME


def read_markdown(path: Path, ticker: str, quarter: str) -> tuple[str, str]:
    before = path.stat()
    data = path.read_bytes()
    text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    require(bool(text.strip()) and "\x00" not in text and "\ufffd" not in text,
            "Markdown is empty or has invalid text")
    require(bool(re.match(rf"^#\s+{re.escape(ticker)}\s+Earning call\s+{quarter}\s*$",
                          text.splitlines()[0], re.IGNORECASE)),
            "Markdown heading differs from its ticker/quarter")
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            "Markdown changed while being read")
    return hashlib.sha256(data).hexdigest(), text


def source_aliases(quarter: str, authorization: dict | None = None) -> list[dict]:
    """Inherit only hash-bound accepted aliases, plus explicit current exceptions."""
    inherited = []
    if store.CURRENT.exists():
        release = store.release_directory(store.current_pointer()["releaseId"])
        manifest_path = release / "manifest.json"
        if manifest_path.exists():
            manifest = store.read_json(manifest_path)
            import_id = manifest.get("markdownImportId")
            if import_id:
                directory = import_directory(import_id)
                job = store.read_json(directory / "import.json")
                proof = manifest["markdownImportVerification"]
                require(store.sha256(directory / "import.json") == proof["requestSha256"]
                        and store.sha256(directory / "authorization.json") == proof["authorizationSha256"],
                        "Accepted source alias evidence changed")
                if job["quarter"] == quarter:
                    inherited = job.get("sourceAliases", [])
    result = {}
    for alias in inherited + (authorization or {}).get("sourceAliases", []):
        require(set(alias) == {"ticker", "eventDate", "filename", "sha256"}, "Invalid source alias fields")
        ticker, name = alias["ticker"], alias["filename"]
        require(bool(re.fullmatch(r"[A-Z0-9&.\-]+", ticker))
                and Path(name).name == name and "/" not in name and "\\" not in name
                and Path(name).suffix == ".md" and bool(re.fullmatch(r"[a-f0-9]{64}", alias["sha256"])),
                "Invalid source alias identity")
        date.fromisoformat(alias["eventDate"])
        key = (ticker, alias["eventDate"])
        require(key not in result or result[key] == alias, "Conflicting source alias")
        result[key] = alias
    return sorted(result.values(), key=lambda alias: (alias["eventDate"], alias["ticker"]))


def alias_for(path: Path, quarter: str, aliases: list[dict]) -> dict | None:
    root = summary_root(quarter)
    return next((alias for alias in aliases
                 if path.resolve() == (root / alias["eventDate"] / alias["filename"]).resolve()), None)


def source_metadata(path: Path, quarter: str, aliases: list[dict], status_row=None) -> dict:
    alias = alias_for(path, quarter, aliases)
    identity = path.with_name(f"{alias['ticker']}-Earning call-{quarter}.md") if alias else path
    meta = server.detect_current_file(identity, quarter, summary_root(quarter), status_row)
    require(meta is not None, "Unapproved Markdown filename")
    return meta


def verify_alias_sources(quarter: str, alias: dict) -> None:
    root = summary_root(quarter)
    primary = root.parent / alias['eventDate'] / alias['ticker'] / alias['filename']
    summary = root / alias['eventDate'] / alias['filename']
    standard = f"{alias['ticker']}-Earning call-{quarter}.md"
    sources = [summary, primary]
    sources += [p for p in (summary.with_name(standard), primary.with_name(standard)) if p.exists()]
    for source in sources:
        require(source.resolve().is_relative_to(root.parent.resolve()), 'Source alias escapes source root')
        require(store.sha256(source) == alias['sha256'], 'Source alias hash changed or copies differ')
        read_markdown(source, alias['ticker'], quarter)


def discover(quarter: str, aliases: list[dict] | None = None) -> list[Path]:
    root = summary_root(quarter)
    paths = sorted(root.rglob(f"*-Earning call-{quarter}.md"))
    for alias in source_aliases(quarter) if aliases is None else aliases:
        path = root / alias["eventDate"] / alias["filename"]
        canonical = path.with_name(f"{alias['ticker']}-Earning call-{quarter}.md")
        require(path != canonical, "Source alias must use a nonstandard filename")
        verify_alias_sources(quarter, alias)
        # A later standard-named copy may coexist only with the exact approved
        # bytes. Keep the bound original and its one stable reader identity.
        if canonical in paths:
            paths.remove(canonical)
        paths.append(path)
    require(bool(paths), "No Earning call Markdown files found")
    return sorted(paths)


def create_request(import_id: str, quarter: str, authorization: dict) -> dict:
    directory = import_directory(import_id)
    require(not directory.exists(), "Use a new immutable Markdown import ID")
    check_authorization(authorization, import_id, quarter)
    root = summary_root(quarter)
    previous_id = store.current_pointer()["releaseId"]
    previous = store.release_directory(previous_id)
    index_path = previous / "public/data/index.json"
    baseline = store.read_json(index_path)
    baseline_by_id = {item["id"]: item for item in baseline["items"]}
    status = server.read_workflow_status(root.parent / f"workflow_status_{quarter}.csv")
    aliases = source_aliases(quarter, authorization)
    entries = []
    for path in discover(quarter, aliases):
        require(len(path.relative_to(root).parts) == 2, "Markdown must be in its canonical event-date folder")
        date.fromisoformat(path.parent.name)
        match = re.fullmatch(rf"([A-Z0-9&.\-]+)-Earning call-{quarter}", path.stem)
        alias = alias_for(path, quarter, aliases)
        require(match is not None or alias is not None, "Invalid Earning call Markdown filename")
        ticker = alias["ticker"] if alias else match[1]
        digest, text = read_markdown(path, ticker, quarter)
        row = server.find_workflow_row(status, ticker, path.parent.name)
        meta = source_metadata(path, quarter, aliases, row)
        groups = {}
        server.add_group(groups, meta, path)
        item = next(iter(groups.values()))
        disposition = "add"
        payload_sha = None
        if item["id"] in baseline_by_id:
            payload_path = previous / "public/data/items" / f"{item['id']}.json"
            accepted = store.read_json(payload_path)["item"]
            require(accepted.get("markdown") == static.redact_local_paths(text),
                    "Existing accepted Markdown differs; history cannot be overwritten")
            disposition, payload_sha = "preserve_existing", store.sha256(payload_path)
        entries.append({"itemId": item["id"], "ticker": ticker, "quarter": quarter,
                        "eventDate": item["eventDate"], "runId": item["runId"],
                        "registrationId": item["registrationId"], "workflowStatus": item["workflowStatus"],
                        "originalPath": str(path), "sha256": digest, "disposition": disposition,
                        "baselinePayloadSha256": payload_sha})
    job = {"schemaVersion": 1, "kind": "existing-earning-call-markdown-import",
           "importId": import_id, "quarter": quarter, "createdAt": datetime.now(timezone.utc).isoformat(),
           "baseReleaseId": previous_id, "baseIndexSha256": store.sha256(index_path), "entries": entries,
           "pdfValidation": "not_requested", "semanticValidation": "not_recertified_existing_source"}
    if aliases:
        job["sourceAliases"] = aliases
    directory.mkdir(parents=True)
    store.write_json_atomic(directory / "authorization.json", authorization)
    store.write_json_atomic(directory / "import.json", job)
    return job


def load_request(import_id: str, *, require_complete_inventory: bool = True) -> tuple[dict, dict, list[tuple[dict, str]]]:
    directory = import_directory(import_id)
    job = store.read_json(directory / "import.json")
    require(job.get("schemaVersion") == 1 and job.get("kind") == "existing-earning-call-markdown-import"
            and job.get("importId") == import_id, "Markdown import identity differs")
    check_authorization(store.read_json(directory / "authorization.json"), import_id, job["quarter"])
    require(job.get("pdfValidation") == "not_requested"
            and job.get("semanticValidation") == "not_recertified_existing_source",
            "An MD import cannot claim report/PDF QA")
    base = store.release_directory(job["baseReleaseId"])
    require(store.sha256(base / "public/data/index.json") == job["baseIndexSha256"], "Import baseline changed")
    baseline = store.read_json(base / "public/data/index.json")
    baseline_by_id = {item["id"]: item for item in baseline["items"]}
    root = summary_root(job["quarter"])
    entries = job["entries"]
    aliases = job.get("sourceAliases", [])
    # Each exception must be explicitly approved or inherited from this request's baseline.
    approved = store.read_json(directory / "authorization.json").get("sourceAliases", [])
    base_manifest = base / "manifest.json"
    if base_manifest.exists():
        prior_import = store.read_json(base_manifest).get("markdownImportId")
        if prior_import:
            approved += store.read_json(import_directory(prior_import) / "import.json").get("sourceAliases", [])
    require(all(alias in approved for alias in aliases), "Unapproved source alias")
    require(bool(entries) and len({entry["itemId"] for entry in entries}) == len(entries),
            "Missing or duplicate Markdown import entries")
    if require_complete_inventory:
        require({path.resolve() for path in discover(job["quarter"], aliases)}
                == {Path(entry["originalPath"]).resolve() for entry in entries},
                "Markdown cohort changed; prepare a new import request")
    checked = []
    for entry in entries:
        ticker = entry["ticker"]
        require(bool(re.fullmatch(r"[A-Z0-9&.\-]+", ticker)) and entry["quarter"] == job["quarter"],
                "Markdown ticker/quarter differs")
        date.fromisoformat(entry["eventDate"])
        canonical = root / entry["eventDate"] / f"{ticker}-Earning call-{job['quarter']}.md"
        alias = next((a for a in aliases if a["ticker"] == ticker and a["eventDate"] == entry["eventDate"]), None)
        source = canonical.with_name(alias["filename"]) if alias else canonical
        canonical.resolve().relative_to(root.resolve())
        require(Path(entry["originalPath"]).resolve() == source.resolve(), "Noncanonical Markdown source")
        expected_id = server.item_id([job["quarter"], job["quarter"], ticker, entry["eventDate"], canonical.stem])
        require(entry["itemId"] == expected_id, "Markdown record ID differs")
        digest, text = read_markdown(source, ticker, job["quarter"])
        if alias:
            verify_alias_sources(job['quarter'], alias)
        require(digest == entry["sha256"], "Original Markdown hash changed")
        if entry["disposition"] == "preserve_existing":
            require(entry["itemId"] in baseline_by_id, "Preserved record is absent from the baseline")
            payload = base / "public/data/items" / f"{entry['itemId']}.json"
            require(store.sha256(payload) == entry["baselinePayloadSha256"]
                    and store.read_json(payload)["item"].get("markdown") == static.redact_local_paths(text),
                    "Accepted historical Markdown differs")
        else:
            require(entry["disposition"] == "add" and entry["itemId"] not in baseline_by_id,
                    "MD imports may add records, never replace history")
        checked.append((entry, text))
    return job, baseline, checked


def select_items(import_id: str) -> list[dict]:
    job, _, checked = load_request(import_id)
    items = []
    for entry, _ in checked:
        if entry["disposition"] != "add":
            continue
        path = Path(entry["originalPath"])
        meta = source_metadata(path, entry["quarter"], job.get("sourceAliases", []))
        meta.update({key: entry[key] for key in ("runId", "registrationId", "workflowStatus")})
        groups = {}
        server.add_group(groups, meta, path)
        item = next(iter(groups.values()))
        item.update(primaryMarkdownId=item["files"][0]["id"], primaryPdfId=None)
        items.append(item)
    return items


def verify_import(import_id: str, items: list[dict], *, require_complete_inventory: bool = True) -> dict:
    job, _, checked = load_request(import_id, require_complete_inventory=require_complete_inventory)
    expected = {entry["itemId"]: entry for entry, _ in checked if entry["disposition"] == "add"}
    require(len(items) == len(expected) and {item["id"] for item in items} == set(expected),
            "Markdown import selection differs")
    for item in items:
        entry = expected[item["id"]]
        require(all(item.get(key) == entry[key] for key in ("quarter", "eventDate", "runId", "registrationId", "workflowStatus"))
                and item["symbol"] == entry["ticker"], "Imported Markdown metadata differs")
        files = item["files"]
        require(len(files) == 1 and files[0]["extension"] == ".md" and not item["hasPdf"]
                and item["primaryPdfId"] is None and item["hasMarkdown"] is True
                and item["primaryMarkdownId"] == files[0]["id"], "MD-only imports cannot include PDFs or other files")
        file = files[0]
        original = Path(entry["originalPath"])
        require(file["id"] == server.file_id(original) and file["name"] == original.name
                and store.sha256(Path(file["path"])) == entry["sha256"], "Imported Markdown bytes/identity differ")
    directory = import_directory(import_id)
    return {"pass": True, "kind": "explicit-existing-markdown-import", "importId": import_id,
            "authorizationSha256": store.sha256(directory / "authorization.json"),
            "requestSha256": store.sha256(directory / "import.json"),
            "cohortItemIds": sorted(entry["itemId"] for entry, _ in checked),
            "selectedItemIds": sorted(expected), "baseReleaseId": job["baseReleaseId"],
            "pdfValidation": "not_requested", "semanticValidation": "not_recertified_existing_source"}


def verify_prepared_release(release_id: str, manifest: dict) -> dict:
    directory = store.release_directory(release_id)
    proof = manifest["markdownImportVerification"]
    selected = manifest["selectedItemIds"]
    local = store.read_json(directory / "index.local.json")
    items = [item for item in local["items"] if item["id"] in selected]
    # Later arrivals belong to another request, not this immutable release or rollback.
    current = verify_import(manifest["markdownImportId"], items, require_complete_inventory=False)
    require(current == proof and current["selectedItemIds"] == sorted(selected)
            and current["baseReleaseId"] == manifest["previousReleaseId"],
            "Markdown import evidence changed; prepare a new release ID")
    base = store.release_directory(current["baseReleaseId"])
    baseline = store.read_json(base / "public/data/index.json")
    candidate = store.read_json(directory / "public/data/index.json")
    candidate_by_id = {item["id"]: item for item in candidate["items"]}
    for old in baseline["items"]:
        require(candidate_by_id.get(old["id"]) == old, "Markdown import changed historical metadata")
        name = f"{old['id']}.json"
        require(store.sha256(base / "public/data/items" / name)
                == store.sha256(directory / "public/data/items" / name), "Markdown import changed a historical payload")
    require(set(candidate_by_id) == {item["id"] for item in baseline["items"]} | set(selected),
            "Markdown import added unexpected records")
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-id", required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--authorization-file", type=Path, required=True)
    args = parser.parse_args()
    from scripts.release_snapshot import release_lock
    with release_lock():
        job = create_request(args.import_id, args.quarter, store.read_json(args.authorization_file))
    print(json.dumps(job, ensure_ascii=False))


if __name__ == "__main__":
    main()
