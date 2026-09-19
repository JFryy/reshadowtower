#!/usr/bin/env bash
# Launch the locally built runtime with explicit project and disc paths.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) runtime="$PWD/build-release/Shadow_Tower_Recompiled.exe" ;;
    *) runtime="$PWD/build-release/Shadow_Tower_Recompiled" ;;
esac

if [[ ! -x "$runtime" ]]; then
    echo "Missing runtime: $runtime. Run: ./scripts/build.sh" >&2
    exit 1
fi
exec "$runtime" \
    --game "$PWD/game.toml" --disc "$PWD/disc/Shadow Tower (USA).cue" \
    --no-launcher "$@"
