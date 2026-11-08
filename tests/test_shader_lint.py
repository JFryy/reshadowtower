"""Embedded GLSL passes glslangValidator, and the lint catches real errors."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lint_shaders


class ShaderLint(unittest.TestCase):
    def test_embedded_shaders_validate(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/lint_shaders.py")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), len(lint_shaders.SHADERS))

    def test_broken_fragment_is_rejected(self):
        for fragment in lint_shaders.DEFAULT_FRAGMENTS:
            with self.subTest(fragment=fragment.name), tempfile.TemporaryDirectory() as directory:
                broken = Path(directory) / fragment.name
                shutil.copy(fragment, broken)
                with broken.open("a") as handle:
                    handle.write("\nfloat shadowtower_lint_probe = ;\n")
                others = [p for p in lint_shaders.DEFAULT_FRAGMENTS if p != fragment]
                with self.assertRaises(RuntimeError) as caught:
                    lint_shaders.lint(others + [broken])
                self.assertIn("FAILED", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
