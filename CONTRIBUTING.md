# Contributing to ReShadowTower

Thank you for helping improve ReShadowTower. This guide covers the rules on game
data, how to build and test, and what to include in issues and pull requests.

## Game data

ReShadowTower is built from each player's own disc. The repository and its
releases must never contain copyrighted game data. Do not commit, attach, or
link to:

- Disc images (BIN/CUE, ISO, CHD) or files extracted from them, including
  `SLUS_008.63` and other executables.
- Generated game code (`generated/`) or build output (`build-*/`, `out/`, `dist/`).
- BIOS dumps. The build uses the bundled OpenBIOS; no retail BIOS is needed.
- Memory cards (`.mcd`, `.mcr`) or save states.

Share reproduction steps, logs, and screenshots instead. Everything in `disc/`
and `saves/` is ignored by Git; do not force-add it.

## Building from source

Follow [Build from source](README.md#build-from-source) in the README. In short,
with the dependencies installed and your dump in `disc/`:

```bash
./scripts/build.sh
./scripts/run.sh
```

The accepted disc images are listed in [`disc/README.md`](disc/README.md).
Windows source builds use the MSYS2 MINGW64 shell.

## Testing

The test suite needs no disc, BIOS, or generated code:

```bash
python3 tools/run_tests.py
```

Without a display, use Xvfb and Mesa:

```bash
SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a python3 tools/run_tests.py
```

Skipped tests count as failures. Install the missing dependency rather than
ignoring the skip.

For gameplay changes, also test in-game with disposable saves and describe what
you checked in the pull request.

## Reporting bugs

Use the bug report form. It asks for:

- **Build:** release version, or `git rev-parse --short HEAD` for source builds.
- **Platform:** OS, GPU and driver version, and whether Windows results come
  from native Windows or Wine.
- **Settings:** your `settings.toml` and `input.ini` if relevant.
- **Save location** and whether the problem reproduces with a new save.
- **Logs** and steps to reproduce.

File locations:

| | Packaged (Linux) | Packaged (Windows) | Source build |
| --- | --- | --- | --- |
| Data directory | `~/.local/share/reshadowtower` | `%LOCALAPPDATA%\ReShadowTower` | Repository root |
| Saves | `<data>/saves` | `<data>\saves` | `saves/` |
| Settings and bindings | `<data>/releases/<id>/build-release/` | `<data>\releases\<id>\build-release\` | `build-release/` |
| Logs | `<data>/launcher.log`, plus `launcher-*.log` in the release directory | Same as Linux | `launcher-*.log` in the repository root |

On Linux, `$XDG_DATA_HOME` replaces `~/.local/share` when set.

## Pull requests

- Keep each pull request focused on one change, and link the issue it addresses
  (`Closes #123`).
- Explain what changed and why, and how you validated it, including any manual
  gameplay testing and remaining gaps.
- Run `python3 tools/run_tests.py` before opening the pull request. CI also
  builds and tests pull requests on Linux and Windows.
- Match the style of the surrounding code.
- Keep PSXRecomp framework fixes separate from title-specific code. Submit shared
  fixes upstream and update the verified pins in `cmake/dependencies.json`; do not
  rely on changes that exist only in a local `PSXRECOMP_ROOT` override.

## License

By contributing, you agree that your contribution is licensed under the
repository's [LICENSE](LICENSE). The PSXRecomp framework remains under its own
noncommercial license.
