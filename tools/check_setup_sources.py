#!/usr/bin/env python3
"""Reject setup-host source manifests that contain generated game or BIOS code."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        validate_sources(args.manifest, args.project)
    except (OSError, ValueError) as error:
        print(f"Setup-host verification failed: {error}", file=sys.stderr)
        return 1
    print("Setup-host sources exclude generated game and BIOS code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
