from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ("verify_ai_layout_no_overlap_v09.js", "verify_ai_chart_interaction.js")


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js not found; install Node and run npm ci --prefix work")
    for test in TESTS:
        print(f"Running browser smoke test: {test}", flush=True)
        subprocess.run([node, str(ROOT / "work" / test)], cwd=ROOT, check=True, timeout=180)
    print("Browser smoke tests passed", flush=True)


if __name__ == "__main__":
    main()
