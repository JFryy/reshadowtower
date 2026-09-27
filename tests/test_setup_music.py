import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'recomp-ui/src/common/backends/imgui/launcher_imgui.cpp'
SPEC = importlib.util.spec_from_file_location("prepare_setup_ui", ROOT / "tools/prepare_setup_ui.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)
prepare = module.prepare


class SetupMusicIntegrationTests(unittest.TestCase):
    def test_pinned_backend_and_lifecycle(self):
        result = prepare(SOURCE.read_text(encoding='utf-8-sig'))
        self.assertIn('m->setup_wizard_supported && m->setup_wizard_open', result)
        self.assertIn('m->setup_wizard_open || m->setup_preparing', result)
        self.assertIn('else setup_music.reset();', result)
        self.assertLess(result.index('setup_music.reset();\n    launcher_texture_free'),
                        result.index('ImGui_ImplOpenGL3_Shutdown();'))
        self.assertIn('ImGui::Checkbox("Mute setup music", &muted)', result)
        self.assertIn('g_setup_music->error().c_str()', result)
        self.assertEqual(result.count('    draw_setup_music_controls();'), 2)

    def test_anchor_mismatch_rejected(self):
        source = SOURCE.read_text(encoding='utf-8-sig')
        with self.assertRaises(ValueError):
            prepare(source.replace('#include "launcher_backend.h"', '#include "changed.h"'))
        with self.assertRaises(ValueError):
            prepare(source + '\n#include "launcher_backend.h"\n')


if __name__ == '__main__':
    unittest.main()
