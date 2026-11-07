import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import coverage_report as cr


def row(pc, insns, hits=1):
    return {"pc": f"0x{pc:08X}", "hits": hits, "insns": insns, "entries": 1,
            "occ_crc": "0x00000000", "occ_ok": 0, "ext_ra": "0x00000000"}


def capture(load_addr, pcs, payload=b"\x00" * 16):
    return {"load_addr": f"0x{load_addr:08X}", "size": len(payload),
            "bytes_b64": base64.b64encode(payload).decode(),
            "executed_pcs": [f"0x{pc:08X}" for pc in pcs],
            "dispatch_entry_pcs": [], "function_entry_pcs": [], "seeds": []}


def run_record(*interp):
    return {"phases": [{"label": f"s{i}", "after": {"phase_profile": {
        "interp_share": share, "static_share": 1 - share, "native_share": 0.0,
        "gpu_share": 0.0, "other_share": 0.0}}} for i, share in enumerate(interp)]}


class CaptureConfigTests(unittest.TestCase):
    def test_enables_capture_and_absolutizes_existing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "disc").mkdir()
            (root / "disc/game.cue").touch()
            source = root / "game.toml"
            source.write_text('[game]\ndisc = "disc/game.cue"\nexe = "disc/missing.exe"\n'
                              '[runtime]\nmemcard_dir = "saves"\n')
            text = cr.capture_config(source, root / "out.toml").read_text()
            self.assertIn(f'disc = "{(root / "disc/game.cue").resolve().as_posix()}"', text)
            self.assertIn('exe = "disc/missing.exe"', text)
            self.assertIn('[runtime]\noverlay_cache = true\nmemcard_dir = "saves"', text)

    def test_requires_runtime_table(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "game.toml"
            source.write_text("[game]\n")
            with self.assertRaisesRegex(ValueError, "no \\[runtime\\]"):
                cr.capture_config(source, Path(directory) / "out.toml")


class CollectorTests(unittest.TestCase):
    def test_keeps_rows_and_flushes_captures(self):
        calls = []

        def query(port, command, **arguments):
            calls.append(command)
            if command == "dirty_ram_stats":
                return {"insns_run": 17, "per_pc": [row(0x2818, 10), row(0x1ED6E4, 5)]}
            return {"capture_entries": 3}

        collector = cr.Collector(query)
        self.assertEqual(collector(1, "idle"), {"interpreted_pcs": 2, "capture_entries": 3})
        self.assertEqual(calls, ["dirty_ram_stats", "overlay_capture_dump"])
        self.assertEqual(set(collector.rows), {0x2818, 0x1ED6E4})
        self.assertFalse(collector.truncated)
        self.assertEqual(collector.insns_run, 17)

    def test_detects_truncated_table(self):
        rows = [row(0x10000 + 4 * i, 1) for i in range(2000)]
        collector = cr.Collector(lambda port, command, **a:
                                 {"insns_run": 2000, "per_pc": rows}
                                 if command == "dirty_ram_stats"
                                 else {"capture_entries": 0})
        collector(1, "idle")
        self.assertTrue(collector.truncated)

    def test_row_size_matches_runtime_format(self):
        expected = ('{"pc":"0x00002818","hits":1,"insns":10,"entries":1,'
                    '"occ_crc":"0x00000000","occ_ok":0,"ext_ra":"0x00000000"}')
        self.assertEqual(cr.per_pc_bytes([row(0x2818, 10)]), len(expected) + 1)


class ReportTests(unittest.TestCase):
    def test_merge_sums_runs_and_classifies_regions(self):
        merged = cr.merge_runs([{0x2818: row(0x2818, 10)},
                                {0x2818: row(0x2818, 5), 0x1ED6E4: row(0x1ED6E4, 20)}])
        self.assertEqual([(r["pc"], r["region"], r["insns"]) for r in merged],
                         [("0x801ED6E4", "game", 20), ("0x80002818", "kernel", 15)])
        self.assertEqual(cr.region_totals(merged), {"kernel": 15, "game": 20})

    def test_gate_on_share_and_truncation(self):
        report = cr.build_report([run_record(0.01, 0.2)], [{}], False, 0.05, 0)
        self.assertEqual(len(report["gate_failures"]), 1)
        self.assertIn("s1", report["gate_failures"][0])
        report = cr.build_report([run_record(0.01)], [{}], True, 0.05, 0)
        self.assertIn("truncated", report["gate_failures"][0])
        report = cr.build_report([run_record(0.01)], [{0x2818: row(0x2818, 3)}], False, 0.05, 3)
        self.assertEqual(report["gate_failures"], [])
        markdown = cr.render_markdown(report)
        self.assertIn("| 0x80002818 | kernel | 3 |", markdown)
        self.assertTrue(markdown.endswith("PASS\n"))

    def test_strict_fails_on_any_interpreted_instruction(self):
        rows = [{0x2818: row(0x2818, 3), 0x1ED6E4: row(0x1ED6E4, 7)}]
        report = cr.build_report([run_record(0.0)], rows, False, 0.05, 12, strict=True)
        self.assertEqual(report["gate_failures"], [
            "strict: 12 guest instruction(s) ran in the interpreter",
            "strict: 3 in kernel code, hottest at 0x80002818",
            "strict: 7 in game code, hottest at 0x801ED6E4"])
        report = cr.build_report([run_record(0.0)], [{}], False, 0.05, 4, strict=True)
        self.assertEqual(report["gate_failures"],
                         ["strict: 4 guest instruction(s) ran in the interpreter"])
        report = cr.build_report([run_record(0.0)], [{}], False, 0.05, 0, strict=True)
        self.assertEqual(report["gate_failures"], [])


class UpdateCaptureTests(unittest.TestCase):
    def test_merges_kernel_captures_only_and_keeps_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            committed = root / "captures/overlay_captures.json"
            committed.parent.mkdir()
            committed.write_text(json.dumps([capture(0x80002000, [0x80002818])]))
            run = root / "run.json"
            run.write_text(json.dumps([capture(0x80002000, [0x80002924]),
                                       capture(0x8000D000, [0x8000DFAC], b"\x01" * 16),
                                       capture(0x8000FFF0, [0x8000FFF0], b"\x02" * 32),
                                       capture(0x801EB000, [0x801ED6E4])]))
            summary = cr.update_captures([run, root / "absent.json"], committed, root / "vault")
            self.assertIn("+1 variant(s)", summary)
            records = json.loads(committed.read_text())
            self.assertEqual([r["load_addr"] for r in records], ["0x80002000", "0x8000D000"])
            self.assertEqual(records[0]["executed_pcs"], ["0x80002818", "0x80002924"])

    def test_no_captures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            committed = root / "captures/overlay_captures.json"
            self.assertEqual(cr.update_captures([], committed, root / "vault"),
                             "no captures recorded")
            self.assertFalse(committed.exists())


if __name__ == "__main__":
    unittest.main()
