#!/usr/bin/env python3
"""Route this title's runtime input through portable adapters, without linker wrapping."""
from __future__ import annotations

import argparse
from pathlib import Path


def prepare_input(source: str) -> str:
    """Adapt only the keyboard call and four SDL event loops in the pinned runtime."""
    replacements = (
        ('#include "psx_keybinds.h"',
         '#include "modern_controls.h"\n#include "psx_keybinds.h"', 1),
        ('return psx_keybinds_pad_word(keys, player);',
         'return shadowtower_pad_word(keys, player);', 1),
        ('while (SDL_PollEvent(&ev)) {',
         'while (shadowtower_poll_event(&ev)) {', 4),
    )
    for old, new, count in replacements:
        if source.count(old) != count:
            raise ValueError(f"Input integration point changed: {old!r}. "
                             "Review tools/prepare_input.py against the framework revision.")
        source = source.replace(old, new)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare_input(args.source.read_text(encoding="utf-8"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Input preparation failed: {error}\n")


if __name__ == "__main__":
    main()
