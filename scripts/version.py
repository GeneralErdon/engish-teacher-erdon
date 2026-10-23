"""The release version: one number for the whole repository, the same in every package.

`just bump X.Y.Z` sets it in the release pull request; release.yml checks it there and tags the
merge into master as vX.Y.Z. Standard library only, so CI runs it with the runner's python3.

    python3 scripts/version.py check         prints the version; fails if the packages disagree
    python3 scripts/version.py bump 0.2.0    sets it in every package (`just bump` also relocks)
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Tauri takes the app's version from here (tauri.conf.json points at it): installers and APK.
APP = ROOT / "apps/desktop/package.json"
# The rest follow it, so the desktop crate and the server images tell the same story.
PACKAGES = (
    ROOT / "apps/desktop/src-tauri/Cargo.toml",
    ROOT / "packages/contracts/pyproject.toml",
    ROOT / "services/api/pyproject.toml",
    ROOT / "services/pron/pyproject.toml",
)
SEMVER = re.compile(r"\d+\.\d+\.\d+")
# A manifest's first version line is the package's own ([package], [project], top-level key).
TOML_VERSION = re.compile(r'^version = "[^"]*"', re.MULTILINE)
JSON_VERSION = re.compile(r'^  "version": "[^"]*"', re.MULTILINE)


def name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return str(json.loads(text)["version"])
    manifest = tomllib.loads(text)
    return str((manifest.get("package") or manifest["project"])["version"])


def check() -> str:
    version = read(APP)
    if not SEMVER.fullmatch(version):
        sys.exit(f"{name(APP)}: {version!r} is not X.Y.Z")
    if behind := [f"{name(path)} ({read(path)})" for path in PACKAGES if read(path) != version]:
        sys.exit(f"not at {version}: {', '.join(behind)}. Run `just bump {version}`")
    return version


def bump(version: str) -> None:
    if not SEMVER.fullmatch(version):
        sys.exit(f"{version!r} is not X.Y.Z")
    for path in (APP, *PACKAGES):
        if path.suffix == ".json":
            pattern, line = JSON_VERSION, f'  "version": "{version}"'
        else:
            pattern, line = TOML_VERSION, f'version = "{version}"'
        text, found = pattern.subn(line, path.read_text(encoding="utf-8"), count=1)
        if not found:
            sys.exit(f"{name(path)}: no version line to replace")
        path.write_text(text, encoding="utf-8", newline="\n")


def main(args: list[str]) -> None:
    match args:
        case ["check"]:
            print(check())
        case ["bump", version]:
            bump(version)
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
