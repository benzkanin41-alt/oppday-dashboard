from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_store as store
from scripts import release_snapshot as snapshots

REPOSITORY = "benzkanin41-alt/oppday-dashboard"
ONLINE = "https://benzkanin41-alt.github.io/oppday-dashboard/"
MANAGER = Path(r"C:\Users\USER\Documents\Codex\LocalDashboardPorts\dashboard_ports.py")
DEFAULT_GIT = Path(r"C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe")


def emit(stage: str, **values) -> None:
    print(json.dumps({"stage": stage, **values}, ensure_ascii=False), flush=True)


def command(arguments: list[str], *, timeout: int = 180) -> str:
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({arguments[0]} {arguments[1]}): {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def git(*arguments: str) -> str:
    executable = os.environ.get("OPPDAY_GIT") or shutil.which("git") or str(DEFAULT_GIT)
    return command([executable, *arguments])


def allowed_public_path(path: str) -> bool:
    from scripts.sync_static_site import FIXED_GENERATED_FILES, direct_item_id
    return path in FIXED_GENERATED_FILES or bool(direct_item_id(path))


def tree_hash(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            digest.update(child.relative_to(path).as_posix().encode())
            digest.update(bytes.fromhex(store.sha256(child)))
    return digest.hexdigest()


def sync_remote(release_id: str) -> None:
    if git("branch", "--show-current") != "main":
        raise ValueError("Release publication requires branch main")
    if git("status", "--porcelain"):
        raise ValueError("Commit reviewed code or resolve unrelated changes before publishing data")
    git("fetch", "origin", "main")
    ahead = git("log", "--format=%s", "origin/main..HEAD").splitlines()
    if ahead and any(message != f"Publish OPPDAY release {release_id}" for message in ahead):
        raise ValueError("Unpublished unrelated commits block the data release")
    if ahead:
        git("rebase", "origin/main")
    else:
        git("merge", "--ff-only", "origin/main")


def publish_files(release_id: str) -> str:
    before = tree_hash(ROOT / "docs/bubble-risk-dashboard")
    snapshots.export_release(release_id)
    if tree_hash(ROOT / "docs/bubble-risk-dashboard") != before:
        raise ValueError("Co-hosted Bubble Dashboard changed during export")
    changed = set(filter(None, git("diff", "--name-only").splitlines()))
    changed.update(filter(None, git("ls-files", "--others", "--exclude-standard").splitlines()))
    if any(not allowed_public_path(path) for path in changed):
        raise ValueError("An unrelated or private path was found in the release working tree")
    from scripts.sync_static_site import git_add_chunks
    for chunk in git_add_chunks(sorted(changed)):
        git("add", "--", *chunk)
    staged = set(filter(None, git("diff", "--cached", "--name-only").splitlines()))
    if staged != changed:
        raise ValueError("Staged release paths differ from the exact generated set")
    if staged:
        git("diff", "--cached", "--check")
        git("commit", "-m", f"Publish OPPDAY release {release_id}")
    # Reconcile a concurrent Bubble update without rewriting its files or history.
    git("fetch", "origin", "main")
    git("rebase", "origin/main")
    git("push", "origin", "main")
    return git("rev-parse", "HEAD")


def wait_pages(commit: str, timeout: int = 600) -> dict:
    deadline = time.monotonic() + timeout
    dispatched = False
    while time.monotonic() < deadline:
        runs = json.loads(command(["gh", "run", "list", "--repo", REPOSITORY,
                                   "--limit", "15", "--json", "databaseId,status,conclusion,headSha,workflowName,url"]))
        candidates = [run for run in runs if run["workflowName"] == "Deploy GitHub Pages"]
        exact = [run for run in candidates if run["headSha"] == commit]
        for run in exact:
            if run["status"] == "completed" and run["conclusion"] == "success":
                return run
        # The shared Pages workflow may replace this run with a newer Bubble commit.
        for run in candidates:
            if run["status"] != "completed" or run["conclusion"] != "success":
                continue
            if run["headSha"] == commit:
                continue
            git("fetch", "origin", "main")
            try:
                git("merge-base", "--is-ancestor", commit, run["headSha"])
            except RuntimeError:
                continue
            return run
        running = any(run["status"] != "completed" for run in exact)
        if exact and not running and not dispatched:
            command(["gh", "workflow", "run", "pages.yml", "--repo", REPOSITORY, "--ref", "main"])
            dispatched = True
        time.sleep(5)
    raise TimeoutError("Timed out waiting for the release's GitHub Pages deployment")


def fetch(url: str) -> bytes:
    last = None
    for attempt in range(7):
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"HTTP verification failed for {url}: {last}")


def verify_online(release_id: str, commit: str, *, all_payloads: bool = False) -> dict:
    directory = store.release_directory(release_id)
    manifest = store.read_json(directory / "manifest.json")
    index_path = directory / "public/data/index.json"
    expected = index_path.read_bytes()
    if fetch(ONLINE + "data/index.json?release=" + commit) != expected:
        raise ValueError("Live online index bytes do not match the intended release")
    index = json.loads(expected)
    selected = [item["id"] for item in index["items"]] if all_payloads else manifest["selectedItemIds"]
    def check(item_id):
        relative = f"data/items/{item_id}.json"
        if fetch(ONLINE + relative + "?release=" + commit) != (directory / "public" / relative).read_bytes():
            raise ValueError(f"Online payload bytes differ: {item_id}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(check, selected))
    return {"ok": True, "releaseId": release_id, "commit": commit, "onlineUrl": ONLINE,
            "indexSha256": manifest["indexSha256"], "verifiedPayloads": len(selected),
            "verifiedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def registered_dashboard() -> dict:
    payload = json.loads(command([sys.executable, "-B", "-X", "utf8", str(MANAGER),
                                  "resolve", "--id", "oppday-dashboard", "--json"]))
    if Path(payload["root"]).resolve() != ROOT.resolve():
        raise ValueError("The port registry does not identify this Dashboard root")
    return payload


def probe_local(registered: dict) -> dict:
    request = urllib.request.Request(registered["url"].rstrip("/") + "/api/index",
                                     headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=5) as response:
        if not response.getheader("Server", "").startswith("OppdayDashboard/"):
            raise ValueError("Registered Local port belongs to a different service")
        payload = json.loads(response.read())
    expected = store.current_pointer()["releaseId"]
    if payload.get("releaseId") != expected or not isinstance(payload.get("items"), list):
        raise ValueError("Local must serve the prior verified snapshot before publication")
    return {"releaseId": expected, "items": len(payload["items"])}


def ensure_local_running(registered: dict) -> dict:
    try:
        return {"status": "already_running", **probe_local(registered)}
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        command(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 registered["entry_point"]], timeout=90)
        return {"status": "started", **probe_local(registered)}


def verify_local(release_id: str, registered: dict) -> dict:
    from scripts.build_static_site import public_item
    directory = store.release_directory(release_id)
    expected = store.read_json(directory / "public/data/index.json")
    url = registered["url"].rstrip("/")
    local = json.loads(fetch(url + "/api/index?refresh=1"))
    if local.get("releaseId") != release_id:
        raise ValueError("Registered Local server is not running the snapshot-aware version")
    if {item["id"]: public_item(item) for item in local["items"]} != {item["id"]: item for item in expected["items"]}:
        raise ValueError("Local/public index projection differs")
    manifest = store.read_json(directory / "manifest.json")
    for item_id in manifest["selectedItemIds"]:
        payload = json.loads(fetch(url + "/api/item/" + item_id))
        expected_item = store.read_json(directory / "public/data/items" / f"{item_id}.json")["item"]
        if payload["item"].get("markdown", "") != expected_item.get("markdown", ""):
            raise ValueError("Local/public summary text differs")
    return {"ok": True, "releaseId": release_id, "url": registered["url"], "items": len(local["items"])}


def publish(release_id: str, *, full_verification: bool = False, rollback: bool = False) -> dict:
    verified = snapshots.verify_release(release_id, verify_blobs=True)
    registered = registered_dashboard()
    previous = store.current_pointer() if store.CURRENT.exists() else None
    online_proof = None
    with snapshots.release_lock():
        sync_remote(release_id)
        ensure_local_running(registered)
        manifest = store.read_json(store.release_directory(release_id) / "manifest.json")
        repository_index = store.read_json(ROOT / "docs/data/index.json")
        if repository_index.get("releaseId") != release_id:
            if manifest["previousReleaseId"] == "legacy-public-baseline":
                baseline = store.read_json(store.release_directory(release_id) / "public/data/index.json")
            else:
                prior_directory = store.release_directory(manifest["previousReleaseId"])
                baseline = store.read_json(prior_directory / "public/data/index.json")
            if repository_index["items"] != baseline["items"] or repository_index["stats"] != baseline["stats"]:
                raise ValueError("Remote OPPDAY data changed since this candidate was prepared; rebuild from the verified current release")
        publication_attempted = False
        try:
            emit("export", releaseId=release_id, items=verified["items"])
            publication_attempted = True
            commit = publish_files(release_id)
            emit("pages", commit=commit)
            pages = wait_pages(commit)
            emit("verify_online", releaseId=release_id, full=full_verification)
            online_proof = verify_online(release_id, pages["headSha"], all_payloads=full_verification)
            store.write_json_atomic(store.release_directory(release_id) / "online-verification.json", online_proof)
            snapshots.promote_release(release_id, online_proof)
            local = verify_local(release_id, registered)
        except Exception as failure:
            recovery = {"ok": False, "releaseId": release_id, "error": str(failure),
                        "localRestored": False, "onlineRestored": False}
            if previous:
                try:
                    store.write_json_atomic(store.CURRENT, previous)
                    recovery["localRestored"] = True
                except Exception as pointer_failure:
                    recovery["pointerRestoreError"] = str(pointer_failure)
                    recovery["degraded"] = True
            if previous and publication_attempted and not rollback:
                prior_id = previous["releaseId"]
                try:
                    emit("rollback", releaseId=prior_id)
                    recovery_commit = publish_files(prior_id)
                    recovery_pages = wait_pages(recovery_commit)
                    recovery_proof = verify_online(prior_id, recovery_pages["headSha"])
                    recovery["onlineRestored"] = True
                    recovery["verification"] = recovery_proof
                except Exception as recovery_failure:
                    recovery["rollbackError"] = str(recovery_failure)
                    recovery["degraded"] = True
            store.write_json_atomic(store.release_directory(release_id) / "rollback.json", recovery)
            if recovery.get("degraded"):
                raise RuntimeError("Release failed and online recovery is incomplete; see private rollback.json") from failure
            raise
        result = {"ok": True, "complete": True, "releaseId": release_id, "git": {"head": commit},
                  "pages": pages, "online": online_proof, "local": local,
                  "intelligence_status": {"status": "not_requested_by_project"}}
        store.write_json_atomic(store.release_directory(release_id) / "deployment.json", result)
        emit("complete", releaseId=release_id, items=verified["items"], commit=commit)
        return result


def main():
    parser = argparse.ArgumentParser(description="Publish one verified OPPDAY snapshot online, then activate Local")
    parser.add_argument("--release-id")
    parser.add_argument("--run-id")
    parser.add_argument("--registration-id", action="append", default=[])
    parser.add_argument("--full-verification", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.run_id:
        if not args.registration_id:
            parser.error("--run-id requires the exact --registration-id set")
        args.release_id = args.release_id or snapshots.release_id_for(args.run_id, args.registration_id)
        with snapshots.release_lock():
            snapshots.prepare_release(args.release_id, run_id=args.run_id, registrations=args.registration_id)
    if not args.release_id:
        parser.error("--release-id or --run-id is required")
    print(json.dumps(publish(args.release_id, full_verification=args.full_verification, rollback=args.rollback), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
