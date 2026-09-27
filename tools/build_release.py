#!/usr/bin/env python3
"""Build a clean native release using a locally supplied pinned toolchain."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import bundled_toolchain
import build_bundled_sdl
import package_release


def native_platform() -> str:
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise ValueError(f"Unsupported native architecture: {machine}")
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform.startswith("linux"):
        return "linux-x64"
    raise ValueError(f"Unsupported native operating system: {sys.platform}")


def run(command: list[str], env: dict[str, str]) -> None:
    print("Running:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, env=env, check=True)


def build(archive: Path, output: Path, sdl_archive: Path | None = None) -> None:
    target = native_platform()
    if target == "linux-x64" and sdl_archive is None:
        raise ValueError("Linux builds require --sdl-archive")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to replace existing output: {output}")
    fingerprint = package_release.source_fingerprint()
    output.mkdir(parents=True)
    pack = output / "toolchain"
    bundled_toolchain.extract_verified(archive, pack, bundled_toolchain.PINS[target][1])
    python, cmake, ninja, cc, cxx = bundled_toolchain.tool_paths(pack, target)
    suffix = ".exe" if target == "windows-x64" else ""
    env = os.environ.copy()
    for key in ("CC", "CXX", "CMAKE_PREFIX_PATH", "SDL3_DIR", "ZLIB_ROOT",
                "LLVM_MINGW_ROOT", "PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env.update(RETCOMM_TOOLCHAIN_DIR=str(pack), PSXRECOMP_TOOLCHAIN_DIR=str(pack),
               PATH=os.pathsep.join((str(pack / "bin"), str(python.parent), env.get("PATH", ""))),
               CC=str(cc), CXX=str(cxx))
    if target == "linux-x64":
        env["LD_LIBRARY_PATH"] = str(pack / "lib")

    if target == "linux-x64":
        sdl = build_bundled_sdl.build(sdl_archive, output, pack, env)

    source = output / "source"
    package_release.copy_sources(source)
    common = [f"-DCMAKE_MAKE_PROGRAM={ninja}", f"-DCMAKE_C_COMPILER={cc}",
              f"-DCMAKE_CXX_COMPILER={cxx}", f"-DPython3_EXECUTABLE={python}",
              "-DCMAKE_BUILD_TYPE=Release"]
    if target == "linux-x64":
        common += [f"-DCMAKE_SYSROOT={pack / 'sysroot'}",
                   "-DOpenGL_GL_PREFERENCE=LEGACY",
                   "-DCMAKE_DISABLE_FIND_PACKAGE_Freetype=TRUE",
                   "-DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=TRUE"]

    def configure(src: Path, destination: Path, options: list[str]) -> None:
        run([str(cmake), "-S", str(src), "-B", str(destination), "-G", "Ninja",
             *common, *options], env)

    def compile(destination: Path, targets: list[str]) -> None:
        run([str(cmake), "--build", str(destination), "--parallel", "4", "--target", *targets], env)

    emitters = output / "emitters"
    configure(source / "psxrecomp/recompiler", emitters, ["-DPSXRECOMP_STATIC_CLI=ON"])
    compile(emitters, ["psxrecomp-game", "psxrecomp-bios"])
    host = output / "host"
    host_options = ["-DPSXRECOMP_FORCE_SETUP_HOST=ON", "-DPSX_ENABLE_VULKAN=OFF",
                    "-DPSX_DEBUG_TOOLS=OFF", "-DPSX_SDL3_FETCH=OFF", "-DPSX_ZLIB_FETCH=OFF"]
    if target == "linux-x64":
        host_options.append(f"-DSDL3_DIR={sdl / 'lib/cmake/SDL3'}")
    configure(source, host, host_options)
    compile(host, ["psx-runtime"])
    binaries = {name: path for name, path in (
        ("Shadow_Tower_Recompiled" + suffix, host / ("Shadow_Tower_Recompiled" + suffix)),
        ("psxrecomp-game" + suffix, emitters / ("psxrecomp-game" + suffix)),
        ("psxrecomp-bios" + suffix, emitters / ("psxrecomp-bios" + suffix)),
    )}
    if suffix:
        launcher = output / "launcher"
        configure(source / "packaging/windows", launcher, [])
        compile(launcher, ["ReShadowTower"])
        binaries["ReShadowTower.exe"] = launcher / "ReShadowTower.exe"
    hashes = {name: package_release.file_hash(path) for name, path in binaries.items()}
    if package_release.source_fingerprint() != fingerprint:
        raise ValueError("Source fingerprint changed during build; discard this output and retry")
    metadata = {"platform": target, "toolchain_sha256": bundled_toolchain.PINS[target][1],
                "source_fingerprint": fingerprint, "emitters": str(emitters), "binaries": hashes}
    if target == "linux-x64":
        metadata["sdl"] = {"archive_sha256": build_bundled_sdl.SHA256,
                           "prefix": str(sdl), "files": build_bundled_sdl.hashes(sdl)}
    (host / "release-build.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n",
                                              encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdl-archive", type=Path)
    args = parser.parse_args()
    try:
        build(args.toolchain_archive.resolve(), args.output.resolve(),
              args.sdl_archive.resolve() if args.sdl_archive else None)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Release build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
