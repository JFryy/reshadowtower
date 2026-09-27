#!/usr/bin/env python3
"""Assemble a disc-free offline release from source inputs and a verified toolchain."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys

from bundled_toolchain import PINS, extract_verified, tool_paths

ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILES = (
    "CMakeLists.txt", "game.toml", "config.ini", "VERSION", "LICENSE",
    "codegen_setup.c", "codegen_setup.h", "cmake/graphics.cmake", "cmake/input.cmake",
    "src/modern_controls.c", "src/modern_controls.h", "src/world_texture_filter.glsl",
    "seeds/ghidra_funcs.txt", "tools/prepare_source.py", "tools/release_cli.py", "tools/generate_aot.py",
    "cmake/adapters.cmake", "patches/runtime-input.patch", "patches/runtime-graphics.patch",
    "patches/setup-host.patch", "patches/setup-ui.patch",
    "packaging/windows/CMakeLists.txt", "packaging/windows/launcher.c",
    "cmake/setup.cmake", "src/setup_music.cpp", "src/setup_music.h",
    "src/setup_music_ui.cpp", "src/setup_music_ui.h",
    "assets/setup/boxart.tga", "assets/setup/music.wav",
)


def validate_sources(manifest: Path, project: Path) -> None:
    if not manifest.is_file():
        raise ValueError(f"Missing {manifest}; configure a setup-host build first.")
    sources = [Path(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    resolved = [(source if source.is_absolute() else project / source).resolve() for source in sources]
    forbidden = (project.resolve() / "generated", project.resolve() / "psxrecomp/generated")
    for source in resolved:
        if "generated" in source.parts or any(source.is_relative_to(root) for root in forbidden):
            raise ValueError(f"Setup host links generated code: {source}. Refusing packaging.")
    required = manifest.resolve().parent / "setup/psxrecomp_codegen_host.c"
    original = project.resolve() / "psxrecomp/host/psxrecomp_codegen_host.c"
    if original in resolved:
        raise ValueError("Setup host links the unrestricted upstream toolchain installer.")
    if required not in resolved:
        raise ValueError("Setup host is missing the first-run codegen implementation.")


def tracked_files(repo: Path):
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


def source_files():
    yield from (ROOT / name for name in PROJECT_FILES)
    for module in ("psxrecomp", "recomp-ui"):
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
    files = list(source_files()) + [ROOT / "tools/launch_release.py", ROOT / "tools/build_bundled_sdl.py"]
    files += sorted((ROOT / "packaging").rglob("*"))
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if path.is_file():
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
            digest.update(file_hash(path).encode() + b"\0")
    return digest.hexdigest()


def validate_build(args: argparse.Namespace) -> None:
    import build_bundled_sdl
    stamp = json.loads((args.build / "release-build.json").read_text(encoding="utf-8"))
    if stamp["source_fingerprint"] != source_fingerprint():
        raise ValueError("Sources changed since the setup-host build. Run tools/build_release.py in a new output directory.")
    if stamp["platform"] != args.platform or stamp["toolchain_sha256"] != PINS[args.platform][1]:
        raise ValueError("Build platform or bundled toolchain does not match the package.")
    if args.platform == "linux-x64":
        sdl = stamp["sdl"]
        if sdl["archive_sha256"] != build_bundled_sdl.SHA256 or sdl["prefix"] != str((args.build.parent / "bundled-sdl").resolve()):
            raise ValueError("Bundled SDL provenance mismatch")
        if build_bundled_sdl.hashes(Path(sdl["prefix"])) != sdl["files"]:
            raise ValueError("Bundled SDL files differ from verified build")
    suffix = ".exe" if args.platform == "windows-x64" else ""
    binaries = {"Shadow_Tower_Recompiled" + suffix: args.build / ("Shadow_Tower_Recompiled" + suffix)}
    binaries.update({name + suffix: args.emitters / (name + suffix) for name in ("psxrecomp-game", "psxrecomp-bios")})
    if suffix:
        if args.windows_launcher is None:
            raise ValueError("Windows packaging requires --windows-launcher.")
        binaries["ReShadowTower.exe"] = args.windows_launcher
    for name, path in binaries.items():
        if file_hash(path) != stamp["binaries"][name]:
            raise ValueError(f"Binary differs from the verified build: {path}")


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def stage(args: argparse.Namespace) -> None:
    import tempfile

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
            from build_bundled_sdl import hashes
            if hashes(payload / "bundled-sdl") != sdl["files"]:
                raise ValueError("Staged SDL files differ from verified build")
        for name in ("Shadow_Tower_Recompiled" + suffix,):
            shutil.copy2(args.build / name, payload / name)
        shutil.copytree(args.build / "assets", payload / "assets", dirs_exist_ok=True)
        bundled = args.build / "mods/bundled"
        if bundled.is_symlink():
            raise ValueError("Bundled mod catalog must not be a symlink")
        if any(path.is_symlink() for path in bundled.rglob("*")):
            raise ValueError("Bundled mod catalog contains a symlink")
        shutil.copytree(bundled, payload / "mods/bundled")
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
        hashes = {path.relative_to(payload).as_posix(): file_hash(path)
                  for path in sorted(payload.rglob("*")) if path.is_file()}
        toolchain_hashes = {path.relative_to(pack).as_posix(): file_hash(path)
                           for path in sorted(pack.rglob("*")) if path.is_file()}
        metadata = {"platform": args.platform, "version": (ROOT / "VERSION").read_text().strip(),
                    "toolchain_sha256": PINS[args.platform][1], "toolchain_files": toolchain_hashes,
                    "files": hashes}
        (staging / "release.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(ROOT / "tools/launch_release.py", staging / "launch_release.py")
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
        validate_sources(args.build / "setup-sources.txt", ROOT)
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
