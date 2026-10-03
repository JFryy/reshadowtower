import difflib
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_source import apply_patch, prepare


class SourceAdapterTests(unittest.TestCase):
    def test_title_patches_apply_to_pinned_sources(self):
        for name in ("runtime-input", "runtime-graphics", "runtime-widescreen"):
            with self.subTest(patch=name):
                text = (ROOT / "patches" / f"{name}.patch").read_text(encoding="utf-8")
                source = (ROOT / text.splitlines()[1].removeprefix("--- a/")).read_text(encoding="utf-8-sig")
                self.assertNotEqual(apply_patch(source, text), source)

    def test_title_runtime_honors_launcher_display_and_volume(self):
        source = (ROOT / "psxrecomp/runtime/src/main.cpp").read_text(encoding="utf-8-sig")
        patched = apply_patch(source, (ROOT / "patches/runtime-input.patch").read_text())
        self.assertIn("constexpr bool ws_offered = true;", patched)
        self.assertIn("constexpr bool ws_ultrawide_offered = true;", patched)
        self.assertIn('std::getenv("SHADOWTOWER_VOLUME")', patched)
        self.assertIn('aspect_ratio = "4:3"', (ROOT / "game.toml").read_text())

    def test_widescreen_recognizes_3d_gameplay_without_forcing_2d_geometry(self):
        config = tomllib.loads((ROOT / "game.toml").read_text())
        self.assertTrue(config["widescreen"]["gte_game_mode"])
        self.assertFalse(config["widescreen"].get("native_wide", True))
        self.assertFalse(config["widescreen"].get("full_2d", False))
        self.assertEqual(config["video"]["aspect_ratio"], "4:3")

    def test_menu_stretch_is_applied_to_all_present_paths_but_not_movies(self):
        source = (ROOT / "psxrecomp/runtime/src/main.cpp").read_text(encoding="utf-8-sig")
        patched = apply_patch(source, (ROOT / "patches/runtime-input.patch").read_text())
        self.assertIn("const bool stretch_menu = g_ws_engaged && fmv_frame && !di.depth24 &&", patched)
        self.assertIn("g_video_aspect_num * 3 > g_video_aspect_den * 4 &&", patched)
        self.assertIn("!mdec_recently_active(30);", patched)
        self.assertEqual(patched.count("((fmv_frame || nw_pin) && !stretch_menu) ? 1 : 0"), 2)
        self.assertIn("pin_43 = (fmv_frame || di.depth24 || (nw_pin && !wide_present)) && !stretch_menu;", patched)

    def test_menu_state_bypasses_gte_hold_immediately(self):
        compiler = shutil.which("cc")
        if not compiler:
            self.skipTest("C compiler unavailable")
        source = (ROOT / "psxrecomp/runtime/src/gpu.c").read_text(encoding="utf-8-sig")
        patched = apply_patch(source, (ROOT / "patches/runtime-widescreen.patch").read_text())
        functions = []
        for name in ("shadowtower_menu_active", "ws_game_mode"):
            match = re.search(r"static int " + name + r"\(void\) \{.*?\n\}", patched, re.S)
            self.assertIsNotNone(match)
            functions.append(match.group())
        program = r'''
#include <assert.h>
#include <stdint.h>
static uint8_t menu;
static uint32_t enter_store = 0xA046B6DAu, exit_store = 0xA062B6DAu;
static int ws_gte_game_mode_cfg = 1;
static uint32_t s_frame_count = 100, ws_last_gte_stamp = 100, ws_last_tag_stamp = 100;
#define WS_GTE_GAME_MODE_HYSTERESIS 45
static uint32_t psx_read_word(uint32_t address) {
    assert(address == 0x80042E74u || address == 0x8004316Cu);
    return address == 0x80042E74u ? enter_store : exit_store;
}
static uint8_t psx_read_byte(uint32_t address) {
    assert(address == 0x8018B6DAu);
    return menu;
}
static int ws_gameplay_state_matches(void) { return -1; }
static int ws_full_2d_mode(void) { return 0; }
''' + "\n".join(functions) + r'''
int main(void) {
    assert(ws_game_mode() == 1);
    menu = 1;
    assert(ws_game_mode() == 0); /* Same frame: no 45-frame hold. */
    menu = 2;
    assert(ws_game_mode() == 1); /* Closing the menu restores wide gameplay. */
    menu = 1;
    enter_store = 0;
    assert(ws_game_mode() == 1); /* Other executable: ignore this RAM byte. */
    enter_store = 0xA046B6DAu;
    exit_store = 0;
    assert(ws_game_mode() == 1);
    exit_store = 0xA062B6DAu;
    ws_gte_game_mode_cfg = 0;
    assert(ws_game_mode() == 1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            test_source = Path(directory) / "menu.c"
            executable = Path(directory) / "menu"
            test_source.write_text(program)
            subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(test_source), "-o", str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_graphics_preparation_emits_both_shader_includes(self):
        shaders = [ROOT / "src/world_texture_filter.glsl", ROOT / "src/post_processing.glsl"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "gpu_gl_renderer.c"
            prepare(ROOT / "psxrecomp/runtime/src/gpu_gl_renderer.c",
                    ROOT / "patches/runtime-graphics.patch", output, shaders)
            for shader in shaders:
                self.assertTrue((output.parent / (shader.stem + ".inc")).is_file())
            generated = output.read_text()
            self.assertEqual(generated.count('#include "post_processing.inc"'), 2)
            self.assertIn("shadowtower_postfx_upload(0, s_present_prog", generated)
            self.assertIn("shadowtower_postfx_upload(1, s_interp_prog", generated)
            self.assertIn("PRESENT_SCANLINE(v_flip ? tex_h : 0", generated)
            self.assertIn("PRESENT_SCANLINE(0, 0, 0);          /* never scanline the host OSD */", generated)

    def test_patch_result_and_drift_rejection(self):
        source, expected = "first\nsecond\n", "first\nreplacement\n"
        patch = f"# source-sha256: {hashlib.sha256(source.encode()).hexdigest()}\n"
        patch += "".join(difflib.unified_diff(source.splitlines(True), expected.splitlines(True),
                                            fromfile="a/source", tofile="b/source"))
        self.assertEqual(apply_patch(source, patch), expected)
        with self.assertRaisesRegex(ValueError, "Upstream source changed"):
            apply_patch(source + "new upstream code\n", patch)
        with self.assertRaisesRegex(ValueError, "context does not match"):
            apply_patch(source, patch.replace("-second\n", "-wrong context\n"))


if __name__ == "__main__":
    unittest.main()
