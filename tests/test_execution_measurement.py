import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "measure_execution.py"
SPEC = importlib.util.spec_from_file_location("measure_execution", MODULE_PATH)
measurement = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(measurement)


class SummarizeTests(unittest.TestCase):
    def snapshots(self):
        before = {
            "frame_after": 100,
            "frame_before": 101,
            "angles": "before",
            "dirty_ram_stats": {"insns_run": 1000, "blocks_run": 200, "aborts": 7, "native_handoffs": 30},
            "dispatch_stats": {"static_hits": 400, "miss_total": 20},
            "fn_stats": {"direct_seen": 50, "direct_filtered": 4},
            "overlay_loader_status": {"dispatch_native": 8, "loads": 2},
            "phase_profile": {"interp_share": 0.5},
        }
        after = {
            "frame_before": 112,
            "frame_after": 113,
            "angles": "after",
            "dirty_ram_stats": {"insns_run": 1312, "blocks_run": 248, "aborts": 9, "native_handoffs": 37},
            "dispatch_stats": {"static_hits": 460, "miss_total": 23},
            "fn_stats": {"direct_seen": 62, "direct_filtered": 5},
            "overlay_loader_status": {"dispatch_native": 11, "loads": 3},
            "phase_profile": {"interp_share": 0.25},
        }
        return before, after

    def test_exact_deltas_and_approximate_frame_rate(self):
        before, after = self.snapshots()
        result = measurement.summarize(before, after)

        self.assertEqual(result["guest_vblanks_approx"], 12)
        self.assertAlmostEqual(result["interpreted_instructions_per_vblank_approx"], 26.0)
        self.assertEqual(result["counter_deltas"], {
            "dirty_ram_stats.insns_run": 312,
            "dirty_ram_stats.blocks_run": 48,
            "dirty_ram_stats.aborts": 2,
            "dirty_ram_stats.native_handoffs": 7,
            "dispatch_stats.static_hits": 60,
            "dispatch_stats.miss_total": 3,
            "fn_stats.direct_seen": 12,
            "fn_stats.direct_filtered": 1,
            "overlay_loader_status.dispatch_native": 3,
            "overlay_loader_status.loads": 1,
        })
        self.assertNotIn("native_percentage", result)
        self.assertNotIn("instruction_percentage", result)

    def test_nonpositive_frames_are_rejected(self):
        before, after = self.snapshots()
        after["frame_before"] = before["frame_after"]
        with self.assertRaisesRegex(RuntimeError, "Guest frames did not advance"):
            measurement.summarize(before, after)

    def test_counter_reset_is_rejected(self):
        before, after = self.snapshots()
        after["dispatch_stats"]["miss_total"] = before["dispatch_stats"]["miss_total"] - 1
        with self.assertRaisesRegex(RuntimeError, "Counter reset: dispatch_stats.miss_total"):
            measurement.summarize(before, after)


if __name__ == "__main__":
    unittest.main()
