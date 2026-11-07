#!/usr/bin/env python3
"""Measure how much guest code runs in the interpreter.

Boots a PSX_DEBUG_TOOLS runtime headless with runtime overlay compilation off,
plays the fixed first-room scenarios from measure_execution.py, and reports the
interpreter's share of wall time and every interpreted PC from the runtime's
dirty_ram_stats table. With --strict, any interpreted guest instruction since
boot fails the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any, Callable, Iterable

from dependencies import framework_root
import measure_execution

ROOT = Path(__file__).resolve().parents[1]
# Kernel RAM: OpenBIOS plus the stubs the game installs.
KERNEL_END = 0x10000
SHARE_KEYS = ("interp", "static", "native", "gpu", "other")
TOP_PCS = 20
# handle_dirty_ram_stats (debug_server.c) stops adding per_pc rows once its
# 64 KiB buffer is within 2 KiB of full. The fixed header is under 256 bytes.
PER_PC_ROW_LIMIT = 64 * 1024 - 2048 - 256

Query = Callable[..., dict[str, Any]]


class Collector:
    """After each scenario, keep the cumulative dirty_ram_stats rows."""

    def __init__(self, query: Query):
        self.query = query
        self.rows: dict[int, dict[str, Any]] = {}
        self.truncated = False
        self.insns_run = 0

    def __call__(self, port: int, label: str) -> dict[str, int]:
        stats = self.query(port, "dirty_ram_stats")
        rows = stats["per_pc"]
        # Global counter: also counts PCs the per_pc table could not track.
        self.insns_run = int(stats["insns_run"])
        self.truncated |= per_pc_bytes(rows) >= PER_PC_ROW_LIMIT
        for row in rows:
            self.rows[int(row["pc"], 16)] = row  # Counters are cumulative since boot.
        return {"interpreted_pcs": len(rows)}


def per_pc_bytes(rows: list[dict[str, Any]]) -> int:
    """Length of the per_pc array as the runtime formatted it."""
    return sum(len(
        f'{{"pc":"{r["pc"]}","hits":{r["hits"]},"insns":{r["insns"]},'
        f'"entries":{r["entries"]},"occ_crc":"{r["occ_crc"]}",'
        f'"occ_ok":{r["occ_ok"]},"ext_ra":"{r["ext_ra"]}"}}') + 1 for r in rows)


def region(phys: int) -> str:
    return "kernel" if phys < KERNEL_END else "game"


def merge_runs(runs: Iterable[dict[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum interpreted instructions per PC across runs, hottest first."""
    merged: dict[int, dict[str, Any]] = {}
    for rows in runs:
        for phys, row in rows.items():
            record = merged.setdefault(phys, {
                "pc": f"0x{0x80000000 | phys:08X}", "region": region(phys),
                "insns": 0, "hits": 0})
            record["insns"] += int(row["insns"])
            record["hits"] += int(row["hits"])
    return sorted(merged.values(), key=lambda r: (-r["insns"], r["pc"]))


def phase_shares(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases = []
    for index, run in enumerate(runs, 1):
        for phase in run["phases"]:
            profile = phase["after"]["phase_profile"]
            phases.append({"run": index, "label": phase["label"],
                           **{key: profile[f"{key}_share"] for key in SHARE_KEYS}})
    return phases


def region_totals(records: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"kernel": 0, "game": 0}
    for record in records:
        totals[record["region"]] += record["insns"]
    return totals


def use_framework_tools() -> None:
    tools = str(framework_root() / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)


def gate_failures(report: dict[str, Any], max_interp_share: float, *,
                  strict: bool = False) -> list[str]:
    failures = [f"run {p['run']} {p['label']}: interpreter share {p['interp']:.1%} "
                f"exceeds {max_interp_share:.1%}"
                for p in report["phases"] if p["interp"] > max_interp_share]
    if report["per_pc_possibly_truncated"]:
        failures.append("dirty_ram_stats truncated its per_pc table; "
                        "interpreted addresses may be missing")
    if strict:
        failures += strict_failures(report)
    return failures


def strict_failures(report: dict[str, Any]) -> list[str]:
    """Any interpreted instruction since boot, attributed to its hottest PC per region."""
    total = report["interpreted_instructions_total"]
    if total == 0:
        return []
    failures = [f"strict: {total} guest instruction(s) ran in the interpreter"]
    for name, count in report["interpreted_instructions"].items():
        hottest = next((r["pc"] for r in report["interpreted_pcs"] if r["region"] == name), None)
        if count:
            failures.append(f"strict: {count} in {name} code, hottest at {hottest}")
    return failures


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Execution coverage", "",
             "| Run | Scenario | Interpreter | Static native | Native overlays | GPU | Other |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for p in report["phases"]:
        lines.append(f"| {p['run']} | {p['label']} | " +
                     " | ".join(f"{p[key]:.1%}" for key in SHARE_KEYS) + " |")
    totals = report["interpreted_instructions"]
    lines += ["", "Shares are sampled wall time. Interpreted instructions since boot: "
              f"{report['interpreted_instructions_total']} total; per PC " +
              ", ".join(f"{name} {count}" for name, count in totals.items()) + ".", ""]
    hottest = report["interpreted_pcs"][:TOP_PCS]
    if hottest:
        lines += ["| PC | Region | Instructions |", "| --- | --- | --- |"]
        lines += [f"| {r['pc']} | {r['region']} | {r['insns']} |" for r in hottest]
        lines.append("")
    lines += ["## Result", ""]
    lines += [f"- FAIL: {f}" for f in report["gate_failures"]] or ["PASS"]
    return "\n".join(lines) + "\n"


def build_report(runs: list[dict[str, Any]], rows: list[dict[int, dict[str, Any]]],
                 truncated: bool, max_interp_share: float, insns_run: int, *,
                 strict: bool = False) -> dict[str, Any]:
    records = merge_runs(rows)
    report: dict[str, Any] = {
        "phases": phase_shares(runs),
        "interpreted_instructions_total": insns_run,
        "interpreted_instructions": region_totals(records),
        "per_pc_possibly_truncated": truncated,
        "interpreted_pcs": records,
    }
    report["gate_failures"] = gate_failures(report, max_interp_share, strict=strict)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--window", type=int, default=5, help="Whole seconds per scenario, 1-60")
    parser.add_argument("--port", type=int, default=14381)
    parser.add_argument("--binary", type=Path,
                        default=ROOT / "build-debug/Shadow_Tower_Recompiled",
                        help="Runtime built with -DPSX_DEBUG_TOOLS=ON")
    parser.add_argument("--disc", type=Path, default=measure_execution.DEFAULT_DISC)
    parser.add_argument("--max-interp-share", type=float, default=0.05,
                        help="Fail if any scenario exceeds this interpreter share")
    parser.add_argument("--strict", action="store_true",
                        help="Fail on any interpreted guest instruction since boot")
    args = parser.parse_args()
    if args.runs < 1 or not 1 <= args.window <= 60 or not 0 < args.max_interp_share <= 1:
        parser.error("runs must be positive, window 1-60, max-interp-share in (0, 1]")
    for path in (args.binary, args.disc):
        if not path.is_file():
            parser.error(f"missing {path}")

    use_framework_tools()
    with socket.socket() as listener:  # Fail early if another process owns the port.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", args.port))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    binary = args.binary.resolve()
    runs, rows, truncated, insns_run = [], [], False, 0
    for index in range(args.runs):
        run_dir = out / f"run-{index + 1}"
        collector = Collector(measure_execution.query)
        runs.append(measure_execution.run_trial(
            run_dir, args.port, args.window, "software", binary, False,
            args.disc.resolve(), collector,
            env_overrides={"PSX_OVERLAY_AUTOCOMPILE_OFF": "1"}))
        rows.append(collector.rows)
        truncated |= collector.truncated
        insns_run += collector.insns_run

    report = build_report(runs, rows, truncated, args.max_interp_share, insns_run,
                          strict=args.strict)
    report["metadata"] = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                              cwd=ROOT, text=True).strip(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "runs": args.runs, "window_s": args.window,
        "max_interp_share": args.max_interp_share, "strict": args.strict,
    }
    (out / "coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    (out / "coverage.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 1 if report["gate_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
