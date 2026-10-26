"""Fail CI when a repository file is missing from FILE_GUIDE.md."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    "artifacts",
    "test-results",
    "playwright-report",
    "coverage",
}


def files():
    import os

    found = []
    for directory, subdirs, names in os.walk(ROOT):
        subdirs[:] = sorted(
            d for d in subdirs if d not in EXCLUDED and not d.endswith(".egg-info")
        )
        for name in sorted(names):
            if (
                name.startswith(".env")
                and name != ".env.example"
                or name.endswith((".pyc", ".tsbuildinfo"))
            ):
                continue
            if name == ".coverage":
                continue
            found.append((Path(directory) / name).relative_to(ROOT).as_posix())
    return sorted(found)


def check():
    guide = (ROOT / "FILE_GUIDE.md").read_text(encoding="utf-8")
    inventory = guide.split("## Individual file inventory", 1)[1]
    documented = set(re.findall(r"^\| `([^`]+)` \|", inventory, flags=re.MULTILINE))
    existing = set(files())
    missing, stale = existing - documented, documented - existing
    if missing or stale:
        for name in sorted(missing):
            print("Missing file documentation:", name)
        for name in sorted(stale):
            print("Stale file documentation:", name)
        raise SystemExit(1)
    print(f"All {len(existing)} repository files have individual guide entries.")


if __name__ == "__main__":
    check()
