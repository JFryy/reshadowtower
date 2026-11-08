#!/usr/bin/env python3
"""Validate the GLSL embedded in the patched GL renderer with glslangValidator."""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from dependencies import framework_root
from prepare_source import prepare

DEFAULT_FRAGMENTS = [ROOT / "src/world_texture_filter.glsl", ROOT / "src/post_processing.glsl"]
RENDERER = "runtime/src/gpu_gl_renderer.c"
# Every renderer shader that includes a fragment or shares its program, with its stage.
SHADERS = {"PRESENT_VS": "vert", "PRESENT_FS": "frag", "INTERP_FS": "frag",
           "TEX_VS": "vert", "TEX_FS": "frag"}
LITERAL = r'"(?:\\.|[^"\\])*"'


def _expand_macro(source: str, name: str) -> str:
    match = re.search(r"(?m)^#define " + name + r" \\\n((?:.*\\\n)*?    " + LITERAL + r"\n)", source)
    if not match:
        raise ValueError(f"renderer source has no {name} macro")
    return "\n".join(re.findall(LITERAL, match.group(1))) + "\n"


def extract(source: str, name: str, includes: Path) -> str:
    """Return the GLSL text of one renderer shader with includes and macros expanded."""
    declaration = re.search(r"static const char \*" + re.escape(name) + r"\s*=", source)
    if not declaration:
        raise ValueError(f"patched renderer has no {name}")
    tail = source[declaration.end():]
    end = re.search(r'^\s*' + LITERAL + r';\s*$', tail, re.M)
    if not end:
        raise ValueError(f"patched renderer has unterminated {name}")
    body = tail[:end.end()]
    body = re.sub(r'(?m)^#include "([\w.]+\.inc)"$',
                  lambda m: (includes / m.group(1)).read_text(encoding="utf-8"), body)
    for macro in ("PSX_SCANLINE_UNIFORMS", "PSX_SCANLINE_FUNC"):
        body = re.sub(r"(?m)^\s*" + macro + r"\s*$", lambda _: _expand_macro(source, macro), body)
    tokens = re.findall(LITERAL, body)
    if not tokens:
        raise ValueError(f"{name} has no string literals")
    return "".join(ast.literal_eval(token) for token in tokens)


def lint(fragments: list[Path] | None = None) -> list[str]:
    """Validate every embedded shader; return one report line each, raise on failure."""
    validator = shutil.which("glslangValidator")
    if not validator:
        raise RuntimeError("glslangValidator not found; install the glslang package")
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        patched = work / "gpu_gl_renderer.c"
        prepare(framework_root() / RENDERER, ROOT / "patches/runtime-graphics.patch", patched,
                fragments or DEFAULT_FRAGMENTS)
        source = patched.read_text(encoding="utf-8")
        reports, failures = [], []
        for name, stage in SHADERS.items():
            path = work / f"{name.lower()}.{stage}"
            path.write_text(extract(source, name, work), encoding="utf-8")
            result = subprocess.run([validator, str(path)], capture_output=True, text=True)
            if result.returncode:
                failures.append(f"{name}:\n{(result.stdout + result.stderr).strip()}")
            reports.append(f"{name} ({stage}): {'FAILED' if result.returncode else 'ok'}")
        if failures:
            raise RuntimeError("\n".join(reports) + "\n" + "\n".join(failures))
        return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fragment", type=Path, action="append",
                        help="override the GLSL fragments (default: src/*.glsl)")
    args = parser.parse_args()
    try:
        print("\n".join(lint(args.fragment)))
    except (OSError, RuntimeError, ValueError) as error:
        sys.exit(f"Shader lint failed: {error}")
