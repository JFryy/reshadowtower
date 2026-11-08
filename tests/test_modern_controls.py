import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from dependencies import framework_root


class ModernControlsTests(unittest.TestCase):
    def test_input_and_camera_behavior(self):
        flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "sdl3"], text=True))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for header in ("mod_plugins.h", "psx_keybinds.h"):
                (path / header).touch()
            executable = path / "controls"
            subprocess.run(["cc", "-std=c11", *flags, "-I", directory, "-I", str(ROOT / "src"),
                            "-I", str(framework_root() / "runtime/include"),
                            str(ROOT / "tests/modern_controls_test.c"), "-lm", "-o", str(executable)], check=True)
            for sensitivity, stick_sensitivity, deadzone in (("invalid", "9", "0.95"), ("2", "2", "0.25")):
                with self.subTest(sensitivity=sensitivity):
                    result = subprocess.run([str(executable)], capture_output=True, text=True, check=False,
                                            env={**os.environ, "SHADOWTOWER_MOUSE_SENSITIVITY": sensitivity,
                                                 "SHADOWTOWER_STICK_SENSITIVITY": stick_sensitivity,
                                                 "SHADOWTOWER_STICK_DEADZONE": deadzone})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr.count("gameplay code at 0x80041EA4 does not match "
                                                         "(found 0xDEADBEEF, expected 0xA4C3027A); "
                                                         "camera look paused while it differs."), 1, result.stderr)
                    self.assertEqual(result.stderr.count("does not match"), 1, result.stderr)
                    if sensitivity == "invalid":
                        for name in ("MOUSE_SENSITIVITY", "STICK_SENSITIVITY", "STICK_DEADZONE"):
                            self.assertIn(f"invalid SHADOWTOWER_{name}", result.stderr)


if __name__ == "__main__":
    unittest.main()
