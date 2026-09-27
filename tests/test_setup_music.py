import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_setup_ui", ROOT / "tools/prepare_setup_ui.py")
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


class SetupUIAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "recomp-ui/src/common/backends/imgui/launcher_imgui.cpp").read_text(
            encoding="utf-8-sig")

    def test_pinned_source_is_supported(self):
        self.assertNotEqual(adapter.prepare(self.source), self.source)

    def test_changed_integration_point_is_rejected(self):
        anchor = '#include "launcher_backend.h"'
        for source in (self.source.replace(anchor, ""), self.source + "\n" + anchor):
            with self.subTest(), self.assertRaisesRegex(ValueError, "review the framework pin"):
                adapter.prepare(source)


if __name__ == "__main__":
    unittest.main()
