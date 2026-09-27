#!/usr/bin/env bash
# Stage an offline release using an explicitly supplied, checksum-pinned archive.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ $# -lt 4 || $# -gt 6 ]]; then
    echo "usage: $0 <build-dir> <linux-x64|windows-x64> <toolchain.zip> <output-dir> [emitter-dir] [windows-launcher]" >&2
    exit 2
fi
extra=()
if [[ "$2" == windows-x64 ]]; then
    extra+=(--windows-launcher "${6:-$1/../launcher/ReShadowTower.exe}")
fi
exec python3 tools/package_release.py \
    --build "$1" --platform "$2" --toolchain-archive "$3" \
    --output "$4" --emitters "${5:-$1/../emitters}" "${extra[@]}"
