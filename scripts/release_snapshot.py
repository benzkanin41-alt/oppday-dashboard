from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_store as store


@contextmanager
def release_lock():
    store.WORK.mkdir(parents=True, exist_ok=True)
    path = store.WORK / "release.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("Another OPPDAY release is in progress; preserve its lock") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def _public_stats(items: list[dict]) -> dict:
    import server
    symbols = sorted({item["symbol"] for item in items})
    return {
        "items": len(items),
        "symbols": len(symbols),
        "quarters": sorted({item["quarter"] for item in items}, key=server.quarter_rank, reverse=True),
        "sources": sorted({item["source"] for item in items}, key=server.quarter_rank, reverse=True),
        "tickerSet": symbols,
        "markdownItems": sum(bool(item["hasMarkdown"]) for item in items),
        "pdfItems": sum(bool(item["hasPdf"]) for item in items),
    }


def _copy_blob(source: Path, expected_size: int | None = None, expected_sha256: str | None = None) -> Path:
    before = source.stat()
    if expected_size is not None and before.st_size != expected_size:
        raise ValueError(f"Source size changed since indexing: {source}")
    digest = store.sha256(source)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(f"Source bytes changed after QA verification: {source}")
    target = store.WORK / "blobs" / digest[:2] / (digest + source.suffix.lower())
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(target.name + ".tmp")
        shutil.copy2(source, temporary)
        if store.sha256(temporary) != digest:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Snapshot copy failed SHA-256 verification: {source}")
        os.replace(temporary, target)
    elif store.sha256(target) != digest:
        raise ValueError(f"Snapshot blob failed SHA-256 verification: {target}")
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Source changed while creating its snapshot: {source}")
    return target


def verify_run_provenance(run_id: str, items: list[dict]) -> dict:
    profile = store.read_json(store.PROFILE)
    run_root = Path(profile["runRoot"])
    run_dir = run_root / "runs" / run_id
    run_dir.resolve().relative_to((run_root / "runs").resolve())
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Original run manifest/QA evidence is missing; recover or requalify before publishing")
    manifest = store.read_json(manifest_path)
    requested = {str(item["registrationId"]) for item in items}
    selected = [item for item in manifest.get("items", []) if str(item.get("registration_id")) in requested]
    if {str(item.get("registration_id")) for item in selected} != requested:
        raise ValueError("Release selection is absent from the original run manifest")
    manifest = {**manifest, "items": selected}
    skill_scripts = Path(r"C:\Users\USER\.codex\skills\multiagent-oppday\scripts")
    sys.path.insert(0, str(skill_scripts))
    from publishing import verify_run
    from workflow_common import parse_quarter
    quarters = {item["quarter"] for item in items}
    if len(quarters) != 1:
        raise ValueError("One run cannot publish multiple quarters")
    verification = verify_run(
        manifest=manifest, run_dir=run_dir, quarter=parse_quarter(quarters.pop()),
        oppday_root=Path(profile.get("oppdayRoot", r"D:\OneDrive\stock\OPPDAY")),
        valuation_map_path=Path(profile["valuationMap"]),
        default_valuation_root=Path(profile.get("valuationRoot", r"D:\OneDrive\stock\Valuation หุ้น")),
        record_status=False,
    )
    if verification.get("pass") is not True:
        raise ValueError("Run source/Agent6/Valuation provenance failed fresh verification")
    accepted_items = {str(item["registration_id"]): item for item in selected}
    for scanned in items:
        accepted_item = accepted_items[str(scanned["registrationId"])]
        handoff_path = run_dir / "staging_final" / accepted_item["event_date"] / accepted_item["ticker"] / "agent6_handoff.json"
        handoff = store.read_json(handoff_path)
        if handoff.get("run_id") != run_id or str(handoff.get("registration_id")) != str(scanned["registrationId"]):
            raise ValueError("Agent6 output identity differs from the selected dashboard record")
        if sorted(entry["extension"] for entry in scanned["files"]) != [".md", ".pdf"]:
            raise ValueError("A new run must publish its exact reviewed Markdown/PDF summary set")
        for entry in scanned["files"]:
            key = "conclusion_md" if entry["extension"] == ".md" else "conclusion_pdf"
            artifact = Path(handoff["outputs"][key])
            artifact.resolve().relative_to(run_dir.resolve())
            expected_digest = handoff["output_sha256"][key]
            if store.sha256(artifact) != expected_digest or store.sha256(Path(entry["path"])) != expected_digest:
                raise ValueError("Scanned summary bytes differ from the exact accepted Agent6 output")
    return verification


def selection_signature(items: list[dict], digests: dict[str, str] | None = None) -> str:
    from scripts.build_static_site import public_item
    values = []
    for item in sorted(items, key=lambda value: value["id"]):
        values.append({"item": public_item(item), "files": [
            {"id": entry["id"], "sha256": (digests or {}).get(entry["id"]) or store.sha256(Path(entry["path"]))}
            for entry in item["files"]
        ]})
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def release_id_for(run_id: str, registrations: list[str]) -> str:
    import server
    selected = [item for item in server.build_index()["items"] if item.get("runId") == run_id
                and str(item.get("registrationId")) in registrations]
    return f"release-{run_id}-{selection_signature(selected)[:12]}"


def frozen_text_loader(item: dict):
    import server
    names = {str(Path(entry["path"])): entry["name"] for entry in item["files"] if entry.get("path")}
    return lambda path: server.read_text_file(path, display_name=names.get(str(path)))


def require_earning_call_summary(item: dict) -> None:
    stem = f"{item['symbol']}-Earning call-{item['quarter']}"
    files = item.get("files", [])
    if not files or not any(entry.get("extension", "").lower() == ".md" for entry in files):
        raise ValueError("New records require an Earning call Markdown summary")
    for entry in files:
        name = Path(entry["name"])
        if name.stem.casefold() != stem.casefold() or name.suffix.lower() not in (".md", ".pdf"):
            raise ValueError("Only Earning call summaries may enter a new release")


def prepare_release(
    release_id: str, *, run_id: str = "", registrations: list[str] | None = None,
    baseline_only: bool = False, qualification_id: str = "", tickers: list[str] | None = None,
) -> dict:
    import server
    from scripts import build_static_site as static
    if not store.RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError("Invalid release ID")
    expected = sorted(set(registrations or []))
    if qualification_id and (run_id or expected or baseline_only or not tickers):
        raise ValueError("Current qualification requires only its exact ticker set, not a replacement source run")
    if tickers and not qualification_id:
        raise ValueError("Ticker selection requires an explicit current qualification")
    if not baseline_only and not qualification_id and (not run_id or not expected):
        raise ValueError("A release must name its exact run and registration set")
    target = store.RELEASES / release_id
    if store.CURRENT.exists():
        previous = store.current_pointer()
        previous_dir = store.release_directory(previous["releaseId"])
        base_public = previous_dir / "public"
        old_local = store.read_json(previous_dir / "index.local.json")
        previous_id = previous["releaseId"]
    else:
        base_public = ROOT / "docs"
        old_local = None
        previous_id = "legacy-public-baseline"
    baseline = store.read_json(base_public / "data/index.json")
    raw = server.build_index()
    source_by_id = {item["id"]: item for item in raw["items"]}
    incoming = [] if baseline_only else [
        item for item in raw["items"]
        if item.get("runId") == run_id and str(item.get("registrationId")) in expected
    ]
    if qualification_id:
        from scripts import requalification
        incoming = requalification.select_items(qualification_id, tickers, raw["items"])
        expected = sorted(str(item["registrationId"]) for item in incoming)
    actual = sorted(str(item.get("registrationId")) for item in incoming)
    if actual != expected:
        raise ValueError(f"Release selection mismatch: expected={expected}, actual={actual}")
    for item in incoming:
        require_earning_call_summary(item)
    source_digests = {entry["id"]: store.sha256(Path(entry["path"]))
                      for item in incoming for entry in item["files"]}
    qualification_proof = None
    if incoming:
        if qualification_id:
            qualification_proof = requalification.verify_qualification(qualification_id, incoming)
        else:
            verify_run_provenance(run_id, incoming)
    for item in incoming:
        if item.get("workflowStatus") not in server.COMPLETED_CONCLUSION_STATUSES:
            raise ValueError("An unfinished conclusion cannot enter a release")
        status_path = server.OPPDAY_ROOT / item["quarter"] / "Oppday" / f"workflow_status_{item['quarter']}.csv"
        status = server.read_workflow_status(status_path)
        row = server.find_workflow_row(status, item["symbol"], item["eventDate"])
        if not row or row.get("hash_status") != "pass" or not row.get("valuation_status", "").startswith("done_"):
            raise ValueError("Valuation and source hashes must pass before preparing a release")
        for prefix in ("conclusion", "transcript", "presentation"):
            source = row.get(prefix + "_source_path")
            target_file = row.get(prefix + "_target_path")
            digest = row.get(prefix + "_sha256_source")
            if not source and prefix == "presentation" and item["workflowStatus"] == "done_transcript_only":
                continue
            if not source or not target_file or not digest:
                raise ValueError(f"Missing verified {prefix} evidence for {item['symbol']}")
            if store.sha256(Path(source)) != digest or store.sha256(Path(target_file)) != digest:
                raise ValueError(f"Fresh {prefix} SHA-256 verification failed for {item['symbol']}")
    signature = selection_signature(incoming, source_digests)
    if target.exists():
        manifest = store.read_json(target / "manifest.json")
        if manifest.get("qualificationId", "") != qualification_id:
            raise ValueError("Existing release ID belongs to a different qualification")
        if qualification_id and manifest.get("qualificationVerification") != qualification_proof:
            raise ValueError("Qualification evidence changed; prepare a new release ID")
        if (manifest.get("runId"), manifest.get("registrations")) != (run_id, expected):
            raise ValueError("Existing release ID belongs to a different selection")
        if manifest.get("sourceSelectionSha256") != signature:
            raise ValueError("Selected source bytes changed; prepare a new release ID")
        return verify_release(release_id)
    public_items = {item["id"]: item for item in baseline["items"]}
    for item in incoming:
        public_items[item["id"]] = static.public_item(item, include_markdown=False)
    ordered = sorted(public_items.values(), key=lambda item: (
        server.quarter_rank(item["quarter"]), item["eventDate"], item["symbol"], item["latestModified"]
    ), reverse=True)
    # Keep every accepted historical payload byte-for-byte unless selected for update.
    old_local_by_id = {item["id"]: item for item in (old_local or {}).get("items", [])}
    incoming_by_id = {item["id"]: item for item in incoming}
    frozen_incoming = copy.deepcopy(incoming_by_id)
    for item in frozen_incoming.values():
        for entry in item["files"]:
            blob = _copy_blob(Path(entry["path"]), entry["size"], source_digests[entry["id"]])
            entry["path"] = str(blob)
            entry["sha256"] = source_digests[entry["id"]]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stats = _public_stats(ordered)
    store.RELEASES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".candidate-", dir=store.RELEASES) as temporary:
        stage = Path(temporary)
        item_dir = stage / "public/data/items"
        item_dir.mkdir(parents=True)
        local_items = []
        missing_files = []
        for item in ordered:
            item_id = item["id"]
            if item_id in incoming_by_id:
                static.write_json(item_dir / f"{item_id}.json", {
                    "item": static.public_item(frozen_incoming[item_id], include_markdown=True,
                                               text_loader=frozen_text_loader(frozen_incoming[item_id]))
                })
            else:
                shutil.copy2(base_public / "data/items" / f"{item_id}.json", item_dir / f"{item_id}.json")
            source_item = source_by_id.get(item_id)
            frozen_legacy = None
            if item_id not in incoming_by_id and item_id not in old_local_by_id and source_item:
                if any(not Path(entry["path"]).is_file() for entry in source_item["files"]):
                    raise ValueError("Historical source has unavailable files; preserve the previous release")
                if [static.public_file_entry(entry) for entry in source_item["files"]] != item["files"]:
                    raise ValueError("Historical source metadata differs from its accepted public record")
                frozen_legacy = copy.deepcopy(source_item)
                for entry in frozen_legacy["files"]:
                    digest = store.sha256(Path(entry["path"]))
                    entry["path"] = str(_copy_blob(Path(entry["path"]), entry["size"], digest))
                    entry["sha256"] = digest
                accepted = store.read_json(base_public / "data/items" / f"{item_id}.json")["item"]
                fresh = static.public_item(frozen_legacy, include_markdown=True, text_loader=frozen_text_loader(frozen_legacy))
                if fresh.get("markdown", "") != accepted.get("markdown", ""):
                    raise ValueError("Historical source text differs from its accepted public summary")
            local = copy.deepcopy(frozen_incoming.get(item_id) or old_local_by_id.get(item_id) or frozen_legacy or source_item or item)
            local_files = []
            for entry in local["files"]:
                entry = dict(entry)
                source = Path(entry["path"]) if entry.get("path") else None
                if source is None or not source.is_file():
                    missing_files.append({"itemId": item_id, "fileId": entry["id"], "name": entry["name"]})
                    entry.pop("path", None)
                else:
                    blob = _copy_blob(source, entry.get("size"), entry.get("sha256"))
                    entry["path"] = str(blob)
                    entry["sha256"] = store.sha256(blob)
                local_files.append(entry)
            local["files"] = local_files
            usable_ids = {entry["id"] for entry in local_files if entry.get("path")}
            if local.get("primaryPdfId") not in usable_ids:
                local["primaryPdfId"] = None
            local_items.append(local)
        public_payload = {
            "mode": "static", "releaseId": release_id, "updatedAt": now,
            "stats": stats, "items": ordered,
        }
        static.write_json(stage / "public/data/index.json", public_payload)
        static.write_json(stage / "index.local.json", {
            "releaseId": release_id, "updatedAt": now, "stats": stats, "items": local_items,
        })
        payload_hashes = {path.name: store.sha256(path) for path in item_dir.glob("*.json")}
        manifest = {
            "schemaVersion": 1, "releaseId": release_id, "previousReleaseId": previous_id,
            "baseIndexSha256": store.sha256(base_public / "data/index.json"),
            "runId": run_id, "registrations": expected, "createdAt": now,
            "qualificationId": qualification_id, "qualificationVerification": qualification_proof,
            "sourceRunIds": sorted({item["runId"] for item in incoming}),
            "sourceSelectionSha256": signature,
            "baselineItemCount": len(baseline["items"]), "itemCount": len(ordered),
            "selectedItemIds": sorted(incoming_by_id), "indexSha256": store.sha256(stage / "public/data/index.json"),
            "localIndexSha256": store.sha256(stage / "index.local.json"),
            "payloadHashes": payload_hashes, "missingLocalFiles": missing_files,
        }
        if missing_files:
            raise ValueError(f"Local snapshot has {len(missing_files)} unavailable files; preserve the previous release")
        static.write_json(stage / "manifest.json", manifest)
        os.replace(stage, target)
    return verify_release(release_id)


def verify_release(release_id: str, *, verify_blobs: bool = False) -> dict:
    directory = store.release_directory(release_id)
    manifest = store.read_json(directory / "manifest.json")
    public = directory / "public/data"
    index = store.read_json(public / "index.json")
    if manifest["releaseId"] != release_id or index["releaseId"] != release_id:
        raise ValueError("Release identity mismatch")
    if store.sha256(public / "index.json") != manifest["indexSha256"]:
        raise ValueError("Release index hash mismatch")
    if store.sha256(directory / "index.local.json") != manifest["localIndexSha256"]:
        raise ValueError("Local snapshot hash mismatch")
    ids = [item["id"] for item in index["items"]]
    from scripts.build_static_site import public_item
    local_index = store.read_json(directory / "index.local.json")
    if {item["id"]: public_item(item) for item in local_index["items"]} != {item["id"]: item for item in index["items"]}:
        raise ValueError("Local/public release metadata differs")
    paths = {path.stem: path for path in (public / "items").glob("*.json")}
    if len(ids) != len(set(ids)) or set(ids) != set(paths):
        raise ValueError("Missing, duplicate or orphan release payloads")
    path_re = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
    def scan(value):
        if isinstance(value, str) and path_re.search(value):
            raise ValueError("A local path leaked into the public release")
        if isinstance(value, dict):
            for nested in value.values():
                scan(nested)
        if isinstance(value, list):
            for nested in value:
                scan(nested)
    scan(index)
    for item_id, path in paths.items():
        payload = store.read_json(path)
        if payload.get("item", {}).get("id") != item_id:
            raise ValueError("Payload identity mismatch")
        if store.sha256(path) != manifest["payloadHashes"].get(path.name):
            raise ValueError("Payload hash mismatch")
        scan(payload)
    blob_count = 0
    if verify_blobs:
        checked = set()
        for item in store.read_json(directory / "index.local.json")["items"]:
            for entry in item["files"]:
                if not entry.get("path"):
                    continue
                path = Path(entry["path"])
                path.resolve().relative_to((store.WORK / "blobs").resolve())
                if path not in checked:
                    if store.sha256(path) != entry.get("sha256"):
                        raise ValueError("Private file snapshot hash mismatch")
                    checked.add(path)
        blob_count = len(checked)
    return {"ok": True, "releaseId": release_id, "items": len(ids), "payloads": len(paths),
            "indexSha256": manifest["indexSha256"], "verifiedBlobs": blob_count,
            "selectedItemIds": manifest["selectedItemIds"], "previousReleaseId": manifest["previousReleaseId"]}


def export_release(release_id: str) -> dict:
    result = verify_release(release_id)
    directory = store.release_directory(release_id)
    manifest = store.read_json(directory / "manifest.json")
    if manifest.get("qualificationId"):
        from scripts.requalification import verify_prepared_release
        verify_prepared_release(release_id, manifest)
    from scripts import build_static_site as static
    with tempfile.TemporaryDirectory(prefix=".release-export-", dir=ROOT) as temporary:
        stage = Path(temporary)
        shutil.copytree(directory / "public/data", stage / "data")
        (stage / "static").mkdir()
        for source, destination in (("index.html", "index.html"), ("app.js", "static/app.js"), ("styles.css", "static/styles.css")):
            shutil.copy2(ROOT / "web" / source, stage / destination)
        (stage / ".nojekyll").write_text("", encoding="ascii")
        static.merge_oppday_stage(stage, ROOT / "docs")
    return result


def promote_release(release_id: str, verification: dict, *, bootstrap: bool = False) -> dict:
    result = verify_release(release_id, verify_blobs=True)
    manifest = store.read_json(store.release_directory(release_id) / "manifest.json")
    if manifest.get("qualificationId"):
        from scripts.requalification import verify_prepared_release
        verify_prepared_release(release_id, manifest)
    if not bootstrap:
        if verification.get("ok") is not True or verification.get("releaseId") != release_id:
            raise ValueError("Online byte verification must pass before Local promotion")
        if verification.get("indexSha256") != result["indexSha256"] or not verification.get("commit"):
            raise ValueError("Online verification is not bound to the selected release")
    elif verification.get("baselineVerified") is not True:
        raise ValueError("Bootstrap is allowed only for the verified pre-migration baseline")
    elif store.CURRENT.exists():
        previous = store.current_pointer()
        if previous.get("verification", {}).get("baselineVerified") is not True:
            raise ValueError("A published release cannot be replaced through bootstrap")
        previous_dir = store.release_directory(previous["releaseId"])
        previous_index = store.read_json(previous_dir / "public/data/index.json")
        next_index = store.read_json(store.release_directory(release_id) / "public/data/index.json")
        previous_manifest = store.read_json(previous_dir / "manifest.json")
        next_manifest = store.read_json(store.release_directory(release_id) / "manifest.json")
        if (previous_index["items"], previous_index["stats"], previous_manifest["payloadHashes"]) != (next_index["items"], next_index["stats"], next_manifest["payloadHashes"]):
            raise ValueError("Bootstrap reconciliation cannot change the accepted public dataset")
    pointer = {"releaseId": release_id, "indexSha256": result["indexSha256"],
               "promotedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "previousReleaseId": result["previousReleaseId"], "verification": verification}
    store.write_json_atomic(store.CURRENT, pointer)
    return {**result, "promoted": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and verify an explicit immutable OPPDAY release")
    parser.add_argument("action", choices=("prepare", "verify", "export", "promote"))
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--registration-id", action="append", default=[])
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--verify-blobs", action="store_true")
    parser.add_argument("--verification-file", type=Path)
    args = parser.parse_args()
    if args.action == "verify":
        result = verify_release(args.release_id, verify_blobs=args.verify_blobs)
    else:
        with release_lock():
            if args.action == "prepare":
                result = prepare_release(args.release_id, run_id=args.run_id, registrations=args.registration_id, baseline_only=args.baseline_only)
            elif args.action == "export":
                result = export_release(args.release_id)
            else:
                if args.verification_file is None:
                    raise ValueError("--verification-file is required")
                result = promote_release(args.release_id, store.read_json(args.verification_file))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
