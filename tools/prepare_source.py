#!/usr/bin/env python3
"""Apply a title patch to an exact upstream revision without requiring Git on players' PCs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n")


def apply_patch(source: str, patch: str) -> str:
    header = patch.splitlines(keepends=True)[:3]
    expected = f"# source-sha256: {hashlib.sha256(source.encode()).hexdigest()}\n"
    if len(header) != 3 or header[0] != expected:
        raise ValueError("Upstream source changed; review the title patch before rebuilding.")
    if not header[1].startswith("--- ") or not header[2].startswith("+++ "):
        raise ValueError("Expected a single-file unified patch.")
    hunks = re.split(r"(?m)(^@@[^\n]*\n)", patch[len("".join(header)):])
    if hunks[0] or len(hunks) < 3:
        raise ValueError("Patch has no valid hunks.")
    original = source.splitlines(keepends=True)
    result: list[str] = []
    position = 0
    for heading, body in zip(hunks[1::2], hunks[2::2]):
        match = HUNK.fullmatch(heading)
        if not match:
            raise ValueError(f"Invalid patch hunk: {heading.strip()}")
        old_start, old_count, new_start, new_count = (int(n) if n is not None else 1 for n in match.groups())
        start = old_start if old_count == 0 else old_start - 1
        lines = body.splitlines(keepends=True)
        if any(line[0] not in " +-" for line in lines):
            raise ValueError("Unsupported patch line; only text hunks are supported.")
        before = [line[1:] for line in lines if line[0] in " -"]
        after = [line[1:] for line in lines if line[0] in " +"]
        if not position <= start <= len(original) or len(before) != old_count or len(after) != new_count:
            raise ValueError("Overlapping patch hunks or incorrect line counts.")
        if original[start:start + old_count] != before:
            raise ValueError(f"Patch context does not match at line {old_start}.")
        result.extend(original[position:start])
        if len(result) != (new_start if new_count == 0 else new_start - 1):
            raise ValueError("Patch output line offset does not match.")
        result.extend(after)
        position = start + old_count
    return "".join(result + original[position:])


def prepare(source: Path, patch: Path, output: Path, shader: Path | list[Path] | None = None) -> None:
    result = apply_patch(source.read_text(encoding="utf-8-sig"), patch.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    shaders = [] if shader is None else [shader] if isinstance(shader, Path) else shader
    for item in shaders:
        literals = "\n".join(json.dumps(line + "\n") for line in item.read_text().splitlines())
        (output.parent / (item.stem + ".inc")).write_text(literals + "\n", encoding="utf-8")
    output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shader", type=Path, action="append")
    args = parser.parse_args()
    try:
        prepare(args.source, args.patch, args.output, args.shader)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Source preparation failed: {error}\n")
