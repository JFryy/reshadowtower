"""Verify the title-local input adaptation without executing the runtime."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_input import prepare_input


class InputIntegration(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "psxrecomp/runtime/src/main.cpp").read_text()

    def test_all_existing_call_sites_are_adapted(self):
        result = prepare_input(self.source)
        self.assertEqual(result.count('while (shadowtower_poll_event(&ev)) {'), 4)
        self.assertEqual(result.count('return shadowtower_pad_word(keys, player);'), 1)
        self.assertNotIn('SDL_PollEvent(', result)
        self.assertNotIn('psx_keybinds_pad_word(', result)
        self.assertNotIn('__wrap_', result)
        # Reversing just these substitutions must recover the entire original.
        restored = result.replace('#include "modern_controls.h"\n', '')
        restored = restored.replace('shadowtower_poll_event(', 'SDL_PollEvent(')
        restored = restored.replace('shadowtower_pad_word(', 'psx_keybinds_pad_word(')
        self.assertEqual(restored, self.source)

    def test_changed_or_additional_call_sites_fail(self):
        for changed in (
            self.source.replace('while (SDL_PollEvent(&ev)) {', 'while (SDL_PollEvent(&event)) {', 1),
            self.source + '\nwhile (SDL_PollEvent(&ev)) {\n',
            self.source.replace('return psx_keybinds_pad_word(keys, player);', ''),
        ):
            with self.subTest(changed=changed[-60:]):
                with self.assertRaisesRegex(ValueError, 'Input integration point changed'):
                    prepare_input(changed)


if __name__ == "__main__":
    unittest.main()
