import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from dependencies import framework_root
from prepare_source import apply_patch


class MemcardTests(unittest.TestCase):
    def test_saves_are_atomic_backed_up_and_damaged_cards_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = (framework_root() / "runtime/src/memcard.c").read_text(encoding="utf-8-sig")
            patch = (ROOT / "patches/runtime-memcard.patch").read_text(encoding="utf-8")
            (path / "memcard.c").write_text(apply_patch(source, patch), encoding="utf-8")
            executable = path / "memcard"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", directory,
                            "-I", str(framework_root() / "runtime/include"), str(ROOT / "tests/memcard_test.c"),
                            "-o", str(executable)], check=True)
            saves = path / "saves"
            saves.mkdir()
            result = subprocess.run([str(executable), str(saves)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr.count("save to card 1 failed"), 1)
            self.assertEqual(result.stderr.count("cannot create"), 1)
            self.assertIn("save to card 1 succeeded after earlier failures", result.stderr)
            damaged = list(saves.glob("card2.mcd.damaged-*"))
            self.assertEqual(len(damaged), 1, result.stderr)
            self.assertEqual(damaged[0].read_bytes(), b"truncated")
            self.assertIn("card2.mcd is damaged", result.stderr)
            self.assertEqual(sorted(p.name for p in saves.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
