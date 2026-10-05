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
import dependencies
from bundled_toolchain import PINS, extract_verified, tool_paths
from release_common import file_hash, file_hashes

ROOT = Path(__file__).resolve().parents[1]
IMGUI_FILES = (
    "LICENSE.txt", "imconfig.h", "imgui.cpp", "imgui.h", "imgui_draw.cpp",
    "imgui_internal.h", "imgui_tables.cpp", "imgui_widgets.cpp",
    "imstb_rectpack.h", "imstb_textedit.h", "imstb_truetype.h",
    "backends/imgui_impl_sdl3.cpp", "backends/imgui_impl_sdl3.h",
    "backends/imgui_impl_opengl3.cpp", "backends/imgui_impl_opengl3.h",
    "backends/imgui_impl_opengl3_loader.h",
)
PROJECT_FILES = (
    "CMakeLists.txt", "game.toml", "config.ini", "VERSION", "LICENSE",
    "cmake/graphics.cmake", "cmake/input.cmake", "cmake/dependencies.cmake",
    "cmake/generate_codegen_hash.cmake",
    "cmake/dependencies.json", "cmake/dependencies/CMakeLists.txt", "tools/dependencies.py",
    "src/modern_controls.c", "src/modern_controls.h", "src/world_texture_filter.glsl",
    "src/post_processing.h", "src/post_processing_gl.h", "src/post_processing.glsl",
    "src/render_scale.h", "src/render_scale_gl.h",
    "seeds/ghidra_funcs.txt", "tools/prepare_source.py", "tools/release_cli.py", "tools/generate_aot.py",
    "tools/release_common.py", "tools/launcher_backend.py",
    "cmake/adapters.cmake", "patches/runtime-input.patch", "patches/runtime-graphics.patch",
    "patches/runtime-widescreen.patch", "patches/runtime-settings.patch", "patches/runtime-software.patch",
    "packaging/windows/CMakeLists.txt", "packaging/windows/launcher.c",
    "assets/setup/boxart.tga", "assets/setup/music.wav",
)


EXCLUDED_DIRS = frozenset((".git", ".github", "disc", "saves", "CMakeFiles", "build", "__pycache__", ".cache"))
EXCLUDED_SUFFIXES = frozenset((".bin", ".cue", ".iso", ".chd", ".mcd", ".mcr", ".exe", ".img", ".dmp"))


def framework_sources(framework: Path) -> Iterator[Path]:
    """Export only files listed in the verified dependency archives."""
    framework = framework.resolve()
    for relative in sorted(dependencies.framework_inventory()):
        if relative.parts[0] == "generated" or any(
            part in EXCLUDED_DIRS or part.startswith(("build-", "cmake-build-"))
            for part in relative.parts[:-1]
        ):
            continue
        if relative.name in (".git", ".gitmodules", "CMakeCache.txt", "compile_commands.json"):
            continue
        if relative.suffix.lower() in EXCLUDED_SUFFIXES and relative.as_posix() != "bios/openbios.bin":
            continue
        path = framework / relative
        if any((framework / parent).is_symlink() for parent in (relative, *relative.parents)):
            raise ValueError(f"Source symlink requires explicit packaging review: {path}")
        if not path.is_file():
            raise ValueError(f"Framework source is missing: {path}. Use complete sources matching cmake/dependencies.json.")
        yield path


def source_files(framework: Path | None = None) -> Iterator[tuple[Path, Path]]:
    if framework is None:
        framework = dependencies.framework_root()
    for name in PROJECT_FILES:
        yield ROOT / name, Path(name)
    for name in ("CMakeLists.txt", "main.cpp", "model.hpp", "model_tests.cpp",
                 "artwork.hpp", "bindings.hpp", "bindings_tests.cpp"):
        relative = Path("launcher") / name
        yield ROOT / relative, relative
    for source in framework_sources(framework):
        yield source, Path("psxrecomp") / source.relative_to(framework.resolve())


def copy_sources(destination: Path, framework: Path | None = None) -> None:
    for source, relative in source_files(framework):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def source_fingerprint(framework: Path | None = None) -> str:
    files = list(source_files(framework))
    files += [(ROOT / name, Path(name)) for name in
              ("tools/launch_release.py", "tools/build_bundled_sdl.py")]
    files += [(path, path.relative_to(ROOT)) for path in (ROOT / "packaging").rglob("*")]
    digest = hashlib.sha256()
    for path, relative in sorted(files, key=lambda item: item[1].as_posix()):
        if path.is_file():
            digest.update(relative.as_posix().encode() + b"\0")
            digest.update(file_hash(path).encode() + b"\0")
    return digest.hexdigest()


def imgui_source(build: Path) -> Path:
    return Path((build / "imgui-source-dir.txt").read_text(encoding="utf-8").strip())


def imgui_hashes(source: Path) -> dict[str, str]:
    return {name: file_hash(source / name) for name in IMGUI_FILES}


def validate_build(args: argparse.Namespace) -> None:
    stamp = json.loads((args.build / "release-build.json").read_text(encoding="utf-8"))
    if stamp["source_fingerprint"] != source_fingerprint():
        raise ValueError("Sources changed since the release build. Run tools/build_release.py in a new output directory.")
    if stamp.get("dependency_pins") != dependencies.dependency_pins():
        raise ValueError("Dependency pins differ from the verified build")
    if stamp["platform"] != args.platform or stamp["toolchain_sha256"] != PINS[args.platform][1]:
        raise ValueError("Build platform or bundled toolchain does not match the package.")
    if args.platform == "linux-x64":
        sdl = stamp["sdl"]
        if sdl["archive_sha256"] != build_bundled_sdl.SHA256 or sdl["prefix"] != str((args.build.parent / "bundled-sdl").resolve()):
            raise ValueError("Bundled SDL provenance mismatch")
        if build_bundled_sdl.hashes(Path(sdl["prefix"])) != sdl["files"]:
            raise ValueError("Bundled SDL files differ from verified build")
    if imgui_hashes(imgui_source(args.build)) != stamp["imgui"]:
        raise ValueError("ImGui sources differ from verified build; rebuild before packaging")
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
        imgui = imgui_source(args.build)
        bundled_imgui = payload / "launcher/bundled-imgui"
        for name in IMGUI_FILES:
            destination = bundled_imgui / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(imgui / name, destination)
        stamp = json.loads((args.build / "release-build.json").read_text(encoding="utf-8"))
        if imgui_hashes(bundled_imgui) != stamp["imgui"]:
            raise ValueError("Staged ImGui sources differ from verified build")
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
            shutil.copy2(payload / "psxrecomp/assets/psxrecomp.png", staging / "reshadowtower.png")
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
