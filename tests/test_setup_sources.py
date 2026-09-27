import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_setup_sources", ROOT / "tools/check_setup_sources.py")
checker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(checker)


class SetupSourceTests(unittest.TestCase):
    def check(self, extra: str = "", *, host: bool = True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "setup-sources.txt"
            manifest.write_text(
                (str(root / "setup/psxrecomp_codegen_host.c") + "\n" if host else "")
                + extra + "\n", encoding="utf-8",
            )
            checker.validate_sources(manifest, root)

    def test_disc_free_host_is_accepted(self):
        self.check("src/modern_controls.c")

    def test_game_overlays_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "generated code"):
            self.check("generated/aot/overlays_static.c")

    def test_generated_bios_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "generated code"):
            self.check("psxrecomp/generated/SCPH1001_full.c")

    def test_missing_host_implementation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "first-run"):
            self.check("src/modern_controls.c", host=False)

    def test_missing_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Missing"):
                checker.validate_sources(Path(directory) / "missing", Path(directory))


if __name__ == "__main__":
    unittest.main()
