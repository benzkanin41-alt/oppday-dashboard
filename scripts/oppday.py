from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / ".oppday-work/project-profile.json"
SCRIPT = Path(r"C:\Users\USER\.codex\skills\multiagent-oppday\scripts\run_multiagent_oppday.py")


def main() -> None:
    arguments = sys.argv[1:]
    if any(value == "--project-profile" or value.startswith("--project-profile=") for value in arguments):
        raise SystemExit("This project entrypoint always uses its own project profile")
    if not PROFILE.is_file() or not SCRIPT.is_file():
        raise SystemExit("The project profile or installed Multiagent Oppday Skill is unavailable")
    if arguments and arguments[0] not in ("--help", "-h"):
        arguments = [arguments[0], "--project-profile", str(PROFILE), *arguments[1:]]
    sys.path.insert(0, str(SCRIPT.parent))
    sys.argv = [str(SCRIPT), *arguments]
    runpy.run_path(str(SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
