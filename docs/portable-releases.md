# Release status

ReShadowTower currently provides source-build instructions, not a verified
portable distribution. Follow the [README](../README.md) and supply your own
Shadow Tower USA BIN/CUE dump.

## Verified scope

- Prior Linux builds and selected gameplay scenes were tested on the development
  machine, not across a distribution compatibility matrix. The current
  debug-disabled build passed a rebuild and headless startup check with isolated
  saves and no open sockets; manual gameplay revalidation remains pending.
- Windows input integration uses portable adapters rather than ELF linker
  wrappers. Earlier Wine tests verified OpenGL gameplay rendering, injected
  turning input, save-state save/load, and clean exit. The current debug-disabled
  Windows x64 build was cross-compiled and passed OpenGL startup at 3× internal
  scale and clean exit under Wine 11.15, using isolated saves with no debug
  listener. This rerun did not revalidate gameplay or controls. Native MSYS2
  builds and gameplay on real Windows still need verification.
- The build generates static AOT game modules from the user's disc. The current
  player build disables debug tooling and uses 4:3, not widescreen.
- No portable packaging pipeline or destination-machine acceptance pass is
  established. A local executable alone is not a portable release.

## Before any public binary release

First establish a distribution approach that does not ship retail assets or
assume generated game code is redistributable. The project's MIT license does
not grant game rights or replace PSXRecomp's noncommercial terms. Retain all
applicable third-party notices. Never upload local private-transfer archives.

Then validate each intended target OS with isolated saves:

- Launch from a writable path containing spaces, away from the development tree.
- Check runtime libraries and any required first-run generation tools explicitly.
- Reach gameplay and check mouse capture/release, WASD, menus, attack, audio,
  and the current graphics defaults with debug tools disabled.
- Cross an area boundary, save at a headstone, exit, restart, and load the save.
- Confirm no developer-path dependencies, missing libraries, or debug listener.
