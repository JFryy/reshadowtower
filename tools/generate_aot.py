#!/usr/bin/env python3
"""Generate static AOT overlays from the configured game disc."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from dependencies import framework_root

ROOT = Path(__file__).resolve().parents[1]
# Kernel RAM code (OpenBIOS plus game-installed stubs) that no disc file holds,
# recorded by tools/coverage_report.py --update-captures.
RUNTIME_CAPTURES = ROOT / "captures/overlay_captures.json"
AREA_ARCHIVE = "ST/COM/FDAT.T"
SECTOR = 0x800
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


def find_recompiler(root: Path = ROOT, *, windows: bool | None = None,
                    framework: Path | None = None) -> Path:
    """Return the native emitter path, failing before code generation starts."""
    if windows is None:
        windows = os.name == "nt"
    name = "psxrecomp-game.exe" if windows else "psxrecomp-game"
    candidates = (
        root / "build-recompiler" / name,
        (framework if framework is not None else root / "psxrecomp")
        / "recompiler" / "build" / name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"missing emitter: {candidates[0].resolve()} or {candidates[1].resolve()}; "
        "run ./scripts/build.sh or reinstall the setup package"
    )


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


def load_capture_list(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        captures = json.load(source)
    if not isinstance(captures, list) or not all(
        isinstance(capture, dict) for capture in captures
    ):
        raise ValueError(f"{path} is not a capture list")
    return captures


def area_code_blocks(archive: bytes) -> list[bytes]:
    """Split FDAT.T into its per-area code blocks.

    The archive opens with a zero-terminated table of u16 sector pairs
    (data, code), one per area after a leading header entry. An area's code
    block runs from its code sector to the next entry's data sector.
    """
    entries = []
    for (word,) in struct.iter_unpack("<I", archive[:SECTOR]):
        if word == 0:
            break
        entries.append((word & 0xFFFF, word >> 16))
    total = len(archive) // SECTOR
    blocks = []
    for index, (_, code) in enumerate(entries[1:], 1):
        end = entries[index + 1][0] if index + 1 < len(entries) else total
        if code < end <= total:
            blocks.append(archive[code * SECTOR:end * SECTOR])
    return blocks


def area_module_records(framework: Path, disc_cue: Path) -> list[dict[str, Any]]:
    """Build capture records for every area code module on the disc.

    extract_generic.py skips files over 2 MB, which excludes FDAT.T. Each
    block must pass the framework's strict raw-code base proof, or (like the
    framework's cross-file header-table fit) win its base vote by 2x for a
    base a strictly proven sibling already established. Other blocks are
    left to the interpreter.
    """
    tools = framework / "tools"
    for path in (tools, tools / "aot_overlay_spike"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import extract_generic as producer
    import extract_overlays as iso

    bin_path, raw = producer.parse_cue_datatrack(str(disc_cue))
    disc = iso.DiscReader(bin_path, raw=raw)
    try:
        located = [(lba, size) for name, lba, size in iso.enumerate_files(disc)
                   if name.upper().split(";")[0] == AREA_ARCHIVE]
        if len(located) != 1:
            raise ValueError(f"{AREA_ARCHIVE} not found on {disc_cue}")
        archive = disc.read_file_bytes(*located[0])
    finally:
        disc.close()

    blocks = list({hashlib.sha256(b).digest(): b
                   for b in area_code_blocks(archive)}.values())
    proven = {}
    for block in blocks:
        proof = producer.recover_raw_base(block, 0x80010000)
        if proof is not None:
            proven[id(block)] = proof[0]
    trusted = set(proven.values())
    for block in blocks:
        if id(block) in proven:
            continue
        votes = producer.raw_base_votes(block, 0x80010000).most_common(2)
        if votes and votes[0][0] in trusted and (
                len(votes) == 1 or votes[0][1] >= 2 * votes[1][1]):
            proven[id(block)] = votes[0][0]

    records = []
    for block in blocks:
        base = proven.get(id(block))
        if base is None:
            continue
        seeds = sorted(set(producer.prologues(block, base))
                       | producer.frameless_leaf_entries(block, base)
                       | producer.supplemental_callable_seeds(block, base))
        page_base, region = producer.page_aligned_region(base, block)
        direct = producer.direct_jal_roots(block, base)
        record = producer.rec(page_base, region, seeds, static_discovery=direct)
        if direct and set(seeds) != set(direct):
            record["optional_enrichment_fallback_entry_pcs"] = [
                f"0x{pc:08X}" for pc in direct]
        records.append(record)
    return records


def run(args: argparse.Namespace) -> int:
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    captures_path = out_dir / "disc-captures.json"
    filtered_path = out_dir / "filtered-captures.json"
    discovery_dir = out_dir / "discovery"
    framework = framework_root()
    recompiler = find_recompiler(framework=framework)
    env = clean_environment()
    subprocess.run(
        ["cmake", f"-DPSXRECOMP_ROOT={framework}",
         "-P", str(ROOT / "cmake/generate_codegen_hash.cmake")],
        check=True, env=env,
    )

    extract_command = [
        sys.executable,
        str(framework / "tools/aot_overlay_spike/extract_generic.py"),
        "--game-toml", str((ROOT / "game.toml").resolve()),
        "--recompiler", str(recompiler),
        "--out", str(captures_path),
        "--tmp", str(discovery_dir),
        "--no-bios-resident",
    ]
    subprocess.run(extract_command, check=True, env=env)

    captures = load_capture_list(captures_path)
    with (ROOT / "game.toml").open("rb") as source:
        disc_cue = ROOT / tomllib.load(source)["game"]["disc"]
    areas = area_module_records(framework, disc_cue)
    captures.extend(areas)
    print(f"Area modules: {len(areas)} from {AREA_ARCHIVE}")
    if args.runtime_captures.is_file():
        runtime = load_capture_list(args.runtime_captures)
        captures.extend(runtime)
        print(f"Runtime captures: {len(runtime)} from {args.runtime_captures}")
    exclusions = filter_false_roots(captures)
    with filtered_path.open("w", encoding="utf-8") as destination:
        json.dump(captures, destination, indent=2)
        destination.write("\n")

    compile_command = [
        sys.executable,
        str(framework / "tools/compile_overlays.py"),
        "--static",
        "--captures", str(filtered_path),
        "--game-toml", str((ROOT / "game.toml").resolve()),
        "--recompiler", str(recompiler),
        "--runtime-include", str((framework / "runtime/include").resolve()),
        "--out-dir", str(out_dir),
        "--cps",
        "--jobs", str(args.jobs),
        "--force",
    ]
    log_path = out_dir / "compile.log"
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            compile_command, stdout=log, stderr=subprocess.STDOUT, env=env, check=False
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
    parser.add_argument(
        "--runtime-captures", type=Path, default=RUNTIME_CAPTURES,
        help="runtime overlay captures to compile, if present (default: %(default)s)",
    )
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError, RuntimeError) as error:
        print(f"generate_aot.py: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
