# Contributing to ReShadowTower

## Game data

ReShadowTower is built from each player's own disc. Never commit, attach, or
link to disc images or files extracted from them, generated game code
(`generated/`), build output, BIOS dumps, memory cards, or save states.
`captures/overlay_captures.json` is the one exception: it holds kernel RAM
code that no disc file contains.

## Building and testing

Build as described in [Build from source](README.md#build-from-source). The
test suite needs no disc:

```bash
python3 tools/run_tests.py
```

Without a display:

```bash
SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a python3 tools/run_tests.py
```

Skipped tests count as failures; install the missing dependency. For gameplay
changes, also test in-game with disposable saves.

## Reporting bugs

Use the bug report form. Logs and settings are here:

| | Packaged (Linux) | Packaged (Windows) | Source build |
| --- | --- | --- | --- |
| Data directory | `~/.local/share/reshadowtower` | `%LOCALAPPDATA%\ReShadowTower` | Repository root |
| Saves | `<data>/saves` | `<data>\saves` | `saves/` |
| Settings and bindings | `<data>/releases/<id>/build-release/` | `<data>\releases\<id>\build-release\` | `build-release/` |
| Logs | `<data>/launcher.log`, plus `launcher-*.log` in the release directory | Same as Linux | `launcher-*.log` in the repository root |

On Linux, `$XDG_DATA_HOME` replaces `~/.local/share` when set.

## Pull requests

- One change per pull request, linked to its issue (`Closes #123`).
- Say what changed, why, and how you tested it.
- Run `python3 tools/run_tests.py` first.
- Framework changes go in `patches/*.patch` against the revision pinned in
  `cmake/dependencies.json`, wired in through `cmake/*.cmake`. When bumping a
  pin, regenerate the affected patches and run `tests/test_source_adapters.py`.

## License

Contributions are licensed under the repository's [LICENSE](LICENSE). The
PSXRecomp framework remains under its own noncommercial license.
