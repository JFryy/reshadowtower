"""Standalone parser and real OpenGL presentation post-processing regressions."""
from __future__ import annotations

import ast
import ctypes
import ctypes.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
from dependencies import framework_root
from prepare_source import prepare
from test_world_texture_filter import _c_string


class PostFxParser(unittest.TestCase):
    def test_payload_validation_and_neutral_failure(self):
        compiler = shutil.which("cc")
        if not compiler:
            self.skipTest("C compiler unavailable")
        code = r'''
#include <assert.h>
#include <math.h>
#include "post_processing.h"
int main(void) {
    ShadowtowerPostFx p;
    float strength;
    assert(shadowtower_postfx_strength(NULL, &strength) && strength == 0.f);
    assert(shadowtower_postfx_strength("0.5", &strength) && strength == .5f);
    const char *invalid_strengths[] = {"", "nan", "inf", "-0.1", "1.1", "0.5x"};
    for (unsigned i = 0; i < sizeof(invalid_strengths)/sizeof(invalid_strengths[0]); ++i)
        assert(!shadowtower_postfx_strength(invalid_strengths[i], &strength) && strength == 0.f);
    assert(shadowtower_postfx_parse(NULL, &p) && !p.enabled);
    assert(shadowtower_postfx_parse("0", &p) && !p.enabled);
    assert(shadowtower_postfx_parse("1,1,1,0,0.1,0.5,0.5,0.5,0.5,0.1", &p));
    assert(p.enabled && p.exposure == 1.f && p.saturation == 0.f && p.curvature == .1f);
    const char *bad[] = {"2,0,1,1,0,0,0,0,0,0", "1,0,1", "1,0,1,1,0,0,0,0,0,0,1",
        "1,nan,1,1,0,0,0,0,0,0", "1,inf,1,1,0,0,0,0,0,0",
        "1,2.1,1,1,0,0,0,0,0,0", "1,0,0.4,1,0,0,0,0,0,0",
        "1,0,1,1,0.21,0,0,0,0,0", "1,0,1,1,0,0,0,0,0,0.21"};
    for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
        assert(!shadowtower_postfx_parse(bad[i], &p));
        assert(!p.enabled && p.exposure == 0.f && p.contrast == 1.f && p.saturation == 1.f);
        assert(p.grain == 0.f && p.dither == 0.f && p.bloom == 0.f);
        assert(p.scanlines == 0.f && p.mask == 0.f && p.curvature == 0.f);
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "parser.c"
            binary = Path(directory) / "parser"
            source.write_text(code)
            subprocess.run([compiler, "-std=c11", "-UNDEBUG", "-I", str(ROOT / "src"),
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


def _expand(source: str, name: str) -> str:
    match = re.search(r"(?m)^#define " + name + r" \\\n((?:.*\\\n)*?    \".*\"\n)", source)
    if not match:
        raise AssertionError(f"missing {name}")
    return "".join(ast.literal_eval(token) for token in
                   re.findall(r'"(?:\\.|[^"\\])*"', match.group(1)))


class PostFxGL(unittest.TestCase):
    W = H = 64

    @classmethod
    def setUpClass(cls):
        try:
            from OpenGL import GL
        except ImportError as exc:
            raise unittest.SkipTest(f"GL context unavailable (PyOpenGL): {exc}")
        library = ctypes.util.find_library("SDL3")
        if not library:
            raise unittest.SkipTest("GL context unavailable (SDL3 library missing)")
        cls.sdl = ctypes.CDLL(library)
        sdl = cls.sdl
        sdl.SDL_Init.argtypes = [ctypes.c_uint32]
        sdl.SDL_Init.restype = ctypes.c_bool
        sdl.SDL_CreateWindow.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint64]
        sdl.SDL_CreateWindow.restype = ctypes.c_void_p
        sdl.SDL_GL_CreateContext.argtypes = [ctypes.c_void_p]
        sdl.SDL_GL_CreateContext.restype = ctypes.c_void_p
        sdl.SDL_GL_SetAttribute.argtypes = [ctypes.c_int, ctypes.c_int]
        sdl.SDL_GL_SetAttribute.restype = ctypes.c_bool
        sdl.SDL_GL_DestroyContext.argtypes = [ctypes.c_void_p]
        sdl.SDL_DestroyWindow.argtypes = [ctypes.c_void_p]
        sdl.SDL_Quit.argtypes = []
        sdl.SDL_GetError.restype = ctypes.c_char_p
        if not sdl.SDL_Init(0x20):
            raise unittest.SkipTest(f"GL context unavailable: {sdl.SDL_GetError().decode()}")
        sdl.SDL_GL_SetAttribute(17, 3)
        sdl.SDL_GL_SetAttribute(18, 3)
        sdl.SDL_GL_SetAttribute(21, 1)
        cls.window = sdl.SDL_CreateWindow(b"postfx-test", cls.W, cls.H, 0x2 | 0x8)
        if not cls.window:
            error = sdl.SDL_GetError().decode()
            sdl.SDL_Quit()
            raise unittest.SkipTest(f"GL context unavailable: {error}")
        cls.context = sdl.SDL_GL_CreateContext(cls.window)
        if not cls.context:
            error = sdl.SDL_GetError().decode()
            sdl.SDL_DestroyWindow(cls.window)
            sdl.SDL_Quit()
            raise unittest.SkipTest(f"GL context unavailable: {error}")
        cls.GL = GL
        try:
            original = (framework_root() / "runtime/src/gpu_gl_renderer.c").read_text()
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "gpu_gl_renderer.c"
                prepare(framework_root() / "runtime/src/gpu_gl_renderer.c",
                        ROOT / "patches/runtime-graphics.patch", output,
                        [ROOT / "src/world_texture_filter.glsl", ROOT / "src/post_processing.glsl"])
                generated = output.read_text().replace('#include "post_processing.inc"',
                                                       (output.parent / "post_processing.inc").read_text())
            for name in ("PSX_SCANLINE_UNIFORMS", "PSX_SCANLINE_FUNC"):
                replacement = '\n'.join('"' + line.encode('unicode_escape').decode() + '\\n"'
                                        for line in _expand(original, name).splitlines())
                generated = generated.replace('    ' + name + '\n', replacement + '\n')
                original = original.replace('    ' + name + '\n', replacement + '\n')
            vs = _c_string(generated, "PRESENT_VS")
            cls.programs = {}
            for mode, text in (("present", "PRESENT_FS"), ("interp", "INTERP_FS")):
                cls.programs[mode] = (cls._program(vs, _c_string(original, text)),
                                      cls._program(vs, _c_string(generated, text)))
            cls.vao = GL.glGenVertexArrays(1)
            cls.texture = GL.glGenTextures(1)
            cls.previous = GL.glGenTextures(1)
            cls.target = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, cls.target)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, cls.W, cls.H, 0,
                            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
            cls.fbo = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, cls.fbo)
            GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                      GL.GL_TEXTURE_2D, cls.target, 0)
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise AssertionError("presentation framebuffer incomplete")
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "context", None):
            cls.sdl.SDL_GL_DestroyContext(cls.context)
            cls.context = None
        if getattr(cls, "window", None):
            cls.sdl.SDL_DestroyWindow(cls.window)
            cls.window = None
        if getattr(cls, "sdl", None):
            cls.sdl.SDL_Quit()

    @classmethod
    def _program(cls, vs, fs):
        GL = cls.GL
        shaders = []
        for kind, text in ((GL.GL_VERTEX_SHADER, vs), (GL.GL_FRAGMENT_SHADER, fs)):
            shader = GL.glCreateShader(kind)
            GL.glShaderSource(shader, text)
            GL.glCompileShader(shader)
            if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
                raise AssertionError(GL.glGetShaderInfoLog(shader).decode())
            shaders.append(shader)
        program = GL.glCreateProgram()
        for shader in shaders:
            GL.glAttachShader(program, shader)
        GL.glLinkProgram(program)
        if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
            raise AssertionError(GL.glGetProgramInfoLog(program).decode())
        for shader in shaders:
            GL.glDeleteShader(shader)
        return program

    def _render(self, mode="present", enabled=0, original=False, pixels=None,
                rect=(0., 0., 1., 1.), exposure=0., contrast=1., saturation=1.,
                grain=0., dither=0., bloom=0., scanlines=0., mask=0., curvature=0.,
                previous=None, blend_mode=0, sharp=0, linear=False, output_size=None,
                fxaa=0., sharpen=0.):
        GL = self.GL
        if pixels is None:
            pixels = bytes(v for y in range(16) for x in range(16)
                           for v in (40+x*9, 60+y*8, 90+x*4, 255))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        filtering = GL.GL_LINEAR if linear else GL.GL_NEAREST
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, filtering)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, filtering)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, 16, 16, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels)
        if previous is not None:
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.previous)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, 16, 16, 0,
                            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, previous)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        width, height = output_size or (self.W, self.H)
        GL.glViewport(0, 0, width, height)
        GL.glDisable(GL.GL_BLEND)
        GL.glBindVertexArray(self.vao)
        program = self.programs[mode][0 if original else 1]
        GL.glUseProgram(program)
        def uniform(name, method, *values):
            location = GL.glGetUniformLocation(program, name)
            if location >= 0:
                getattr(GL, method)(location, *values)
        uniform("u_uv_rect", "glUniform4f", *rect)
        uniform("u_tex_size", "glUniform2f", 16., 16.)
        uniform("u_sharp_scale", "glUniform2f", width / 16., height / 16.)
        uniform("u_sharp", "glUniform1i", sharp)
        uniform("u_tex", "glUniform1i", 0)
        uniform("u_prev", "glUniform1i", 1 if previous is not None else 0)
        uniform("u_curr", "glUniform1i", 0)
        uniform("u_alpha", "glUniform1f", .5)
        uniform("u_blend_mode", "glUniform1i", blend_mode)
        uniform("u_scanline", "glUniform1i", 0)
        uniform("u_postfx_enabled", "glUniform1i", enabled)
        uniform("u_postfx_color", "glUniform4f", exposure, contrast, saturation, bloom)
        uniform("u_postfx_texture", "glUniform2f", grain, dither)
        uniform("u_postfx_crt", "glUniform4f", curvature, scanlines, mask, 1.)
        uniform("u_postfx_pitch", "glUniform1f", 16.)
        uniform("u_postfx_time", "glUniform1f", 42.)
        uniform("u_postfx_detail", "glUniform2f", fxaa, sharpen)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        result = bytes(GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE))
        self.assertEqual(GL.glGetError(), GL.GL_NO_ERROR)
        return result

    @staticmethod
    def _pixel(image, x, y):
        return image[(y*64+x)*4:(y*64+x+1)*4]

    def test_disabled_and_neutral_match_original(self):
        for mode, blend in (("present", 0), ("interp", 0), ("interp", 1)):
            with self.subTest(mode=mode, blend=blend):
                options = dict(mode=mode, blend_mode=blend,
                               previous=bytes((180, 70, 120, 255)) * 256)
                baseline = self._render(original=True, **options)
                self.assertEqual(self._render(**options), baseline)
                self.assertEqual(self._render(enabled=1, **options), baseline)
                self.assertNotEqual(self._render(enabled=1, exposure=1., grain=.2,
                                                 curvature=.2, mask=1., **options), baseline)
                self.assertEqual(self._render(**options), baseline)

    def test_movie_filters_reconstruct_the_image_and_preserve_flat_colors(self):
        # Sharp-bilinear intentionally matches nearest at integer magnification.
        self.assertTrue(self._render(sharp=1, linear=True) == self._render())
        options = dict(output_size=(63, 61))
        nearest = self._render(**options)
        bilinear = self._render(linear=True, **options)
        self.assertTrue(nearest != bilinear, "Linear filtering should affect fractional scaling")
        for sharp in (1, 2):
            with self.subTest(sharp=sharp):
                filtered = self._render(sharp=sharp, linear=True, **options)
                self.assertTrue(filtered != nearest, "Movie filter should reconstruct fractional edges")
                self.assertTrue(filtered != bilinear, "Movie filter should differ from plain bilinear")
                self.assertTrue(filtered == self._render(original=True, sharp=sharp, linear=True, **options))
                gray = bytes((96, 96, 96, 255)) * 256
                self.assertTrue(self._render(pixels=gray, sharp=sharp, linear=True, **options) ==
                                self._render(pixels=gray, **options))

    def test_color_and_texture_effects(self):
        gray = bytes((96, 96, 96, 255)) * 256
        baseline = self._render(pixels=gray)
        self.assertGreater(self._pixel(self._render(enabled=1, pixels=gray, exposure=1.), 32, 32)[0], 150)
        color = self._render(enabled=1, saturation=0.)
        p = self._pixel(color, 32, 32)
        self.assertLess(max(p[:3])-min(p[:3]), 2)
        for effect in (dict(grain=.2), dict(dither=1.), dict(scanlines=1.), dict(mask=1.)):
            with self.subTest(effect=effect):
                result = self._render(enabled=1, pixels=gray, **effect)
                self.assertNotEqual(result, baseline)
                self.assertTrue(all(0 <= v <= 255 for v in result))
        curved = self._render(enabled=1, pixels=gray, curvature=.2)
        self.assertNotEqual(curved, baseline)
        self.assertEqual(self._pixel(curved, 0, 0), bytes((0, 0, 0, 255)))

    def test_detail_effects_preserve_flat_images_and_respect_master_switch(self):
        gray = bytes((96, 96, 96, 255)) * 256
        for mode in ("present", "interp"):
            for options in (dict(fxaa=1.), dict(sharpen=1.), dict(fxaa=1., sharpen=1.)):
                with self.subTest(mode=mode, options=options):
                    self.assertEqual(self._render(mode=mode, pixels=gray, enabled=1, **options),
                                     self._render(mode=mode, pixels=gray))
                    self.assertEqual(self._render(mode=mode, **options), self._render(mode=mode))

    def test_fxaa_smooths_diagonal_edges(self):
        pixels = bytes(v for y in range(16) for x in range(16)
                       for v in ((220, 220, 220, 255) if x > y else (30, 30, 30, 255)))
        for mode in ("present", "interp"):
            with self.subTest(mode=mode):
                baseline = self._render(mode=mode, pixels=pixels)
                result = self._render(mode=mode, pixels=pixels, enabled=1, fxaa=1.)
                self.assertNotEqual(result, baseline)
                self.assertTrue(any(35 < value < 215 for value in result[::4]))
                self.assertTrue(all(29 <= value <= 221 for value in result[::4]))
                self.assertEqual(result[3::4], baseline[3::4])

    def test_sharpening_adds_contrast_without_ringing(self):
        levels = (80, 80, 80, 80, 80, 90, 100, 130, 150, 160, 170, 170, 170, 170, 170, 170)
        pixels = bytes(v for _ in range(16) for x in range(16)
                       for v in (levels[x], levels[x], levels[x], 255))
        for mode in ("present", "interp"):
            with self.subTest(mode=mode):
                baseline = self._render(mode=mode, pixels=pixels)
                result = self._render(mode=mode, pixels=pixels, enabled=1, sharpen=1.)
                self.assertNotEqual(result, baseline)
                self.assertTrue(all(80 <= value <= 170 for value in result[::4]))
                self.assertEqual(result[3::4], baseline[3::4])

    def test_detail_effects_do_not_sample_adjacent_vram(self):
        pixels = bytes(v for _ in range(16) for x in range(16)
                       for v in ((80, 80, 80, 255) if x < 8 else (255, 0, 0, 255)))
        rect = (.5/16, .5/16, 7.5/16, 15.5/16)
        for mode in ("present", "interp"):
            baseline = self._render(mode=mode, pixels=pixels, rect=rect)
            result = self._render(mode=mode, pixels=pixels, rect=rect, enabled=1, fxaa=1., sharpen=1.)
            self.assertEqual(result, baseline)

    def test_bloom_clamps_to_display_rect(self):
        pixels = bytearray(bytes((0, 0, 0, 255)) * 256)
        for y in range(16):
            pixels[(y*16+8)*4:(y*16+9)*4] = bytes((255, 0, 0, 255))
        pixels[(8*16+7)*4:(8*16+8)*4] = bytes((255, 255, 255, 255))
        rect = (.5/16, .5/16, 7.5/16, 15.5/16)
        base = self._render(pixels=bytes(pixels), rect=rect)
        glow = self._render(enabled=1, bloom=1., pixels=bytes(pixels), rect=rect)
        self.assertNotEqual(glow, base)
        self.assertGreater(self._pixel(glow, 52, 32)[0], self._pixel(base, 52, 32)[0])
        pixels[(8*16+7)*4:(8*16+8)*4] = bytes((0, 0, 0, 255))
        outside = self._render(enabled=1, bloom=1., pixels=bytes(pixels), rect=rect)
        self.assertEqual(self._pixel(outside, 63, 32)[0], 0)


if __name__ == "__main__":
    unittest.main()
