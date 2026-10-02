#!/usr/bin/env python3
"""Run offline disc setup for the native launcher, never gameplay or settings."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


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
