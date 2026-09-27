import difflib
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_source import apply_patch


class SourceAdapterTests(unittest.TestCase):
    def test_title_patches_apply_to_pinned_sources(self):
        for name in ("runtime-input", "runtime-graphics", "setup-host", "setup-ui"):
            with self.subTest(patch=name):
                text = (ROOT / "patches" / f"{name}.patch").read_text(encoding="utf-8")
                source = (ROOT / text.splitlines()[1].removeprefix("--- a/")).read_text(encoding="utf-8-sig")
                self.assertNotEqual(apply_patch(source, text), source)

    def test_patch_result_and_drift_rejection(self):
        source, expected = "first\nsecond\n", "first\nreplacement\n"
        patch = f"# source-sha256: {hashlib.sha256(source.encode()).hexdigest()}\n"
        patch += "".join(difflib.unified_diff(source.splitlines(True), expected.splitlines(True),
                                            fromfile="a/source", tofile="b/source"))
        self.assertEqual(apply_patch(source, patch), expected)
        with self.assertRaisesRegex(ValueError, "Upstream source changed"):
            apply_patch(source + "new upstream code\n", patch)
        with self.assertRaisesRegex(ValueError, "context does not match"):
            apply_patch(source, patch.replace("-second\n", "-wrong context\n"))


if __name__ == "__main__":
    unittest.main()
