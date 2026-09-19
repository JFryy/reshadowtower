#!/usr/bin/env python3
"""Generate static AOT overlays from the configured game disc."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT / "psxrecomp"
_SANITIZE = (
    "PSX_OVERLAY_CACHE_DIR",
    "PSX_OVERLAY_CAPTURES",
    "PSX_OVERLAY_FLAVOR",
    "PSX_STATIC_NO_ISOLATED",
)
_FALSE_ROOTS = {
    "82f818ca6121ef8168c7b9527a32eca957f199f1cae79c165015399f0f984158":
        0x80074634,
    "fdc01e70a6914680f6efa73d63e07bfbb1220e7be5105ea5804b76b1ead4ca0f":
        0x80042A54,
}
_ROOT_FIELDS = (
    "seeds",
    "function_entry_pcs",
    "dispatch_entry_pcs",
    "static_dispatch_entry_pcs",
)
_RESULT_RE = re.compile(
    r"PSX_SHARD_RESULT\s+ok=(\d+)\s+failed=(\d+)\s+skipped=(\d+)"
)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in _SANITIZE:
        env.pop(name, None)
    return env


def find_recompiler(root: Path = ROOT, *, windows: bool | None = None) -> Path:
    """Return the native emitter path, failing before code generation starts."""
    if windows is None:
        windows = os.name == "nt"
    name = "psxrecomp-game.exe" if windows else "psxrecomp-game"
    recompiler = (root / "build-recompiler" / name).resolve()
    if not recompiler.is_file():
        raise FileNotFoundError(
            f"missing emitter: {recompiler}; run ./scripts/build.sh first"
        )
    return recompiler


def address(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"invalid address value: {value!r}")


def filter_false_roots(captures: list[dict[str, Any]]) -> int:
    excluded = 0
    expected_bytes = bytes.fromhex("50730921ad424200")
    for capture in captures:
        payload = base64.b64decode(capture["bytes_b64"], validate=True)
        digest = hashlib.sha256(payload).hexdigest()
        root = _FALSE_ROOTS.get(digest)
        if root is None:
            continue

        load_addr = address(capture["load_addr"])
        offset = root - load_addr
        if offset < 0 or payload[offset:offset + 8] != expected_bytes:
            raise ValueError(f"false-root byte assertion failed at 0x{root:08X}")
        if root in {address(pc) for pc in capture.get("executed_pcs", [])}:
            raise ValueError(f"false root 0x{root:08X} was executed")
        entries = {address(pc) for pc in capture.get("function_entry_pcs", [])}
        if root + 8 not in entries:
            raise ValueError(
                f"expected function entry 0x{root + 8:08X} is absent"
            )

        for field in _ROOT_FIELDS:
            values = capture.get(field, [])
            capture[field] = [pc for pc in values if address(pc) != root]
        print(f"Excluded known false data root 0x{root:08X} ({digest})")
        excluded += 1
    return excluded


def run(args: argparse.Namespace) -> int:
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    captures_path = out_dir / "disc-captures.json"
    filtered_path = out_dir / "filtered-captures.json"
    discovery_dir = out_dir / "discovery"
    recompiler = find_recompiler()
    env = clean_environment()

    extract_command = [
        sys.executable,
        str(FRAMEWORK / "tools/aot_overlay_spike/extract_generic.py"),
        "--game-toml", str((ROOT / "game.toml").resolve()),
        "--recompiler", str(recompiler),
        "--out", str(captures_path),
        "--tmp", str(discovery_dir),
        "--no-bios-resident",
    ]
    subprocess.run(extract_command, check=True, env=env)

    with captures_path.open(encoding="utf-8") as source:
        captures = json.load(source)
    if not isinstance(captures, list) or not all(
        isinstance(capture, dict) for capture in captures
    ):
        raise ValueError(f"{captures_path} is not a capture list")
    exclusions = filter_false_roots(captures)
    with filtered_path.open("w", encoding="utf-8") as destination:
        json.dump(captures, destination, indent=2)
        destination.write("\n")

    compile_command = [
        sys.executable,
        str(FRAMEWORK / "tools/compile_overlays.py"),
        "--static",
        "--captures", str(filtered_path),
        "--game-toml", str((ROOT / "game.toml").resolve()),
        "--recompiler", str(recompiler),
        "--runtime-include", str((FRAMEWORK / "runtime/include").resolve()),
        "--out-dir", str(out_dir),
        "--cps",
        "--jobs", str(args.jobs),
        "--force",
    ]
    log_path = out_dir / "compile.log"
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            compile_command, stdout=log, stderr=subprocess.STDOUT, env=env
        )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    results = list(_RESULT_RE.finditer(log_text))
    if not results:
        raise RuntimeError(f"PSX_SHARD_RESULT absent; see {log_path}")
    result = results[-1]
    ok, failed, skipped = (int(value) for value in result.groups())
    print(
        f"AOT compile: ok={ok} failed={failed} skipped={skipped}; "
        f"excluded={exclusions}; log={log_path}"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"compile_overlays.py exited {completed.returncode}; see {log_path}"
        )
    if failed:
        raise RuntimeError(f"static compile reported {failed} failed shard(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "generated/aot",
        help="output directory (default: %(default)s)",
    )
    parser.add_argument("--jobs", type=positive_int, default=4)
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError, RuntimeError) as error:
        print(f"generate_aot.py: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
