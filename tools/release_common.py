"""Shared integrity helpers and offline build settings for release tools."""
from __future__ import annotations

import hashlib
from pathlib import Path


OFFLINE_CMAKE_OPTIONS = (
    # Allow extraction of vendored archives, but never fall back to network URLs.
    "-DFETCHCONTENT_FULLY_DISCONNECTED=OFF",
    "-DPSX_DEPS_OFFLINE=ON",
    "-DPSX_ENABLE_VULKAN=OFF",
    "-DPSX_DEBUG_TOOLS=OFF",
    "-DPSX_SDL3_FETCH=OFF",
    "-DPSX_ZLIB_FETCH=OFF",
)


def file_hash(path: Path) -> str:
    """Compute a file's SHA-256 without loading it into memory."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    """Map relative file paths to hashes for a release manifest."""
    return {path.relative_to(root).as_posix(): file_hash(path)
            for path in sorted(root.rglob("*")) if path.is_file()}
