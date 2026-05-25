from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, text=True, check=False, capture_output=True)


def main() -> int:
    build = run([sys.executable, "scripts/build_static_site.py", "--json"])
    print(build.stdout.strip())
    if build.returncode:
        print(build.stderr, file=sys.stderr)
        return build.returncode

    status = run(["git", "status", "--porcelain"])
    if status.returncode:
        print(status.stderr, file=sys.stderr)
        return status.returncode
    if not status.stdout.strip():
        print("No OPPDAY dashboard changes to publish.")
        return 0

    for command in (
        ["git", "add", "docs", "web", "server.py", "scripts", "README.md", ".github", ".gitignore"],
        ["git", "commit", "-m", "Update OPPDAY dashboard data"],
        ["git", "push"],
    ):
        result = run(command)
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
