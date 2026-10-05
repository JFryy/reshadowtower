#!/usr/bin/env python3
"""Run source or packaged disc setup for the native launcher."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from release_common import file_hash


def setup_source(workspace: Path, disc: Path, bios: Path | None) -> None:
    """Build a source checkout with local tools and record its playable binary."""
    ready = workspace / ".build-ready"
    ready.unlink(missing_ok=True)
    command = ["bash", str(workspace / "scripts/build.sh"), str(disc)]
    if bios is not None:
        command.append(str(bios))
    log_path = workspace / "launcher-actions.log"
    print("Building the game from source...", flush=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        log.write("\nSource setup: verify disc, generate code, and build game\n")
        result = subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(
            f"Source setup failed (exit {result.returncode}). Details: {log_path}. "
            "Check the first error for missing build tools or invalid disc data."
        )
    suffix = ".exe" if os.name == "nt" else ""
    executable = workspace / "build-release" / ("Shadow_Tower_Recompiled" + suffix)
    temporary = ready.with_suffix(".tmp")
    temporary.write_text(file_hash(executable) + "\n", encoding="utf-8")
    temporary.replace(ready)
    print("Setup complete. The game is ready to play.", flush=True)


def setup(workspace: Path, disc: Path, bios: Path | None = None) -> None:
    """Verify and generate a supplied disc, then build the playable runtime."""
    workspace = workspace.resolve(strict=True)
    disc = disc.expanduser().resolve(strict=True)
    if not disc.is_file():
        raise ValueError("Select a Shadow Tower (USA) disc image file.")
    if bios is not None:
        bios = bios.expanduser().resolve(strict=True)
        if not bios.is_file():
            raise ValueError("The selected BIOS is not a file.")
    cli = workspace / "tools/release_cli.py"
    if not cli.is_file() or not (workspace / "game.toml").is_file():
        raise ValueError("Setup files are missing. Reinstall the complete release; saves are stored separately.")
    if (workspace / "scripts/build.sh").is_file():
        setup_source(workspace, disc, bios)
        return
    common = ["--project-root", str(workspace), "--config", str(workspace / "game.toml"), "--json-progress"]
    generate = ["generate", *common, "--disc", str(disc), "--no-toolchain-download", "--force-prepare"]
    if bios is not None:
        generate += ["--bios", str(bios)]
    commands = [
        ("Verifying the disc", ["verify-disc", *common, "--disc", str(disc)]),
        ("Generating game code", generate),
        ("Building the game", ["rebuild", *common, "--build-dir", str(workspace / "build-release"),
                               "--target", "psx-runtime", "--exe-basename", "Shadow_Tower_Recompiled"]),
    ]
    log_path = workspace / "launcher-actions.log"
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        for label, arguments in commands:
            print(label + "...", flush=True)
            log.write("\n" + label + "\n")
            result = subprocess.run([sys.executable, str(cli), *arguments], cwd=workspace,
                                    stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f"{label} failed (exit {result.returncode}). Details: {log_path}. Correct the input or reported build error and retry.")
    print("Setup complete. The game is ready to play.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("setup")
    prepare.add_argument("--disc", type=Path, required=True)
    prepare.add_argument("--bios", type=Path)
    args = parser.parse_args()
    try:
        setup(args.workspace, args.disc, args.bios)
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        # The native launcher redirects stdout to its process log.
        print(f"Setup failed: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
