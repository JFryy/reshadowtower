#!/usr/bin/env python3
"""Generate a title-local OpenGL renderer without modifying the framework checkout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(source: str, old: str, new: str) -> str:
    """Reject upstream drift rather than silently building a partial adaptation."""
    if source.count(old) != 1:
        raise ValueError(f"OpenGL integration point changed: {old[:100]!r}. "
                         "Review tools/prepare_graphics.py against the framework revision.")
    return source.replace(old, new, 1)


def prepare_renderer(source: str, shader: str) -> str:
    """Add selective spatial filtering while retaining upstream decoding and blending."""
    source = replace_once(source, "#define TEXV 20", "#define TEXV 21")
    source = replace_once(source,
        '    "layout(location=9) in float a_q;   /* persp weight; 0 = affine (default) */\\n"',
        '    "layout(location=9) in float a_q;   /* persp weight; 0 = affine (default) */\\n"\n'
        '    "layout(location=10) in float a_world_filter;\\n"\n'
        '    "flat out int v_world_filter;\\n"')
    source = replace_once(source,
        '    "  v_persp = (a_q > 0.0) ? 1 : 0;\\n"',
        '    "  v_persp = (a_q > 0.0) ? 1 : 0;\\n"\n'
        '    "  v_world_filter = int(a_world_filter);\\n"')
    source = replace_once(source,
        '    "smooth in vec2 v_uv_p; flat in int v_persp;\\n"',
        '    "smooth in vec2 v_uv_p; flat in int v_persp;\\n"\n'
        '    "flat in int v_world_filter;\\n"')
    source = replace_once(source,
        '    "void main(){\\n"\n    "  int stp; vec3 rgb;\\n"',
        ''.join('    ' + json.dumps(line + '\n') + '\n' for line in shader.splitlines())
        + '    "void main(){\\n"\n    "  int stp; vec3 rgb;\\n"')
    start = source.index('    "  if (u_filter == 0) {\\n"', source.index('static const char *TEX_FS'))
    end = source.index('    "  if (u_semipass == 1', start)
    source = source[:start] + '''    "  vec2 dx = dFdx(uv), dy = dFdy(uv);\\n"
    "  int raw = fetch_texel(int(floor(uv.x)), int(floor(uv.y)));\\n"
    "  if (raw == 0) discard;\\n"
    "  stp = (raw >> 15) & 1;\\n"
    "  rgb = (u_filter != 0 && v_world_filter != 0)\\n"
    "      ? world_filter(uv, dx, dy, raw) : col5(raw);\\n"
''' + source[end:]
    source = replace_once(source,
        "    int lim_buf[4];\n    int uv_buf[6];\n    if (!lim) {",
        "    /* Rectangles carry explicit limits. Only modulated, opaque polygons\n"
        "     * with validated subpixel positions qualify, not raw sprites/UI. */\n"
        "    const int world_filter = !lim && s_pc_valid && !rawtex && semi < 0;\n"
        "    int lim_buf[4];\n    int uv_buf[6];\n    if (!lim) {")
    source = replace_once(source,
        "            vp[19] = s_pq_valid ? s_pq[i] : 0.0f;                   /* a_q; 0 = affine */",
        "            vp[19] = s_pq_valid ? s_pq[i] : 0.0f;                   /* a_q; 0 = affine */\n"
        "            vp[20] = (float)world_filter;")
    anchor = "        p_glVertexAttribPointer(9, 1, GL_FLOAT, GL_FALSE, st, (void*)(19*sizeof(float))); p_glEnableVertexAttribArray(9); /* q      */"
    source = replace_once(source, anchor, anchor + "\n"
        "        p_glVertexAttribPointer(10, 1, GL_FLOAT, GL_FALSE, st, (void*)(20*sizeof(float))); p_glEnableVertexAttribArray(10);")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--shader", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare_renderer(args.source.read_text(encoding="utf-8"),
                                  args.shader.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Graphics preparation failed: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
