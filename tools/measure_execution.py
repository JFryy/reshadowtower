#!/usr/bin/env python3
"""Measure execution tiers through existing diagnostics, using disposable saves."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "psxrecomp/tools"))
import debug_client  # noqa: E402


def query(port: int, command: str, **arguments: Any) -> dict[str, Any]:
    result = debug_client.query("127.0.0.1", port, {"id": 1, "cmd": command, **arguments})
    if not result.get("ok"):
        raise RuntimeError(f"{command} failed: {result}")
    return result


def snapshot(port: int, window: int) -> dict[str, Any]:
    """Collect cumulative counters and a whole-second statistical window."""
    result: dict[str, Any] = {"host_monotonic": time.monotonic()}
    result["frame_before"] = query(port, "get_registers")["frame"]
    for command in ("dirty_ram_stats", "dispatch_stats", "fn_stats",
                    "overlay_loader_status", "autocompile_status"):
        result[command] = query(port, command)
    result["phase_profile"] = query(port, "phase_profile", window=window)
    result["static_hot"] = query(port, "phase_hot", set="static", top=64)
    result["native_hot"] = query(port, "phase_hot", top=64)
    result["angles"] = query(port, "read_ram", addr="801991a0", len=4)["hex"]
    result["frame_after"] = query(port, "get_registers")["frame"]
    return result


def summarize(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Keep instruction counts, entry counts, and wall-time samples separate."""
    frames = after["frame_before"] - before["frame_after"]
    if frames <= 0:
        raise RuntimeError("Guest frames did not advance during measurement")
    delta: dict[str, int] = {}
    for command, fields in {
        "dirty_ram_stats": ("insns_run", "blocks_run", "aborts", "native_handoffs"),
        "dispatch_stats": ("static_hits", "miss_total"),
        "fn_stats": ("direct_seen", "direct_filtered"),
        "overlay_loader_status": ("dispatch_native", "loads"),
    }.items():
        for field in fields:
            value = after[command][field] - before[command][field]
            if value < 0:
                raise RuntimeError(f"Counter reset: {command}.{field}")
            delta[f"{command}.{field}"] = value
    overlay_fields = ("static_checks", "static_hits", "static_variant_misses",
                      "static_address_misses")
    for field in overlay_fields:
        if (field in before["overlay_loader_status"] and
                field in after["overlay_loader_status"]):
            value = (after["overlay_loader_status"][field] -
                     before["overlay_loader_status"][field])
            if value < 0:
                raise RuntimeError(f"Counter reset: overlay_loader_status.{field}")
            delta[f"overlay_loader_status.{field}"] = value
    return {
        "guest_vblanks_approx": frames,
        "counter_deltas": delta,
        "interpreted_instructions_per_vblank_approx": delta["dirty_ram_stats.insns_run"] / frames,
        "wall_time_samples": after["phase_profile"],
        "angles_before": before["angles"],
        "angles_after": after["angles"],
    }


def press(port: int, button: int) -> None:
    query(port, "set_input", buttons=0xFFFF ^ button)
    time.sleep(0.15)
    query(port, "clear_input")
    time.sleep(0.6)


def run_trial(out: Path, port: int, window: int, renderer: str, binary: Path,
              trace_boot: bool) -> dict[str, Any]:
    """Run one cold boot and a fixed sequence of first-room input scenarios."""
    out.mkdir(parents=True, exist_ok=False)
    # Prevent external diagnostic/performance overrides from contaminating a trial.
    removed = {k: v for k, v in os.environ.items() if k.startswith(("PSX_", "SHADOWTOWER_"))}
    env = {k: v for k, v in os.environ.items() if k not in removed}
    if trace_boot:
        # Count generated boot-loader prologues only, not interpreted entries or BIOS.
        env["PSX_FN_FILTER"] = "0x80010000:0x80010800"
    command = [str(binary),
               "--game", str(ROOT / "game.toml"),
               "--disc", str(ROOT / "disc/Shadow Tower (USA).cue"),
               "--no-launcher", "--renderer", renderer,
               "--debug-port", str(port), "--memcard-dir", str(out / "saves")]
    if renderer == "software":
        command.append("--headless")
    record: dict[str, Any] = {"command": command, "removed_overrides": removed,
                              "trace_boot": trace_boot, "phases": []}
    (out / "launch.json").write_text(json.dumps(record, indent=2) + "\n")
    with (out / "runtime.log").open("w") as log:
        proc = subprocess.Popen(command, cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"Runtime exited {proc.returncode}; see {out / 'runtime.log'}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Debug server unavailable; see {out / 'runtime.log'}")
                    time.sleep(0.1)
            record["boot_snapshot"] = snapshot(port, window)

            def measure(label: str, held: int = 0) -> None:
                query(port, "set_input", buttons=0xFFFF ^ held)
                before = snapshot(port, window)
                # The sampler excludes the current partial second. This margin
                # ensures its entire reported window is inside this scenario.
                time.sleep(window + 2)
                after = snapshot(port, window)
                query(port, "clear_input")
                image = out / f"{label}.png"
                query(port, "screenshot_file", path=str(image))
                phase = {"label": label, "held_buttons": held, "before": before,
                         "after": after, "summary": summarize(before, after)}
                record["phases"].append(phase)
                (out / "results.json").write_text(json.dumps(record, indent=2) + "\n")
                stats = after["phase_profile"]
                print(f"{out.name}/{label}: interp={stats['interp_share']:.1%}, "
                      f"static={stats['static_share']:.1%}, overlays={stats['native_share']:.1%}, "
                      f"gpu={stats['gpu_share']:.1%}", flush=True)

            measure("opening")
            for _ in range(20):
                signature = query(port, "read_ram", addr="80041d4c", len=8)["hex"]
                if signature == "e8ffbd271d80023c":
                    break
                press(port, 0x0008)  # Start: skip intro / title transitions.
                time.sleep(0.5)
            else:
                raise RuntimeError("Gameplay executable not reached after 20 Start presses")
            time.sleep(4)  # The executable becomes resident before loading finishes.
            record["gameplay_signature"] = query(port, "read_ram", addr="80041d4c", len=8)
            measure("idle")
            measure("turn_right", 0x0020)
            if record["phases"][-1]["summary"]["angles_before"] == record["phases"][-1]["summary"]["angles_after"]:
                raise RuntimeError("Turning did not change player angles; inspect screenshots")
            measure("attack_input", 0x1000)
            press(port, 0x0001)  # Select: main menu.
            measure("main_menu")
            press(port, 0x2000)  # Circle: close main menu.
            time.sleep(1)
            press(port, 0x2000)  # Circle: open inventory.
            measure("inventory_input")
            press(port, 0x2000)
            time.sleep(1)
            measure("idle_return")
            record["boot_entries"] = query(port, "fn_entry_dump", count=128)
        finally:
            # SIGTERM is handled by the runtime. Never touch another instance.
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    record["forced_kill"] = True
            record["exit_code"] = proc.returncode
            (out / "results.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New directory, preferably under analysis/")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--window", type=int, default=10, help="Whole seconds per phase, 1–60")
    parser.add_argument("--port", type=int, default=14381)
    parser.add_argument("--renderer", choices=("software", "opengl"), default="software",
                        help="Software runs headless; OpenGL opens a normal game window")
    parser.add_argument("--binary", type=Path,
                        default=ROOT / "build-release/Shadow_Tower_Recompiled")
    parser.add_argument("--trace-boot", action="store_true",
                        help="Enable boot function entry tracing")
    args = parser.parse_args()
    if args.runs < 1 or not 1 <= args.window <= 60:
        parser.error("runs must be positive and window must be 1–60")
    # Fail before launching if the port belongs to an existing process.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", args.port))
    out = args.out.resolve()
    binary = args.binary.resolve()
    out.mkdir(parents=True, exist_ok=False)
    metadata = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "framework_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT / "psxrecomp", text=True).strip(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "game_toml": (ROOT / "game.toml").read_text(),
        "renderer": args.renderer, "window": args.window, "trace_boot": args.trace_boot,
        "sampling_note": "Tagged wall-time samples, NOT guest-instruction percentages; snapshots are not atomic.",
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    runs = [run_trial(out / f"run-{i + 1}", args.port, args.window, args.renderer,
                      binary, args.trace_boot) for i in range(args.runs)]
    summary = [[{"label": p["label"], **p["summary"]} for p in run["phases"]] for run in runs]
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
