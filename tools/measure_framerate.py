#!/usr/bin/env python3
"""Reproduce the docs/framerate.md VSync(3) versus VSync(0) comparison.

Holds digital turn-right in first-room gameplay and counts writes to the
persistent yaw at 0x801991A2 using the runtime's write trace, which records the
guest VBlank of every write. The unlocked mode patches the low byte of 0x800175C0
(the VSync argument) from 3 to 0 and always restores it. Needs the disc, so it
is a local tool.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from collections import Counter
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_session  # noqa: E402

VSYNC_ARG_ADDR = "800175c0"
VSYNC_ORIGINAL = 3
YAW_LO = 0x801991A0
YAW_ADDR = 0x801991A2
TURN_RIGHT = 0x0020
YAW_MODULUS = 4096  # PSX angles: 4096 units per revolution.


def signed_delta(previous: int, current: int, modulus: int = YAW_MODULUS) -> int:
    half = modulus // 2
    return (current - previous + half) % modulus - half


def summarize(samples: Sequence[tuple[int, int]], start_frame: int, end_frame: int,
              initial_yaw: int, modulus: int = YAW_MODULUS) -> dict[str, Any]:
    """Summarize yaw writes. `samples` are (vblank, yaw) per write, in order.

    Units are absolute wrapped yaw movement from `initial_yaw` through the last
    write, divided by the observed VBlanks.
    """
    vblanks = end_frame - start_frame
    if vblanks <= 0:
        raise ValueError(f"end_frame {end_frame} must be after start_frame {start_frame}")
    units = 0
    previous = initial_yaw
    for _, yaw in samples:
        units += abs(signed_delta(previous, yaw, modulus))
        previous = yaw
    gaps = Counter(b[0] - a[0] for a, b in zip(samples, samples[1:]))
    return {
        "vblanks": vblanks,
        "updates": len(samples),
        "spacing_histogram": {str(gap): gaps[gap] for gap in sorted(gaps)},
        "spacing_min": min(gaps) if gaps else None,
        "spacing_max": max(gaps) if gaps else None,
        "yaw_units": units,
        "units_per_vblank": units / vblanks,
    }


def format_spacing(summary: dict[str, Any]) -> str:
    low, high = summary["spacing_min"], summary["spacing_max"]
    if low is None:
        return "n/a"
    unit = "VBlank" if high == 1 else "VBlanks"
    return f"{low} {unit}" if low == high else f"{low}-{high} {unit}"


def yaw_from_entry(entry: dict[str, str | int]) -> int | None:
    """Extract the yaw halfword from a write-trace entry, or None if it did not write it."""
    phys = int(str(entry["addr"]), 16)
    width = int(entry["w"])
    new = int(str(entry["new"]), 16)
    if width == 2 and phys == YAW_ADDR & 0x1FFFFFFF:
        return new & 0xFFFF
    if width == 4 and phys == YAW_LO & 0x1FFFFFFF:
        return new >> 16
    return None


def read_yaw(port: int) -> int:
    data = bytes.fromhex(game_session.query(port, "read_ram", addr=f"{YAW_ADDR:08x}", len=2)["hex"])
    return int.from_bytes(data, "little")


def frame(port: int) -> int:
    return game_session.query(port, "get_registers")["frame"]


def measure(port: int, unlocked: bool, vblanks: int) -> dict[str, Any]:
    original = bytes.fromhex(game_session.query(port, "read_ram", addr=VSYNC_ARG_ADDR, len=1)["hex"])[0]
    if original != VSYNC_ORIGINAL:
        raise RuntimeError(f"Byte at 0x{VSYNC_ARG_ADDR} is {original}, expected {VSYNC_ORIGINAL}; "
                           "the game is not in gameplay or the code changed")
    try:
        if unlocked:
            game_session.query(port, "write_ram", addr=VSYNC_ARG_ADDR, val="00")
        time.sleep(1)  # Let a loop iteration pass under the new argument.
        game_session.query(port, "wtrace_clear")
        game_session.query(port, "wtrace_range", lo=f"{YAW_LO:08x}", hi=f"{YAW_LO + 4:08x}")
        initial_yaw = read_yaw(port)
        start = frame(port)
        game_session.query(port, "set_input", buttons=0xFFFF ^ TURN_RIGHT)
        end = start
        deadline = time.monotonic() + max(10.0, vblanks / 20)
        while end - start < vblanks:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Frame counter stalled at {end} ({end - start} of {vblanks} VBlanks)")
            end = frame(port)
        game_session.query(port, "clear_input")
        dump = game_session.query(port, "wtrace_dump", frame_lo=start, frame_hi=end, count=2048)
        game_session.query(port, "wtrace_disarm_all")
        samples = [(int(e["frame"]), yaw) for e in dump["entries"]
                   if (yaw := yaw_from_entry(e)) is not None]
        if not samples:
            raise RuntimeError("No yaw writes traced; the player may not be controllable")
        return summarize(samples, start, end, initial_yaw)
    finally:
        # Best effort: the process is terminated next, so a dead server must not hide the real error.
        for command, arguments in (("clear_input", {}),
                                   ("write_ram", {"addr": VSYNC_ARG_ADDR, "val": f"{original:02x}"})):
            try:
                game_session.query(port, command, **arguments)
            except Exception as error:  # noqa: BLE001 - reported, not swallowed
                print(f"warning: cleanup {command} failed: {error}", file=sys.stderr)


def run_mode(mode: str, args: argparse.Namespace) -> dict[str, Any]:
    game_session.ensure_port_free(args.port)
    env, _ = game_session.clean_environment()
    with tempfile.TemporaryDirectory(prefix="framerate-") as tmp:
        out = Path(tmp)
        log_path = out / "runtime.log"
        command = game_session.launch_command(args.binary.resolve(), args.disc.resolve(), args.port, out)
        with log_path.open("w") as log:
            proc = subprocess.Popen(command, cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                game_session.wait_for_debug_server(proc, args.port, log_path)
                game_session.reach_gameplay(args.port)
                return measure(args.port, mode == "unlocked", args.vblanks)
            finally:
                game_session.terminate(proc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("original", "unlocked", "both"), default="both")
    parser.add_argument("--vblanks", type=int, default=81,
                        help="Guest VBlanks to hold turn-right (default 81, as in the doc, about 1.35 s at 60 Hz)")
    parser.add_argument("--binary", type=Path, default=game_session.DEFAULT_BINARY)
    parser.add_argument("--disc", type=Path, default=game_session.DEFAULT_DISC)
    parser.add_argument("--port", type=int, default=14384)
    parser.add_argument("--out", type=Path, help="Optional JSON results file")
    args = parser.parse_args()
    if args.vblanks < 1:
        parser.error("--vblanks must be positive")
    game_session.use_framework_debug_client()

    modes = ("original", "unlocked") if args.mode == "both" else (args.mode,)
    results = {mode: run_mode(mode, args) for mode in modes}
    labels = {"original": "Original VSync(3)", "unlocked": "Experimental VSync(0)"}
    print("| Mode | Observed VBlanks | Yaw updates | Update spacing | Yaw units / VBlank |")
    print("| --- | ---: | ---: | --- | ---: |")
    for mode, summary in results.items():
        print(f"| {labels[mode]} | {summary['vblanks']} | {summary['updates']} | "
              f"{format_spacing(summary)} | {summary['units_per_vblank']:.2f} |")
    for mode, summary in results.items():
        print(f"{mode} spacing histogram (VBlanks: count): {summary['spacing_histogram']}")
    print("Updates come from per-write frame numbers in the runtime write trace, not polling.")
    if args.out:
        args.out.write_text(json.dumps(results, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
