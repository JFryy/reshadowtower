from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import coverage_report as cr


def row(pc, insns, hits=1):
    return {"pc": f"0x{pc:08X}", "hits": hits, "insns": insns, "entries": 1,
            "occ_crc": "0x00000000", "occ_ok": 0, "ext_ra": "0x00000000"}


def run_record(*interp):
    return {"phases": [{"label": f"s{i}", "after": {"phase_profile": {
        "interp_share": share, "static_share": 1 - share, "native_share": 0.0,
        "gpu_share": 0.0, "other_share": 0.0}}} for i, share in enumerate(interp)]}


class CollectorTests(unittest.TestCase):
    def test_keeps_rows_and_global_count(self):
        calls = []

        def query(port, command, **arguments):
            calls.append(command)
            if command == "dirty_ram_stats":
                return {"insns_run": 17, "per_pc": [row(0x2818, 10), row(0x1ED6E4, 5)]}
            raise AssertionError(command)

        collector = cr.Collector(query)
        self.assertEqual(collector(1, "idle"), {"interpreted_pcs": 2})
        self.assertEqual(calls, ["dirty_ram_stats"])
        self.assertEqual(set(collector.rows), {0x2818, 0x1ED6E4})
        self.assertFalse(collector.truncated)
        self.assertEqual(collector.insns_run, 17)

    def test_detects_truncated_table(self):
        rows = [row(0x10000 + 4 * i, 1) for i in range(2000)]
        collector = cr.Collector(lambda port, command, **a:
                                 {"insns_run": 2000, "per_pc": rows})
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


if __name__ == "__main__":
    unittest.main()
