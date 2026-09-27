"""Configure the exported, disc-free project rather than a reconstructed CMake fragment."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import package_release


class BuildConfigurationTests(unittest.TestCase):
    def test_exported_setup_host_configures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, build = root / "source", root / "build"
            package_release.copy_sources(source)
            result = subprocess.run(
                ["cmake", "-S", str(source), "-B", str(build), "-G", "Ninja",
                 "-DPSXRECOMP_FORCE_SETUP_HOST=ON", "-DPSX_ENABLE_VULKAN=OFF",
                 "-DPSX_DEBUG_TOOLS=OFF", "-DPSX_SDL3_FETCH=OFF", "-DPSX_ZLIB_FETCH=OFF"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            package_release.validate_sources(build / "setup-sources.txt", source)


if __name__ == "__main__":
    unittest.main()
