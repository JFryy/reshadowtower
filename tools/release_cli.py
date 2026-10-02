#!/usr/bin/env python3
"""Run the package's generation and rebuild steps without toolchain downloads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from release_common import OFFLINE_CMAKE_OPTIONS, file_hash

ROOT = Path(__file__).resolve().parents[1]


def command_arguments(arguments: list[str]) -> list[str]:
    if not arguments or arguments[0] not in ("generate", "rebuild", "verify-disc"):
        raise ValueError("This package only supports generate, rebuild, and verify-disc.")
    result = list(arguments)
    if "--prune-after" in result:
        index = result.index("--prune-after")
        del result[index:index + 2]
    if result[0] == "rebuild":
        result += ["--no-toolchain-download", "--no-pgo"]
        result.extend(f"--cmake-extra={option}" for option in OFFLINE_CMAKE_OPTIONS)
    return result


def main() -> int:
    try:
        args = command_arguments(sys.argv[1:])
        pack = Path(os.environ["SHADOWTOWER_BUNDLED_TOOLCHAIN"])
        suffix = ".exe" if os.name == "nt" else ""
        for tool in ("cmake", "ninja", "clang", "clang++"):
            if not (pack / "bin" / (tool + suffix)).is_file():
                raise ValueError(f"Bundled {tool} is missing. Re-extract the complete release package.")
        if args[0] == "rebuild" and os.name != "nt":
            sdl = ROOT / "bundled-sdl/lib/cmake/SDL3"
            if not sdl.is_dir() or not (sdl / "SDL3Config.cmake").is_file():
                raise ValueError("Packaged SDL SDK is missing. Reinstall the complete release to restore mouse input support.")
            args.append(f"--cmake-extra=-DSDL3_DIR={sdl}")
            os.environ["SDL3_DIR"] = str(sdl)
        os.environ["RETCOMM_TOOLCHAIN_DIR"] = str(pack)
        os.environ["PSXRECOMP_TOOLCHAIN_DIR"] = str(pack)
        ready = ROOT / ".build-ready"
        if args[0] in ("generate", "rebuild"):
            ready.unlink(missing_ok=True)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "psxrecomp/psxrecomp_cli.py"), *args], cwd=ROOT,
        )
        if completed.returncode:
            return completed.returncode
        if args[0] == "rebuild":
            executable = ROOT / "build-release" / ("Shadow_Tower_Recompiled" + suffix)
            digest = file_hash(executable)
            temporary = ready.with_suffix(".tmp")
            temporary.write_text(digest + "\n", encoding="utf-8")
            temporary.replace(ready)
            return 0
        if args[0] == "generate":
            print(json.dumps({"event": "phase", "phase": "aot", "pct": 0.8,
                              "message": "Generating the remaining game modules..."}), flush=True)
            return subprocess.run([sys.executable, str(ROOT / "tools/generate_aot.py")], cwd=ROOT).returncode
        return 0
    except (OSError, KeyError, ValueError) as error:
        print(f"ReShadowTower setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
