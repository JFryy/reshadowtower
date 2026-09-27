import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModernControlsTests(unittest.TestCase):
    def test_input_and_camera_behavior(self):
        flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "sdl3"], text=True))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for header in ("mod_plugins.h", "psx_keybinds.h"):
                (path / header).touch()
            executable = path / "controls"
            subprocess.run(["cc", "-std=c11", *flags, "-I", directory, "-I", str(ROOT / "src"),
                            "-I", str(ROOT / "psxrecomp/runtime/include"),
                            str(ROOT / "tests/modern_controls_test.c"), "-lm", "-o", str(executable)], check=True)
            for sensitivity in ("invalid", "2"):
                with self.subTest(sensitivity=sensitivity):
                    result = subprocess.run([str(executable)], capture_output=True, text=True,
                                            env={**os.environ, "SHADOWTOWER_MOUSE_SENSITIVITY": sensitivity})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if sensitivity == "invalid":
                        self.assertIn("invalid SHADOWTOWER_MOUSE_SENSITIVITY", result.stderr)


if __name__ == "__main__":
    unittest.main()
