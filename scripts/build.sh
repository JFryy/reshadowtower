#!/usr/bin/env bash
# Generate game/BIOS C and build the player runtime from a local disc.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -n "${MSYSTEM:-}" && "$MSYSTEM" != MINGW64 ]]; then
    echo "Unsupported MSYS2 environment '$MSYSTEM'. Use the MSYS2 MINGW64 shell." >&2
    exit 1
fi

disc="${1:-disc/Shadow Tower (USA).cue}"
bios_args=()
if [[ -n "${2:-}" ]]; then
    bios_args=(--bios "$2")
fi
if [[ ! -f "$disc" ]]; then
    echo "Missing disc: $disc. Supply your own USA BIN/CUE dump." >&2
    exit 1
fi
PSXRECOMP_ROOT="$(python3 tools/dependencies.py)"
export PSXRECOMP_ROOT
python3 "$PSXRECOMP_ROOT/psxrecomp_cli.py" verify-disc \
    --config game.toml --project-root . --disc "$disc"
cmake -S "$PSXRECOMP_ROOT/recompiler" -B build-recompiler -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DPSXRECOMP_ENABLE_CHD=OFF
cmake --build build-recompiler --target psxrecomp-game psxrecomp-bios -j4
python3 "$PSXRECOMP_ROOT/psxrecomp_cli.py" generate \
    --config game.toml --project-root . --disc "$disc" "${bios_args[@]}"
PSXRECOMP_BIOS_BUILD="$PWD/build-recompiler" \
    "$PSXRECOMP_ROOT/tools/regen_bios.sh" --config bios/OpenBIOS.toml
python3 tools/generate_aot.py --jobs 4
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPSX_ENABLE_VULKAN=OFF -DPSX_DEBUG_TOOLS=OFF \
    -DPSXRECOMP_ROOT="$PSXRECOMP_ROOT"
cmake --build build-release --target psx-runtime -j4
