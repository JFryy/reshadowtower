"""Compile and exercise the actual render-scale helpers with mocked GL allocations."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_source import apply_patch


def compile_run(test, code):
    compiler = shutil.which("cc")
    if not compiler:
        test.skipTest("C compiler unavailable")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "check.c"
        executable = Path(directory) / "check"
        source.write_text(code)
        subprocess.run([compiler, "-std=c11", "-UNDEBUG", "-I", str(ROOT / "src"),
                        str(source), "-o", str(executable)], check=True, capture_output=True, text=True)
        subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)


class RenderScale(unittest.TestCase):
    def test_limits_and_retry_ladder(self):
        compile_run(self, r'''
#include <assert.h>
#include "render_scale.h"
int main(void) {
    for (int n = 1; n <= 8; ++n) assert(shadowtower_scale_for_limits(n, 8192, 8192) == n);
    assert(shadowtower_scale_for_limits(8, 4096, 8192) == 4);
    assert(shadowtower_scale_for_limits(8, 8192, 2048) == 2);
    assert(shadowtower_scale_for_limits(8, 1023, 8192) == 0);
    assert(shadowtower_scale_for_limits(8, 8192, 1023) == 0);
    assert(shadowtower_scale_for_limits(99, 8192, 8192) == 8);
    int ladder[] = {8, 4, 2, 1, 0};
    for (int i = 0; i < 4; ++i) assert(shadowtower_lower_scale(ladder[i]) == ladder[i+1]);
    return 0;
}
''')

    def test_transactional_gl_allocations(self):
        compile_run(self, r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "render_scale.h"
typedef unsigned int GLuint, GLenum;
typedef int GLint;
#define GL_MAX_TEXTURE_SIZE 0xD33
#define GL_NO_ERROR 0
#define GL_RGBA8 1
#define GL_RGBA 2
#define GL_UNSIGNED_BYTE 3
#define GL_TEXTURE_2D 4
#define PSXGL_RENDERBUFFER 5
#define PSXGL_DEPTH24_STENCIL8 6
#define PSXGL_FRAMEBUFFER 7
#define VRAM_W 1024
#define VRAM_H 512
static GLuint s_hr_tex, s_scratch_tex, s_hr_rb, s_hr_fbo, s_scratch_fbo;
static int s_scale, limit, mode, attempts[5], na, next_id, live[256], warnings;
static char warning[160];
static GLenum pending;
static int stage, error_calls;
static void reset(int m, int cap) {
    memset(live, 0, sizeof live); memset(attempts, 0, sizeof attempts);
    s_hr_tex = s_scratch_tex = s_hr_rb = s_hr_fbo = s_scratch_fbo = 0;
    s_scale = 1; warnings = na = 0; next_id = 0; pending = 0;
    stage = error_calls = 0; mode = m; limit = cap; warning[0] = 0;
}
static GLuint alloc(void) { GLuint id = ++next_id; assert(id < 256); live[id] = 1; return id; }
static void drop(GLuint id) { assert(id && live[id]); live[id] = 0; }
static void glGetIntegerv(GLenum p, GLint *v) { *v = limit; (void)p; }
static GLenum glGetError(void) { ++error_calls; GLenum e = pending; pending = 0; return e; }
static GLuint make_tex(GLenum a, int w, int h, GLenum b, GLenum c) {
    (void)a; (void)h; (void)b; (void)c;
    if (stage == 0) { attempts[na++] = w / VRAM_W; stage = 1; }
    else stage = 2;
    GLuint id = alloc();
    if (w == 8192 && ((mode == 1 && stage == 1) || (mode == 2 && stage == 2))) pending = 0x505;
    if (mode == 5) pending = 0x505;
    return id;
}
static void p_glGenRenderbuffers(int n, GLuint *id) { assert(n == 1); *id = alloc(); }
static void p_glBindRenderbuffer(GLenum t, GLuint id) { (void)t; (void)id; }
static void p_glRenderbufferStorage(GLenum t, GLenum f, int w, int h) {
    (void)t; (void)f; (void)h;
    if (w == 8192 && mode == 3) pending = 0x505;
}
static int make_fbo(GLuint *id, GLuint tex, GLuint depth) {
    (void)tex; (void)depth; *id = alloc();
    if (mode == 4 && attempts[na-1] == 8) return 0;
    return 1;
}
static void p_glBindFramebuffer(GLenum t, GLuint id) { (void)t; (void)id; stage = 0; }
static void p_glDeleteFramebuffers(int n, const GLuint *id) { assert(n == 1); drop(*id); }
static void p_glDeleteRenderbuffers(int n, const GLuint *id) { assert(n == 1); drop(*id); }
static void glBindTexture(GLenum t, GLuint id) { (void)t; (void)id; }
static void glDeleteTextures(int n, const GLuint *id) { assert(n == 1); drop(*id); }
static void host_osd_push(const char *s, int ms) {
    assert(ms == 8000); ++warnings; snprintf(warning, sizeof warning, "%s", s);
}
#include "render_scale_gl.h"
static void check_live(int success) {
    for (int i = 1; i <= next_id; ++i) {
        int expected = success && (i == s_hr_tex || i == s_scratch_tex || i == s_hr_rb ||
                                      i == s_hr_fbo || i == s_scratch_fbo);
        assert(live[i] == expected);
    }
}
int main(void) {
    reset(0, 8192); assert(shadowtower_allocate_render_targets(8));
    assert(s_scale == 8 && na == 1 && attempts[0] == 8 && !warnings); check_live(1);
    reset(0, 4096); assert(shadowtower_allocate_render_targets(8));
    assert(s_scale == 4 && na == 1 && attempts[0] == 4 && warnings == 1);
    assert(strstr(warning, "8x") && strstr(warning, "4x")); check_live(1);
    for (int mode = 1; mode <= 4; ++mode) {
        reset(mode, 8192); assert(shadowtower_allocate_render_targets(8));
        assert(s_scale == 4 && na == 2 && attempts[0] == 8 && attempts[1] == 4);
        assert(warnings == 1 && strstr(warning, "4x")); check_live(1);
    }
    reset(5, 8192); assert(!shadowtower_allocate_render_targets(8));
    assert(s_scale == 1 && !warnings && na == 4);
    assert(attempts[0] == 8 && attempts[1] == 4 && attempts[2] == 2 && attempts[3] == 1);
    assert(error_calls < 100); check_live(0);
    reset(0, 1023); assert(!shadowtower_allocate_render_targets(8));
    assert(!na && s_scale == 1); check_live(0);
    return 0;
}
''')

    def test_software_allocation_failure_returns_to_native(self):
        source = (ROOT / "psxrecomp/runtime/src/gpu_sw_renderer.c").read_text()
        source = apply_patch(source, (ROOT / "patches/runtime-software.patch").read_text())
        function = re.search(r"void sw_renderer_set_scale\(int scale\) \{.*?^\}", source, re.S | re.M)
        self.assertIsNotNone(function)
        compile_run(self, r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "render_scale.h"
#define VRAM_WIDTH 1024
#define VRAM_HEIGHT 512
static uint16_t *g_hr;
static int g_scale = 1, g_hr_w = 1024, g_hr_h = 512, fail, warnings;
static size_t requested_bytes;
static void wide_free_all(void) {}
static void host_osd_push(const char *message, int duration) { (void)message; (void)duration; ++warnings; }
static void *test_calloc(size_t count, size_t size) {
    requested_bytes = count * size;
    return fail ? NULL : malloc(8);
}
#define calloc test_calloc
''' + function.group() + r'''
int main(void) {
    sw_renderer_set_scale(8);
    assert(g_scale == 8 && g_hr && g_hr_w == 8192 && g_hr_h == 4096);
    assert(requested_bytes == 64u * 1024u * 1024u);
    fail = 1;
    sw_renderer_set_scale(8);
    assert(g_scale == 1 && !g_hr && g_hr_w == 1024 && g_hr_h == 512 && warnings == 1);
    sw_renderer_set_scale(1);
    assert(g_scale == 1 && !g_hr && warnings == 1);
    return 0;
}
''')

    def test_source_caps(self):
        patch = (ROOT / "patches/runtime-input.patch").read_text()
        self.assertGreaterEqual(patch.count("SHADOWTOWER_MAX_INTERNAL_SCALE"), 4)
        self.assertIn("640 * SHADOWTOWER_MAX_INTERNAL_SCALE", patch)
        settings = (ROOT / "patches/runtime-settings.patch").read_text()
        self.assertGreaterEqual(settings.count("SHADOWTOWER_MAX_INTERNAL_SCALE"), 2)
        software = (ROOT / "patches/runtime-software.patch").read_text()
        self.assertIn("if (scale > SHADOWTOWER_MAX_INTERNAL_SCALE) scale = SHADOWTOWER_MAX_INTERNAL_SCALE;", software)
        self.assertIn("host_osd_push", software)
