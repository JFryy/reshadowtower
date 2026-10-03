import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from generate_aot import find_recompiler


class RecompilerDiscoveryTests(unittest.TestCase):
    def test_local_and_packaged_emitters_on_both_platforms(self):
        for directory in ("build-recompiler", "psxrecomp/recompiler/build"):
            for windows in (False, True):
                with self.subTest(directory=directory, windows=windows), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    emitter = root / directory / ("psxrecomp-game.exe" if windows else "psxrecomp-game")
                    emitter.parent.mkdir(parents=True)
                    emitter.touch()
                    self.assertEqual(find_recompiler(root, windows=windows), emitter)

    def test_resolved_framework_emitter(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary).resolve()
            root = temporary_root / "project"
            framework = temporary_root / "framework"
            name = "psxrecomp-game.exe" if os.name == "nt" else "psxrecomp-game"
            emitter = framework / "recompiler/build" / name
            emitter.parent.mkdir(parents=True)
            emitter.touch()
            self.assertEqual(find_recompiler(root, framework=framework), emitter)

    def test_missing_emitter_reports_expected_path(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory).resolve() / "build-recompiler/psxrecomp-game.exe"
            with self.assertRaisesRegex(FileNotFoundError, "missing emitter") as raised:
                find_recompiler(Path(directory).resolve(), windows=True)
            self.assertIn(str(expected), str(raised.exception))


if __name__ == "__main__":
    unittest.main()
