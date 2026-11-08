# Architecture

ReShadowTower is a title layer on top of the PSXRecomp static recompiler and
runtime. The framework is not vendored. This repository holds the title
configuration, a set of patches to the framework, a few title-specific sources,
and the launcher.

## Framework pin

- `cmake/dependencies.json` pins the framework revision and its other inputs.
- `tools/dependencies.py` resolves the pins through `cmake/dependencies.cmake`
  and exposes `framework_root()`. Sources land in `build-dependencies/`.

## Title configuration

`game.toml` is the title config read by the recompiler and runtime. It holds
`[prepare_disc]` (accepted disc sizes and MD5, SHA-1, and CRC32 hashes, output
names), `[recompiler]` (seeds, output in `generated/`, and
`mod_function_entry_funcs`, which lists guest functions whose generated code
calls registered function-entry hooks; mouse look hooks `0x80041D4C` this way),
plus runtime, video, widescreen, and controller settings.

## Patches

Framework changes live in `patches/*.patch`. `tools/prepare_source.py` applies a
patch to the pinned file at build time, checking the file's sha256 (the
`# source-sha256:` header) and requiring exact context. Output goes to the build
directory and replaces the original in the runtime source list.

| CMake file | Patch | Framework file |
| --- | --- | --- |
| `cmake/graphics.cmake` | `runtime-graphics.patch` | `runtime/src/gpu_gl_renderer.c` |
| | `runtime-widescreen.patch` | `runtime/src/gpu.c` |
| | `runtime-software.patch` | `runtime/src/gpu_sw_renderer.c` |
| | `runtime-settings.patch` | `recompiler/src/config_loader.cpp` |
| `cmake/input.cmake` | `runtime-input.patch` | `runtime/src/main.cpp` |
| `cmake/saves.cmake` | `runtime-memcard.patch` | `runtime/src/memcard.c` |
| `cmake/overrides.cmake` | `runtime-overrides.patch` | `runtime/src/data_shards.c` |
| | `runtime-overrides-interp.patch` | `runtime/src/dirty_ram_interp.c` |
| `cmake/recompiler_overrides.cmake` | `recompiler-overrides.patch` | `recompiler/src/main_psx.cpp` |

`cmake/adapters.cmake` defines `shadowtower_prepare`. Other files in `cmake/`:
`generate_codegen_hash.cmake` (framework fingerprint before offline AOT
generation) and `llvm-mingw.cmake` (Linux to Windows toolchain).

## Sources in `src/`

- `function_overrides.c`, `function_overrides.h`: the function override registry.
  Hand-written C replacements for recompiled guest functions register here and
  are called from the patched data shard and interpreter entry points.
- `modern_controls.c`, `modern_controls.h`: mouse look, right-stick camera, and
  event adapters for the framework's input path.
- `post_processing.h`, `post_processing.glsl`, `post_processing_gl.h`: display
  effect settings parser, shader code, and uniform handling.
- `world_texture_filter.glsl`: world texture filtering code for the texture shader.
- `render_scale.h`, `render_scale_gl.h`: internal resolution limits and render
  target allocation.
- `settings_ranges.h`: setting ranges and defaults shared by launcher and runtime.

The `.glsl` files are turned into `.inc` string literals by
`tools/prepare_source.py` and included from the patched renderer.
`tools/lint_shaders.py` validates the result with `glslangValidator`.

## Launcher

`launcher/` is the ImGui launcher (`main.cpp`, `model.hpp` for settings and
`settings.toml` handling, `bindings.hpp` for input bindings).
`tools/launcher_backend.py` runs disc setup and the build or packaged release
steps for it. Release packaging is done by `tools/build_release.py` and
`tools/package_release.py`.

## Data and generated files

- `captures/overlay_captures.json`: kernel RAM code only, written by
  `tools/coverage_report.py --update-captures`.
- `generated/`: recompiler output from the player's disc. Untracked.
- `disc/`, `saves/`: player data. Untracked.

## Tests

`tests/test_*.py` run with `python3 tools/run_tests.py`, which discovers them and
treats skipped tests as failures. No disc or generated code is needed. C tests
in `tests/*.c` are compiled by their Python wrappers. `tests/test_source_adapters.py`
checks every patch against the pinned framework.
