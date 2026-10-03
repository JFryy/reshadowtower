"""Resolve the pinned framework sources through the shared CMake dependency setup."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "runtime/runtime.cmake",
    "lib/recomp-net/CMakeLists.txt",
    "lib/retcomm-rbengine/CMakeLists.txt",
)


def dependency_pins() -> list[dict[str, str]]:
    return json.loads((ROOT / "cmake/dependencies.json").read_text(encoding="utf-8"))


def fetch_framework(project_root: Path) -> Path:
    build = project_root / "build-dependencies"
    env = os.environ.copy()
    env.pop("PSXRECOMP_ROOT", None)
    subprocess.run(
        ["cmake", "-S", str(project_root / "cmake/dependencies"), "-B", str(build),
         "-G", "Ninja", "-DPSXRECOMP_ROOT="],
        check=True, stdout=sys.stderr, env=env,
    )
    return Path((build / "psxrecomp-source-dir.txt").read_text(encoding="utf-8").strip())


def framework_inventory(project_root: Path = ROOT) -> set[Path]:
    pins = dependency_pins()
    archives = [project_root / "build-dependencies/dependency-archives" / pin["name"]
                / (pin["revision"] + ".tar.gz") for pin in pins]
    if any(not archive.is_file() for archive in archives):
        fetch_framework(project_root)
    files: set[Path] = set()
    for pin, archive in zip(pins, archives, strict=True):
        if not archive.is_file():
            raise ValueError(f"Missing dependency archive: {archive}. Reset build-dependencies and rerun tools/dependencies.py.")
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != pin["sha256"]:
                raise ValueError(f"Dependency archive checksum mismatch: {archive}. Reset build-dependencies and rerun tools/dependencies.py.")
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise ValueError(f"Unsafe dependency archive path: {member.name}")
                if member.isdir():
                    continue
                if not member.isfile() or len(path.parts) < 2:
                    raise ValueError(f"Unsupported dependency archive entry: {member.name}")
                files.add(Path(pin["path"]).joinpath(*path.parts[1:]))
    return files


def framework_root(project_root: Path = ROOT) -> Path:
    override = os.environ.get("PSXRECOMP_ROOT")
    bundled = project_root / "psxrecomp"
    if override:
        source = Path(override).expanduser().resolve()
    elif not (project_root / ".git").exists() and (bundled / REQUIRED_FILES[0]).is_file():
        source = bundled.resolve()
    else:
        source = fetch_framework(project_root)
    for name in REQUIRED_FILES:
        if not (source / name).is_file():
            raise ValueError(
                f"Framework sources are missing {name}: {source}. "
                "Supply a complete PSXRECOMP_ROOT or unset it to fetch the pinned dependencies."
            )
    return source


def main() -> int:
    try:
        print(framework_root())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Framework dependency setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
