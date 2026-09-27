#!/usr/bin/env python3
"""Verify and unpack a pinned, locally supplied toolchain archive."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from release_common import file_hash

PINS = {
    "linux-x64": (
        "https://github.com/RetroPortingToolKit/RetroPorting-Toolchains/releases/download/v1.0.14/cmake-clang-v1-linux-x64.zip",
        "597c8d343a3cf02ba6f6b2ae7cf6fe2fef125dde8feff62a144e8dd3da3d484e",
    ),
    "windows-x64": (
        "https://github.com/RetroPortingToolKit/RetroPorting-Toolchains/releases/download/v1.0.14/cmake-clang-v1-windows-x64.zip",
        "28da9742385e7ff875b3d9311e8ed89dbdc84f27b6ecba2bc0d0acc11f6d2b4d",
    ),
}


def _parts(name: str) -> tuple[str, ...]:
    if not name or name.startswith("/") or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"Unsafe archive path: {name!r}")
    parts = tuple(part for part in name.split("/") if part != "")
    if not parts or any(part in (".", "..") or "\x00" in part or ":" in part for part in parts):
        raise ValueError(f"Unsafe archive path: {name!r}")
    return parts


def _validate(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, tuple[str, ...], str]]:
    entries = []
    seen: dict[tuple[str, ...], str] = {}
    for info in archive.infolist():
        parts = _parts(info.filename)
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
            raise ValueError(f"Unsupported archive entry: {info.filename}")
        type_ = "link" if kind == stat.S_IFLNK else "dir" if info.is_dir() or kind == stat.S_IFDIR else "file"
        if (info.is_dir() or kind == stat.S_IFDIR) and type_ != "dir":
            raise ValueError(f"Invalid directory: {info.filename}")
        if parts in seen:
            raise ValueError(f"Duplicate archive entry: {info.filename}")
        seen[parts] = type_
        entries.append((info, parts, type_))
    for info, parts, type_ in entries:
        if any(seen.get(parts[:i]) in ("file", "link") for i in range(1, len(parts))):
            raise ValueError(f"Entry inside file or link: {info.filename}")
        if type_ == "link":
            target = archive.read(info).decode("utf-8")
            if not target or target.startswith("/") or "\\" in target or re.match(r"^[A-Za-z]:", target) or "\x00" in target:
                raise ValueError(f"Unsafe symlink: {info.filename}")
            depth = len(parts) - 1
            for component in target.split("/"):
                if component == "..":
                    depth -= 1
                elif component not in ("", "."):
                    if ":" in component:
                        raise ValueError(f"Unsafe symlink: {info.filename}")
                    depth += 1
                if depth < 0:
                    raise ValueError(f"Escaping symlink: {info.filename}")
    return entries


def extract_verified(archive_path: Path, destination: Path, expected_sha256: str) -> None:
    """Verify the entire zip before creating a staging directory or destination."""
    archive_path = Path(archive_path)
    destination = Path(destination)
    if file_hash(archive_path) != expected_sha256.lower():
        raise ValueError("Toolchain archive SHA256 mismatch")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    with zipfile.ZipFile(archive_path) as archive:
        entries = _validate(archive)
        # Stage beside the destination so the final move is on the same filesystem.
        with tempfile.TemporaryDirectory(prefix=".toolchain-", dir=destination.parent) as staging:
            root = Path(staging) / "contents"
            root.mkdir()
            directories = []
            for info, parts, type_ in entries:
                output = root.joinpath(*parts)
                if type_ == "dir":
                    output.mkdir(parents=True, exist_ok=True)
                    directories.append((output, info.external_attr >> 16))
                elif type_ == "link":
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.symlink_to(archive.read(info).decode("utf-8"))
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, output.open("xb") as sink:
                        shutil.copyfileobj(source, sink)
                    if os.name != "nt":
                        output.chmod((info.external_attr >> 16) & 0o777)
            for info, parts, type_ in entries:
                if type_ == "link":
                    resolved = root.joinpath(*parts).resolve()
                    if not resolved.is_relative_to(root.resolve()):
                        raise ValueError(f"Escaping symlink chain: {info.filename}")
            if os.name != "nt":
                for output, mode in reversed(directories):
                    output.chmod(mode & 0o777)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(destination)
            root.rename(destination)


def tool_paths(pack: Path, platform: str) -> tuple[Path, Path, Path, Path, Path]:
    """Require metadata at the archive root and all bundled executables."""
    if (not (pack / "retcomm-toolchain.json").is_file()
            or list(pack.rglob("retcomm-toolchain.json")) != [pack / "retcomm-toolchain.json"]):
        raise ValueError("Expected exactly one toolchain metadata file, directly in output/toolchain")
    suffix = ".exe" if platform == "windows-x64" else ""
    python = pack / ("python/python.exe" if suffix else "python/bin/python3")
    tools = tuple(pack / "bin" / (name + suffix)
                  for name in ("cmake", "ninja", "clang", "clang++"))
    for path in (python, *tools):
        if not path.is_file():
            raise ValueError(f"Incomplete bundled toolchain: {path}")
    return python, *tools
