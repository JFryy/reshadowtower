#!/usr/bin/env python3
"""Launch a package from an isolated per-release workspace, preserving shared saves."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Iterator
from typing import TextIO

# Isolated Python excludes the script directory; load only our packaged helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_common import file_hash


def data_directory() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "ReShadowTower"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "reshadowtower"


def verify_payload(payload: Path, hashes: dict[str, str]) -> None:
    for name, expected in hashes.items():
        path = payload / name
        if not path.resolve().is_relative_to(payload.resolve()) or not path.is_file():
            raise ValueError(f"Missing or invalid package file: {name}")
        if file_hash(path) != expected:
            raise ValueError(f"Package file failed integrity check: {name}")
    actual_names = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    if actual_names != set(hashes):
        raise ValueError("Package contains unlisted files. Extract into an empty directory.")


def prepare_workspace(payload: Path, data: Path, identity: str) -> Path:
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("Invalid package identity; re-extract the release.")
    releases = data / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    workspace = releases / identity
    if workspace.exists():
        if (workspace / ".package-id").read_text(encoding="utf-8").strip() != identity:
            raise ValueError(f"Unrecognized workspace: {workspace}; choose a clean data directory.")
        return workspace
    saves = data / "saves"
    saves.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=releases) as directory:
        staging = Path(directory) / "payload"
        shutil.copytree(payload, staging, symlinks=False)
        config = staging / "game.toml"
        text = config.read_text(encoding="utf-8")
        old = 'memcard_dir = "saves"'
        if text.count(old) != 1:
            raise ValueError("Package save-directory configuration changed; cannot safely install.")
        config.write_text(text.replace(old, "memcard_dir = " + json.dumps(saves.resolve().as_posix())), encoding="utf-8")
        (staging / ".package-id").write_text(identity + "\n", encoding="utf-8")
        staging.rename(workspace)
    return workspace


@contextmanager
def session_lock(data: Path) -> Iterator[None]:
    """Prevent concurrent setup or gameplay from sharing writable saves."""
    data.mkdir(parents=True, exist_ok=True)
    with (data / "session.lock").open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            # Windows can lock past EOF; reading first would fail if already locked.
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError("ReShadowTower is already running. Close it before starting another copy.") from error
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("ReShadowTower is already running. Close it before starting another copy.") from error
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def prepare_toolchain(source: Path, data: Path, identity: str, hashes: dict[str, str]) -> Path:
    """Cache bundled tools at a stable path without replacing existing versions."""
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("Invalid bundled toolchain identity.")
    parent = data / "toolchains"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / identity
    if destination.exists():
        if (destination / ".bundle-id").read_text(encoding="utf-8").strip() != identity:
            raise ValueError(f"Incomplete bundled tools at {destination}. Rename that directory and retry; saves are separate.")
        return destination
    verify_payload(source, hashes)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=parent) as directory:
        staging = Path(directory) / "tools"
        shutil.copytree(source, staging, symlinks=True)
        (staging / ".bundle-id").write_text(identity + "\n", encoding="utf-8")
        staging.rename(destination)
    return destination


def built_game_ready(workspace: Path) -> bool:
    executable = workspace / "build-release" / ("Shadow_Tower_Recompiled.exe" if os.name == "nt" else "Shadow_Tower_Recompiled")
    try:
        expected = (workspace / ".build-ready").read_text(encoding="utf-8").strip()
        return file_hash(executable) == expected
    except FileNotFoundError:
        return False


def prepare_launch(package: Path, data: Path) -> tuple[Path, dict[str, str]]:
    metadata = json.loads((package / "release.json").read_text(encoding="utf-8"))
    platform = "windows-x64" if os.name == "nt" else "linux-x64"
    if metadata["platform"] != platform:
        raise ValueError("This release is for a different operating system.")
    payload = package / "payload"
    verify_payload(payload, metadata["files"])
    pack = prepare_toolchain(package / "toolchain", data, metadata["toolchain_sha256"], metadata["toolchain_files"])
    identity = hashlib.sha256((package / "release.json").read_bytes()).hexdigest()
    workspace = prepare_workspace(payload, data, identity)
    env = os.environ.copy()
    # The child executable lives in user data, not in the AppImage. Inherited
    # APPIMAGE makes the runtime resolve BIOS/assets beside the outer archive.
    for key in ("APPIMAGE", "APPDIR", "ARGV0", "OWD", "CC", "CXX", "CMAKE_PREFIX_PATH", "SDL3_DIR", "ZLIB_ROOT", "PYTHONPATH", "PYTHONHOME",
                "CMAKE", "PYTHON", "PSXRECOMP_ROOT", "PSXRECOMP_PROJECT_ROOT", "PSXRECOMP_BUILD_DIR", "TOOLCHAIN_DIR", "BPE_TOOLCHAIN_DIR"):
        env.pop(key, None)
    python = pack / ("python/python.exe" if os.name == "nt" else "python/bin/python3")
    env.update({
        "SHADOWTOWER_PROJECT_ROOT": str(workspace),
        "SHADOWTOWER_FORCE_SETUP": "0" if built_game_ready(workspace) else "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SHADOWTOWER_BUILD_DIR": str(workspace / "build-release"),
        "SHADOWTOWER_BUNDLED_TOOLCHAIN": str(pack),
        "RETCOMM_TOOLCHAIN_DIR": str(pack),
        "PSXRECOMP_TOOLCHAIN_DIR": str(pack),
        "RETCOMM_TOOLCHAIN_SKIP_UPDATE": "1",
        "RETCOMM_PYTHON": str(python),
        "PATH": os.pathsep.join((str(pack / "bin"), str(python.parent), env.get("PATH", ""))),
    })
    if os.name != "nt":
        env["LD_LIBRARY_PATH"] = str(pack / "lib")
    suffix = ".exe" if os.name == "nt" else ""
    for tool in ("cmake", "ninja", "clang"):
        subprocess.run([str(pack / "bin" / (tool + suffix)), "--version"],
                       env=env, check=True, capture_output=True, timeout=30)
    return workspace, env


def run_launcher(package: Path, workspace: Path, env: dict[str, str],
                 log: TextIO) -> subprocess.CompletedProcess:
    """Hand off to the native UI while the bootstrap retains the save lock."""
    executable = package / ("shadowtower-launcher.exe" if os.name == "nt" else "shadowtower-launcher")
    return subprocess.run(
        [str(executable), "--python", env["RETCOMM_PYTHON"],
         "--backend", str(workspace / "tools/launcher_backend.py"),
         "--workspace", str(workspace)],
        cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def main() -> int:
    package = Path(__file__).resolve().parent
    data = data_directory()
    data.mkdir(parents=True, exist_ok=True)
    log_path = data / "launcher.log"
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        try:
            with session_lock(data):
                workspace, env = prepare_launch(package, data)
                completed = run_launcher(package, workspace, env, log)
                if completed.returncode:
                    raise RuntimeError(f"The game or setup exited with code {completed.returncode}.")
                return 0
        except Exception as error:
            traceback.print_exc(file=log)
            reason = ("Could not copy the bundled files. Check free disk space and write permissions, then retry."
                      if isinstance(error, shutil.Error) else str(error))
            message = f"ReShadowTower could not start: {reason}\n\nDetails: {log_path}\nExisting saves have not been removed."
            print(message, file=sys.stderr)
            if os.name != "nt":
                try:
                    subprocess.run([str(package / "shadowtower-launcher"), "--error", message],
                                   check=True, stdout=log, stderr=subprocess.STDOUT)
                except (OSError, subprocess.SubprocessError) as dialog_error:
                    log.write(f"Could not show native error dialog: {dialog_error}\n")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
