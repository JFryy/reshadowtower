import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("playthrough", TOOLS / "playthrough.py")
playthrough = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(playthrough)


class InputPlanTests(unittest.TestCase):
    def test_same_seed_is_identical(self):
        self.assertEqual(playthrough.input_plan(7, 120), playthrough.input_plan(7, 120))

    def test_different_seed_differs(self):
        self.assertNotEqual(playthrough.input_plan(1, 120), playthrough.input_plan(2, 120))

    def test_only_valid_buttons(self):
        allowed = playthrough.VALID_MASKS
        for seed in range(20):
            for event in playthrough.input_plan(seed, 120):
                remaining = event.buttons
                for bit in range(16):
                    mask = 1 << bit
                    if remaining & mask:
                        self.assertIn(mask, allowed)
                self.assertGreater(event.hold, 0)

    def test_events_ordered_without_overlap_and_cover_duration(self):
        plan = playthrough.input_plan(3, 60)
        for earlier, later in zip(plan, plan[1:]):
            self.assertGreaterEqual(later.start, earlier.start + earlier.hold)
        self.assertGreater(plan[-1].start, 50)
        self.assertTrue(all(event.start < 60 for event in plan))

    def test_includes_menu_open_and_close(self):
        menus = 0
        for seed in range(10):
            plan = playthrough.input_plan(seed, 300)
            for index, event in enumerate(plan):
                if event.buttons != playthrough.SELECT:
                    continue
                menus += 1
                self.assertLess(index + 1, len(plan), "menu opened at the end without a close")
                self.assertEqual(plan[index + 1].buttons, playthrough.CIRCLE)
        self.assertGreater(menus, 0)


class DetectHangTests(unittest.TestCase):
    def test_too_few_samples(self):
        self.assertIsNone(playthrough.detect_hang([], 10))
        self.assertIsNone(playthrough.detect_hang([(0, 5)], 10))

    def test_advancing_frames(self):
        samples = [(float(i), 60 * i) for i in range(30)]
        self.assertIsNone(playthrough.detect_hang(samples, 10))

    def test_stuck_below_threshold(self):
        samples = [(0.0, 1), (1.0, 2)] + [(float(t), 3) for t in range(2, 11)]
        self.assertIsNone(playthrough.detect_hang(samples, 10))

    def test_stuck_at_threshold(self):
        samples = [(0.0, 1), (1.0, 2)] + [(float(t), 3) for t in range(2, 13)]
        self.assertEqual(playthrough.detect_hang(samples, 10), 10.0)

    def test_stall_that_recovered_is_not_a_hang(self):
        samples = [(float(t), 3) for t in range(0, 15)] + [(15.0, 99)]
        self.assertIsNone(playthrough.detect_hang(samples, 10))

    def test_stuck_from_first_sample(self):
        samples = [(float(t), 7) for t in range(0, 12)]
        self.assertEqual(playthrough.detect_hang(samples, 10), 11.0)


if __name__ == "__main__":
    unittest.main()
