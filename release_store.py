from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".oppday-work"
PROFILE = WORK / "project-profile.json"
RELEASES = WORK / "releases"
CURRENT = RELEASES / "current.json"
RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_mode() -> bool:
    if CURRENT.exists():
        return True
    if not PROFILE.exists():
        return False
    return read_json(PROFILE).get("releaseMode") == "snapshot"


def release_directory(release_id: str) -> Path:
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError("Invalid release ID")
    path = RELEASES / release_id
    if not path.is_dir():
        raise FileNotFoundError(f"Release does not exist: {release_id}")
    return path


def current_pointer() -> dict:
    pointer = read_json(CURRENT)
    directory = release_directory(str(pointer.get("releaseId", "")))
    if sha256(directory / "public/data/index.json") != pointer.get("indexSha256"):
        raise ValueError("Active release index failed integrity verification")
    return pointer


def current_cache() -> dict:
    pointer = current_pointer()
    directory = release_directory(pointer["releaseId"])
    manifest = read_json(directory / "manifest.json")
    if sha256(directory / "index.local.json") != manifest["localIndexSha256"]:
        raise ValueError("Active Local release index failed integrity verification")
    payload = read_json(directory / "index.local.json")
    if payload.get("releaseId") != pointer["releaseId"]:
        raise ValueError("Local release identity differs from the active pointer")
    items = payload["items"]
    public_index = read_json(directory / "public/data/index.json")
    public_ids = {item["id"] for item in public_index["items"]}
    if len(items) != len(public_ids) or {item["id"] for item in items} != public_ids:
        raise ValueError("Active Local/public record sets differ")
    from scripts.build_static_site import public_item
    if {item["id"]: public_item(item) for item in items} != {item["id"]: item for item in public_index["items"]}:
        raise ValueError("Active Local/public release metadata differs")
    blob_root = WORK / "blobs"
    if blob_root.resolve() != blob_root.absolute():
        raise ValueError("Private blob root must not redirect outside the project")
    for item in items:
        for entry in item["files"]:
            if entry.get("path"):
                Path(entry["path"]).resolve().relative_to(blob_root.resolve())
    return {
        "items": items,
        "by_item_id": {item["id"]: item for item in items},
        "by_file_id": {
            entry["id"]: entry for item in items for entry in item["files"]
            if entry.get("path")
        },
        "updated_at": payload["updatedAt"],
        "stats": payload["stats"],
        "release_id": pointer["releaseId"],
        "release_directory": str(directory),
        "payload_hashes": manifest["payloadHashes"],
    }


def item_from_cache(cache: dict, item_id: str) -> dict:
    directory = Path(cache["release_directory"])
    path = directory / "public/data/items" / f"{item_id}.json"
    expected = cache["payload_hashes"][path.name]
    if sha256(path) != expected:
        fallback = ROOT / "docs/data/items" / path.name
        if not fallback.is_file() or sha256(fallback) != expected:
            raise ValueError("Active item payload failed integrity verification")
        path = fallback
    public = read_json(path)["item"]
    local = dict(cache["by_item_id"][item_id])
    local["markdown"] = public.get("markdown", "")
    return {"item": local, "releaseId": cache["release_id"]}
