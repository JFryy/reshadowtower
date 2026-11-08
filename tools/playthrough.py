#!/usr/bin/env python3
"""Seeded headless playthrough that looks for crashes and hangs.

Needs the disc and a debug-enabled build, so it is a local tool. The same seed
produces the same input plan; timing of the host still varies between runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_session  # noqa: E402

SELECT, UP, RIGHT, DOWN, LEFT = 0x0001, 0x0010, 0x0020, 0x0040, 0x0080
L1, R1, TRIANGLE, CIRCLE, CROSS = 0x0400, 0x0800, 0x1000, 0x2000, 0x4000
DIRECTIONS = (UP, RIGHT, DOWN, LEFT)
VALID_MASKS = frozenset({SELECT, CIRCLE, CROSS, TRIANGLE, L1, R1, *DIRECTIONS})
SAMPLE_INTERVAL = 1.0
TAP_SECONDS = 0.15


class InputEvent(NamedTuple):
    start: float    # seconds after gameplay was reached
    hold: float     # seconds the buttons stay down
    buttons: int    # OR of pad bits, all within VALID_MASKS


def input_plan(seed: int, duration: float) -> list[InputEvent]:
    """Deterministic, non-overlapping input events covering `duration` seconds."""
    rng = random.Random(seed)
    events: list[InputEvent] = []
    t = 0.0
    while t < duration:
        roll = rng.random()
        if roll < 0.45:
            mask = rng.choice(DIRECTIONS)
            if rng.random() < 0.3:
                mask |= rng.choice((L1, R1))
            hold = rng.uniform(0.3, 2.5)
            events.append(InputEvent(t, hold, mask))
        elif roll < 0.65:
            hold = rng.uniform(0.1, 0.4)
            events.append(InputEvent(t, hold, TRIANGLE))
        elif roll < 0.8:
            hold = rng.uniform(0.1, 0.3)
            events.append(InputEvent(t, hold, CROSS))
        elif roll < 0.9:
            hold = rng.uniform(0.1, 0.3)
            events.append(InputEvent(t, hold, CIRCLE))
        elif roll < 0.95:
            hold = rng.uniform(0.1, 0.3)
            events.append(InputEvent(t, hold, SELECT))
            # Menu open: close it with Circle after a short look.
            close_at = t + hold + rng.uniform(0.8, 1.5)
            events.append(InputEvent(close_at, TAP_SECONDS, CIRCLE))
            hold = close_at - t + TAP_SECONDS
        else:
            hold = 0.0  # Idle gap.
        t += hold + rng.uniform(0.05, 0.5)
    return events


def detect_hang(samples: Sequence[tuple[float, int]], hang_seconds: float) -> float | None:
    """Return how long the frame counter has been stuck if >= hang_seconds, else None.

    `samples` are (time, frame) in time order. The stall starts at the first
    sample carrying the latest frame value.
    """
    if len(samples) < 2:
        return None
    last_time, last_frame = samples[-1]
    stall_start = last_time
    for sample_time, frame in reversed(samples):
        if frame != last_frame:
            break
        stall_start = sample_time
    stalled = last_time - stall_start
    return stalled if stalled >= hang_seconds else None


def tail(path: Path, lines: int = 60) -> str:
    return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])


def fail(out: Path, kind: str, message: str, seed: int, port: int, proc: subprocess.Popen[Any],
         samples: list[tuple[float, int]], sent: list[dict[str, Any]], log: Path) -> str:
    screenshot: str | None = None
    if proc.poll() is None:
        try:
            game_session.query(port, "screenshot_file", path=str(out / "failure.png"))
            screenshot = "failure.png"
        except Exception as error:  # Hung server often cannot answer; record why.
            screenshot = f"unavailable: {error}"
    report = {"kind": kind, "message": message, "seed": seed, "screenshot": screenshot,
              "exit_code": proc.poll(), "last_inputs": sent[-20:],
              "frame_samples": samples[-60:], "runtime_log_tail": tail(log)}
    (out / "failure.json").write_text(json.dumps(report, indent=2) + "\n")
    return (f"{kind.upper()}: {message} (seed {seed}). Reproduce with: "
            f"python3 tools/playthrough.py --seed {seed}. Details in {out / 'failure.json'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--duration", type=float, default=300, help="Seconds of gameplay input")
    parser.add_argument("--binary", type=Path, default=game_session.DEFAULT_BINARY)
    parser.add_argument("--disc", type=Path, default=game_session.DEFAULT_DISC)
    parser.add_argument("--port", type=int, default=14383)
    parser.add_argument("--out", type=Path, required=True, help="New directory")
    parser.add_argument("--hang-seconds", type=float, default=10)
    args = parser.parse_args()
    if args.duration <= 0 or args.hang_seconds <= 0:
        parser.error("duration and hang-seconds must be positive")
    game_session.use_framework_debug_client()

    game_session.ensure_port_free(args.port)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    log_path = out / "runtime.log"
    env, _ = game_session.clean_environment()
    command = game_session.launch_command(args.binary.resolve(), args.disc.resolve(), args.port, out)
    plan = input_plan(args.seed, args.duration)
    (out / "launch.json").write_text(json.dumps({"command": command, "seed": args.seed,
                                                 "events": len(plan)}, indent=2) + "\n")
    samples: list[tuple[float, int]] = []
    sent: list[dict[str, Any]] = []
    with log_path.open("w") as log:
        proc = subprocess.Popen(command, cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
        failure: str | None = None
        try:
            game_session.wait_for_debug_server(proc, args.port, log_path)
            game_session.reach_gameplay(args.port)
            start = time.monotonic()
            first_frame = game_session.query(args.port, "get_registers")["frame"]
            next_sample = 0.0
            clear_at: float | None = None
            index = 0
            while True:
                now = time.monotonic() - start
                if proc.poll() is not None:
                    failure = fail(out, "crash", f"runtime exited with code {proc.returncode}",
                                   args.seed, args.port, proc, samples, sent, log_path)
                    break
                if now >= args.duration and clear_at is None:
                    break
                try:
                    if clear_at is not None and now >= clear_at:
                        game_session.query(args.port, "clear_input")
                        clear_at = None
                    if clear_at is None and index < len(plan) and now >= plan[index].start:
                        event = plan[index]
                        index += 1
                        game_session.query(args.port, "set_input", buttons=0xFFFF ^ event.buttons)
                        sent.append({"t": round(now, 3), "buttons": event.buttons, "hold": round(event.hold, 3)})
                        clear_at = now + event.hold
                    if now >= next_sample:
                        next_sample = now + SAMPLE_INTERVAL
                        samples.append((round(now, 3), game_session.query(args.port, "get_registers")["frame"]))
                except (OSError, RuntimeError) as error:
                    if proc.poll() is not None:
                        continue  # Reported as a crash on the next iteration.
                    failure = fail(out, "hang", f"debug server stopped answering: {error}",
                                   args.seed, args.port, proc, samples, sent, log_path)
                    break
                stalled = detect_hang(samples, args.hang_seconds)
                if stalled is not None:
                    failure = fail(out, "hang", f"frame counter stuck for {stalled:.1f}s at frame {samples[-1][1]}",
                                   args.seed, args.port, proc, samples, sent, log_path)
                    break
                time.sleep(0.02)
            if failure is None:
                game_session.query(args.port, "clear_input")
                summary = {"seed": args.seed, "duration": args.duration,
                           "frames_advanced": samples[-1][1] - first_frame if samples else 0,
                           "inputs_sent": len(sent)}
                (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
                print(f"OK: {json.dumps(summary)}")
        except (OSError, RuntimeError, TimeoutError) as error:
            failure = fail(out, "crash" if proc.poll() is not None else "hang",
                           f"{type(error).__name__}: {error}", args.seed, args.port, proc,
                           samples, sent, log_path)
        finally:
            game_session.terminate(proc)
    if failure is not None:
        print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
