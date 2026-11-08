import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("measure_framerate", TOOLS / "measure_framerate.py")
framerate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(framerate)


def turning_samples(frames, total_units, initial=100):
    """Spread total_units of yaw movement evenly (remainder up front) over the writes."""
    base, extra = divmod(total_units, len(frames))
    samples, yaw = [], initial
    for index, frame in enumerate(frames):
        yaw = (yaw + base + (1 if index < extra else 0)) % 4096
        samples.append((frame, yaw))
    return samples


class SummarizeTests(unittest.TestCase):
    def test_original_cadence_matches_doc(self):
        frames = [1000 + 3 * i for i in range(27)]
        samples = turning_samples(frames, 980)
        result = framerate.summarize(samples, 1000, 1081, 100)
        self.assertEqual(result["vblanks"], 81)
        self.assertEqual(result["updates"], 27)
        self.assertEqual(result["spacing_histogram"], {"3": 26})
        self.assertEqual((result["spacing_min"], result["spacing_max"]), (3, 3))
        self.assertEqual(f"{result['units_per_vblank']:.2f}", "12.10")
        self.assertEqual(framerate.format_spacing(result), "3 VBlanks")

    def test_unlocked_cadence_matches_doc(self):
        gaps = [1, 2] * 15 + [1]
        frames = [2000]
        for gap in gaps:
            frames.append(frames[-1] + gap)
        samples = turning_samples(frames[:32], 1180)
        result = framerate.summarize(samples, 2000, 2060, 100)
        self.assertEqual(result["vblanks"], 60)
        self.assertEqual(result["updates"], 32)
        self.assertEqual(set(result["spacing_histogram"]), {"1", "2"})
        self.assertEqual(f"{result['units_per_vblank']:.2f}", "19.67")
        self.assertEqual(framerate.format_spacing(result), "1-2 VBlanks")

    def test_yaw_wraps_at_modulus(self):
        result = framerate.summarize([(10, 5)], 0, 10, 4090)
        self.assertEqual(result["yaw_units"], 11)

    def test_no_updates(self):
        result = framerate.summarize([], 0, 60, 7)
        self.assertEqual(result["updates"], 0)
        self.assertIsNone(result["spacing_min"])
        self.assertEqual(result["units_per_vblank"], 0)
        self.assertEqual(framerate.format_spacing(result), "n/a")

    def test_rejects_empty_window(self):
        with self.assertRaises(ValueError):
            framerate.summarize([], 10, 10, 0)


class TraceEntryTests(unittest.TestCase):
    def test_halfword_and_word_writes(self):
        self.assertEqual(framerate.yaw_from_entry({"addr": "0x001991A2", "w": 2, "new": "0x0000ABCD"}), 0xABCD)
        self.assertEqual(framerate.yaw_from_entry({"addr": "0x001991A0", "w": 4, "new": "0x1234FFFF"}), 0x1234)
        self.assertIsNone(framerate.yaw_from_entry({"addr": "0x001991A0", "w": 2, "new": "0x1"}))


if __name__ == "__main__":
    unittest.main()
