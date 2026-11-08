import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FunctionOverrideTests(unittest.TestCase):
    def test_registry_and_differential_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for header in ("cpu_state.h", "mod_plugins.h"):
                (path / header).touch()
            executable = path / "overrides"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", directory,
                            "-I", str(ROOT / "src"), str(ROOT / "tests/function_overrides_test.c"),
                            "-o", str(executable)], check=True)
            for check in ("0", "1", "maybe"):
                with self.subTest(check=check):
                    result = subprocess.run([str(executable)], capture_output=True, text=True,
                                            env={**os.environ, "SHADOWTOWER_OVERRIDE_CHECK": check})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if check == "1":
                        self.assertIn("override wrong (0x80004000) differs from generated code", result.stderr)
                        self.assertIn("r2: generated 0x00000005, override 0x00000007", result.stderr)
                        self.assertIn("RAM 0x80000100", result.stderr)
                        self.assertNotIn("0x801FFE", result.stderr)
                        self.assertIn("override check add: 3 matched, 0 differed, 0 skipped", result.stderr)
                        self.assertEqual(result.stderr.count("r2: generated 0x00000005, override 0x00000007"), 1)
                        self.assertIn("override check wrong: 0 matched, 2 differed, 2 skipped", result.stderr)
                        self.assertIn("override check guest: 1 matched, 0 differed, 1 skipped", result.stderr)
                    if check == "maybe":
                        self.assertIn("invalid SHADOWTOWER_OVERRIDE_CHECK 'maybe'", result.stderr)


if __name__ == "__main__":
    unittest.main()
