#!/usr/bin/env python3
"""Assemble a disc-free offline release from source inputs and a verified toolchain."""
from __future__ import annotations

import argparse
from collections.abc import Iterator
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import build_bundled_sdl
from bundled_toolchain import PINS, extract_verified, tool_paths
from release_common import file_hash, file_hashes

ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILES = (
    "CMakeLists.txt", "game.toml", "config.ini", "VERSION", "LICENSE",
    "cmake/graphics.cmake", "cmake/input.cmake",
    "src/modern_controls.c", "src/modern_controls.h", "src/world_texture_filter.glsl",
    "seeds/ghidra_funcs.txt", "tools/prepare_source.py", "tools/release_cli.py", "tools/generate_aot.py",
    "tools/release_common.py", "tools/launcher_backend.py",
    "cmake/adapters.cmake", "patches/runtime-input.patch", "patches/runtime-graphics.patch",
    "patches/runtime-widescreen.patch",
    "packaging/windows/CMakeLists.txt", "packaging/windows/launcher.c",
    "assets/setup/music.wav",
)


def tracked_files(repo: Path) -> Iterator[Path]:
    listing = subprocess.check_output(["git", "-C", str(repo), "ls-files", "--stage", "-z"])
    for entry in listing.decode().split("\0"):
        if not entry:
            continue
        attributes, name = entry.split("\t", 1)
        mode = attributes.split()[0]
        path = repo / name
        if mode == "160000":
            yield from tracked_files(path)
        elif mode != "120000":
            yield path
        else:
            raise ValueError(f"Source symlink requires explicit packaging review: {path}")


def source_files() -> Iterator[Path]:
    yield from (ROOT / name for name in PROJECT_FILES)
    for name in ("CMakeLists.txt", "main.cpp", "model.hpp", "model_tests.cpp"):
        yield ROOT / "launcher" / name
    yield from (path for path in sorted((ROOT / "launcher/vendor/imgui").rglob("*"))
                if path.is_file() and (path.suffix in (".cpp", ".h") or path.name == "LICENSE.txt"))
    for module in ("psxrecomp",):
        for source in tracked_files(ROOT / module):
            relative = source.relative_to(ROOT)
            # Never collect ignored local output, test dumps, or generated game code.
            if relative.parts[:2] == ("psxrecomp", "generated"):
                continue
            if any(part in ("disc", "saves", ".github") for part in relative.parts):
                continue
            if source.suffix.lower() in (".bin", ".cue", ".iso", ".chd", ".mcd", ".mcr", ".exe"):
                if relative.as_posix() != "psxrecomp/bios/openbios.bin":
                    continue
            yield source


def copy_sources(destination: Path) -> None:
    for source in source_files():
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def source_fingerprint() -> str:
    files = list(source_files()) + [ROOT / "tools/launch_release.py",
                                    ROOT / "tools/build_bundled_sdl.py"]
    files += sorted((ROOT / "packaging").rglob("*"))
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if path.is_file():
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
            digest.update(file_hash(path).encode() + b"\0")
    return digest.hexdigest()


def validate_build(args: argparse.Namespace) -> None:
    stamp = json.loads((args.build / "release-build.json").read_text(encoding="utf-8"))
    if stamp["source_fingerprint"] != source_fingerprint():
        raise ValueError("Sources changed since the release build. Run tools/build_release.py in a new output directory.")
    if stamp["platform"] != args.platform or stamp["toolchain_sha256"] != PINS[args.platform][1]:
        raise ValueError("Build platform or bundled toolchain does not match the package.")
    if args.platform == "linux-x64":
        sdl = stamp["sdl"]
        if sdl["archive_sha256"] != build_bundled_sdl.SHA256 or sdl["prefix"] != str((args.build.parent / "bundled-sdl").resolve()):
            raise ValueError("Bundled SDL provenance mismatch")
        if build_bundled_sdl.hashes(Path(sdl["prefix"])) != sdl["files"]:
            raise ValueError("Bundled SDL files differ from verified build")
    suffix = ".exe" if args.platform == "windows-x64" else ""
    binaries = {name + suffix: args.emitters / (name + suffix) for name in ("psxrecomp-game", "psxrecomp-bios")}
    binaries["shadowtower-launcher" + suffix] = args.build / ("shadowtower-launcher" + suffix)
    if suffix:
        if args.windows_launcher is None:
            raise ValueError("Windows packaging requires --windows-launcher.")
        binaries["ReShadowTower.exe"] = args.windows_launcher
    for name, path in binaries.items():
        if file_hash(path) != stamp["binaries"][name]:
            raise ValueError(f"Binary differs from the verified build: {path}")


def stage(args: argparse.Namespace) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=args.output.parent) as directory:
        staging = Path(directory) / "ReShadowTower"
        staging.mkdir()
        extract_verified(args.toolchain_archive, staging / "toolchain", PINS[args.platform][1])
        python, *_ = tool_paths(staging / "toolchain", args.platform)
        pack = staging / "toolchain"
        suffix = ".exe" if args.platform == "windows-x64" else ""
        payload = staging / "payload"
        payload.mkdir()
        copy_sources(payload)
        if args.platform == "linux-x64":
            sdl = json.loads((args.build / "release-build.json").read_text())["sdl"]
            shutil.copytree(sdl["prefix"], payload / "bundled-sdl")
            if build_bundled_sdl.hashes(payload / "bundled-sdl") != sdl["files"]:
                raise ValueError("Staged SDL files differ from verified build")
        for name in ("psxrecomp-game", "psxrecomp-bios"):
            destination = payload / "psxrecomp/recompiler/build" / (name + suffix)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.emitters / (name + suffix), destination)
        # This is compiler identity metadata, not game code. A fresh package has
        # not configured CMake yet, but AOT's stale-emitter guard needs this value.
        codegen_hash = subprocess.check_output(
            [str(args.emitters.resolve() / ("psxrecomp-game" + suffix)), "--codegen-hash"], text=True,
        ).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{8}", codegen_hash):
            raise ValueError("The verified emitter returned an invalid codegen hash.")
        (payload / "psxrecomp/runtime/include/overlay_codegen_hash.h").write_text(
            f"#pragma once\n#define PSX_OVERLAY_CODEGEN_HASH 0x{codegen_hash}u\n", encoding="utf-8")
        metadata = {"platform": args.platform, "version": (ROOT / "VERSION").read_text().strip(),
                    "toolchain_sha256": PINS[args.platform][1], "toolchain_files": file_hashes(pack),
                    "files": file_hashes(payload)}
        (staging / "release.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        for name in ("launch_release.py", "release_common.py"):
            shutil.copy2(ROOT / "tools" / name, staging / name)
        shutil.copy2(args.build / ("shadowtower-launcher" + suffix), staging / ("shadowtower-launcher" + suffix))
        py_relative = python.relative_to(staging).as_posix()
        if suffix:
            if args.windows_launcher is None:
                raise ValueError("Windows packages require --windows-launcher pointing to the native ReShadowTower.exe.")
            shutil.copy2(args.windows_launcher, staging / "ReShadowTower.exe")
        else:
            launcher = staging / "AppRun"
            launcher.write_text('#!/bin/sh\nset -eu\ncd -- "$(dirname -- "$0")"\nexport LD_LIBRARY_PATH="$PWD/toolchain/lib"\nexec "./' + py_relative + '" -I -B ./launch_release.py\n', encoding="utf-8")
            launcher.chmod(0o755)
            shutil.copy2(ROOT / "packaging/linux/reshadowtower.desktop", staging / "reshadowtower.desktop")
            shutil.copy2(ROOT / "psxrecomp/assets/psxrecomp.png", staging / "reshadowtower.png")
        staging.rename(args.output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--emitters", type=Path, default=ROOT / "build-recompiler")
    parser.add_argument("--windows-launcher", type=Path)
    parser.add_argument("--platform", choices=("linux-x64", "windows-x64"), required=True)
    parser.add_argument("--toolchain-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_build(args)
        if args.output.exists() or args.output.is_symlink():
            raise ValueError(f"Refusing to replace existing package: {args.output}")
        stage(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Packaging failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
