#!/usr/bin/env bash
# Generate game/BIOS C and build the player runtime from a local disc.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -n "${MSYSTEM:-}" && "$MSYSTEM" != MINGW64 ]]; then
    echo "Unsupported MSYS2 environment '$MSYSTEM'. Use the MSYS2 MINGW64 shell." >&2
    exit 1
fi

if [[ ! -f 'disc/Shadow Tower (USA).cue' ]]; then
    echo 'Missing disc/Shadow Tower (USA).cue. Place your own USA BIN/CUE dump in disc/ first.' >&2
    exit 1
fi
PSXRECOMP_ROOT="$(python3 tools/dependencies.py)"
export PSXRECOMP_ROOT
cmake -S "$PSXRECOMP_ROOT/recompiler" -B build-recompiler -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DPSXRECOMP_ENABLE_CHD=OFF
cmake --build build-recompiler --target psxrecomp-game psxrecomp-bios -j4
python3 "$PSXRECOMP_ROOT/psxrecomp_cli.py" generate \
    --config game.toml --project-root . --disc 'disc/Shadow Tower (USA).cue'
PSXRECOMP_BIOS_BUILD="$PWD/build-recompiler" \
    "$PSXRECOMP_ROOT/tools/regen_bios.sh" --config bios/OpenBIOS.toml
python3 tools/generate_aot.py --jobs 4
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPSX_ENABLE_VULKAN=OFF -DPSX_DEBUG_TOOLS=OFF \
    -DPSXRECOMP_ROOT="$PSXRECOMP_ROOT"
cmake --build build-release --target psx-runtime -j4
