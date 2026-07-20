from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_GENERATED_FILES = (
    "docs/.nojekyll",
    "docs/index.html",
    "docs/static/app.js",
    "docs/static/styles.css",
    "docs/data/index.json",
)
ITEMS_DIR = "docs/data/items"
ITEM_ID_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
GIT_ADD_MAX_COMMAND_CHARS = 16_000


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        capture_output=True,
    )


def normalise_git_path(path: str) -> str:
    value = path.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def direct_item_id(path: str) -> str:
    normalised = normalise_git_path(path)
    prefix = f"{ITEMS_DIR}/"
    if not normalised.startswith(prefix):
        return ""
    relative = normalised[len(prefix) :]
    if "/" in relative or not relative.lower().endswith(".json"):
        return ""
    item_id = relative[:-5]
    return item_id if ITEM_ID_RE.fullmatch(item_id) else ""


def command_paths(command: list[str]) -> set[str]:
    result = run(command)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git path query failed")
    return {normalise_git_path(line) for line in result.stdout.splitlines() if line.strip()}


def expected_item_paths() -> set[str]:
    index_path = ROOT / "docs" / "data" / "index.json"
    if not index_path.exists():
        return set()
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot validate generated item allowlist: {exc}") from exc

    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Cannot validate generated item allowlist: index items is not a list")
    expected = set()
    for item in items:
        item_id = str(item.get("id", "") if isinstance(item, dict) else "")
        if not ITEM_ID_RE.fullmatch(item_id):
            raise RuntimeError(f"Cannot validate generated item id: {item_id!r}")
        expected.add(f"{ITEMS_DIR}/{item_id}.json")
    return expected


def tracked_item_paths() -> set[str]:
    tracked = command_paths(["git", "ls-files", "--", ITEMS_DIR])
    staged_deletions = command_paths(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=D", "--", ITEMS_DIR]
    )
    return {
        path
        for path in tracked | staged_deletions
        if direct_item_id(path)
    }


def generated_item_allowlist() -> set[str]:
    return expected_item_paths() | tracked_item_paths()


def is_generated_path(path: str, item_allowlist: set[str] | None = None) -> bool:
    normalised = normalise_git_path(path)
    if normalised in FIXED_GENERATED_FILES:
        return True
    return normalised in (item_allowlist or set())


def git_add_chunks(
    paths: list[str],
    max_command_chars: int = GIT_ADD_MAX_COMMAND_CHARS,
) -> list[list[str]]:
    prefix = ["git", "add", "--"]
    ordered = sorted({normalise_git_path(path) for path in paths})
    chunks: list[list[str]] = []
    current: list[str] = []

    for path in ordered:
        candidate = [*current, path]
        if len(subprocess.list2cmdline([*prefix, *candidate])) <= max_command_chars:
            current = candidate
            continue
        if not current:
            raise ValueError(f"One generated path exceeds git add command budget: {path}")
        chunks.append(current)
        current = [path]
        if len(subprocess.list2cmdline([*prefix, *current])) > max_command_chars:
            raise ValueError(f"One generated path exceeds git add command budget: {path}")

    if current:
        chunks.append(current)
    return chunks


def dirty_paths() -> set[str]:
    return (
        command_paths(["git", "diff", "--name-only"])
        | command_paths(["git", "diff", "--cached", "--name-only"])
        | command_paths(["git", "ls-files", "--others", "--exclude-standard"])
    )


def unrelated_dirty_paths(paths: set[str], item_allowlist: set[str]) -> set[str]:
    return {
        normalise_git_path(path)
        for path in paths
        if not is_generated_path(path, item_allowlist)
    }


def ensure_publishable_tree() -> tuple[bool, str]:
    branch = run(["git", "branch", "--show-current"])
    if branch.returncode or branch.stdout.strip() != "main":
        return False, "Static publish is allowed only from branch main."
    conflicts = command_paths(["git", "diff", "--name-only", "--diff-filter=U"])
    if conflicts:
        return False, "Unmerged files block publish: " + ", ".join(sorted(conflicts))
    item_allowlist = generated_item_allowlist()
    unrelated = sorted(unrelated_dirty_paths(dirty_paths(), item_allowlist))
    if unrelated:
        return False, "Unrelated dirty files block publish: " + ", ".join(unrelated)
    return True, ""


def print_result(result: subprocess.CompletedProcess) -> None:
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def main() -> int:
    try:
        clean, message = ensure_publishable_tree()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not clean:
        print(message, file=sys.stderr)
        return 2

    build = run([sys.executable, "scripts/build_static_site.py", "--json"])
    print_result(build)
    if build.returncode:
        return build.returncode

    try:
        clean, message = ensure_publishable_tree()
        item_allowlist = generated_item_allowlist()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not clean:
        print(message, file=sys.stderr)
        return 2

    generated_changes = sorted(
        path
        for path in dirty_paths()
        if is_generated_path(path, item_allowlist)
    )
    if not generated_changes:
        print("No OPPDAY dashboard changes to publish.")
        return 0

    # Stage exact changed files only. Never pass docs/data/items as a directory
    # pathspec because that could include an unrelated secret or nested file.
    # Chunking also keeps CreateProcess command lines safely below Windows'
    # 32,767-character limit.
    try:
        add_chunks = git_add_chunks(generated_changes)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for chunk_number, chunk in enumerate(add_chunks, start=1):
        add = run(["git", "add", "--", *chunk])
        print_result(add)
        if add.returncode:
            print(
                f"git add chunk {chunk_number}/{len(add_chunks)} failed; publish aborted.",
                file=sys.stderr,
            )
            return add.returncode

    try:
        staged = command_paths(["git", "diff", "--cached", "--name-only"])
        staged_item_allowlist = generated_item_allowlist()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    expected_staged = {normalise_git_path(path) for path in generated_changes}
    if staged != expected_staged:
        missing = sorted(expected_staged - staged)
        unexpected = sorted(staged - expected_staged)
        print(
            "Staged set does not match generated changes exactly; "
            f"missing={missing}, unexpected={unexpected}",
            file=sys.stderr,
        )
        return 2
    unrelated_staged = sorted(unrelated_dirty_paths(staged, staged_item_allowlist))
    if unrelated_staged:
        print("Refusing to commit unrelated staged files: " + ", ".join(unrelated_staged), file=sys.stderr)
        return 2

    for command in (
        ["git", "commit", "-m", "Update OPPDAY dashboard data"],
        ["git", "push", "origin", "main"],
    ):
        result = run(command)
        print_result(result)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
