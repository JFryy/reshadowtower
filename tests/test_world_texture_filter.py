"""Small real-GL tests for the generated textured-polygon shader: the world texture
filter and per-pixel GTE lighting and fog.

These tests deliberately use the renderer's generated shaders and vertex format.  They
skip (rather than substituting a software GL implementation) when SDL3, PyOpenGL, or
an OpenGL 3.3 context is unavailable.
"""
from __future__ import annotations

import ast
import ctypes
import ctypes.util
import re
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from dependencies import framework_root
from prepare_source import prepare


def _c_string(source: str, name: str) -> str:
    declaration = re.search(r"static const char \*" + re.escape(name) + r"\s*=", source)
    if not declaration:
        raise AssertionError(f"generated renderer has no {name}")
    # GLSL strings contain semicolons; find the C initializer's final string.
    tail = source[declaration.end():]
    end = re.search(r'^\s*"(?:\\.|[^"\\])*";\s*$', tail, re.MULTILINE)
    if not end:
        raise AssertionError(f"generated renderer has unterminated {name}")
    tokens = re.findall(r'"(?:\\.|[^"\\])*"', tail[:end.end()])
    if not tokens:
        raise AssertionError(f"generated {name} has no C string literals")
    return "".join(ast.literal_eval(token) for token in tokens)


def _find_sdl3() -> str | None:
    """SDL3's shared library; find_library does not search Homebrew's prefix on macOS."""
    library = ctypes.util.find_library("SDL3")
    if library or sys.platform != "darwin":
        return library
    for prefix in ("/opt/homebrew/lib", "/usr/local/lib"):
        candidate = Path(prefix) / "libSDL3.dylib"
        if candidate.exists():
            return str(candidate)
    return None


def _request_core_gl(sdl) -> None:
    """Ask for an OpenGL 3.3 core context; macOS only grants one when it is forward-compatible."""
    # SDL_GL_CONTEXT_{MAJOR,MINOR}_VERSION (17, 18) and SDL_GL_CONTEXT_PROFILE_MASK (20) = core.
    # 21 is SDL_GL_SHARE_WITH_CURRENT_CONTEXT, not the profile.
    sdl.SDL_GL_SetAttribute(17, 3)
    sdl.SDL_GL_SetAttribute(18, 3)
    sdl.SDL_GL_SetAttribute(20, 1)
    if sys.platform == "darwin":
        # SDL_GL_CONTEXT_FLAGS (19) = SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG.
        sdl.SDL_GL_SetAttribute(19, 2)


class TexturedShaderGL(unittest.TestCase):
    """GL context and renderer TEX program shared by the textured-shader tests."""
    W = H = 32

    @classmethod
    def setUpClass(cls):
        try:
            from OpenGL import GL
        except ImportError as exc:
            raise unittest.SkipTest(f"PyOpenGL unavailable: {exc}")
        library = _find_sdl3()
        if not library:
            raise unittest.SkipTest("SDL3 library unavailable")
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
        sdl.SDL_GL_DestroyContext.restype = ctypes.c_bool
        sdl.SDL_DestroyWindow.argtypes = [ctypes.c_void_p]
        sdl.SDL_DestroyWindow.restype = None
        sdl.SDL_Quit.argtypes = []
        sdl.SDL_Quit.restype = None
        sdl.SDL_GetError.restype = ctypes.c_char_p
        if not sdl.SDL_Init(0x20):
            raise unittest.SkipTest(f"SDL video init failed: {sdl.SDL_GetError().decode()}")
        _request_core_gl(sdl)
        cls.window = sdl.SDL_CreateWindow(b"shader-test", cls.W, cls.H, 0x2 | 0x8)
        if not cls.window:
            sdl.SDL_Quit()
            raise unittest.SkipTest(f"hidden GL window failed: {sdl.SDL_GetError().decode()}")
        cls.context = sdl.SDL_GL_CreateContext(cls.window)
        if not cls.context:
            sdl.SDL_DestroyWindow(cls.window)
            sdl.SDL_Quit()
            raise unittest.SkipTest(f"OpenGL 3.3 context failed: {sdl.SDL_GetError().decode()}")
        cls.GL = GL
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "gpu_gl_renderer.c"
                shaders = [ROOT / "src/world_texture_filter.glsl", ROOT / "src/gte_lighting.glsl"]
                prepare(framework_root() / "runtime/src/gpu_gl_renderer.c",
                        ROOT / "patches/runtime-graphics.patch", output, shaders)
                generated = output.read_text()
                for shader in shaders:
                    generated = generated.replace(f'#include "{shader.stem}.inc"',
                                                  (output.parent / f"{shader.stem}.inc").read_text())
            cls.vs_source = _c_string(generated, "TEX_VS")
            cls.fs_source = _c_string(generated, "TEX_FS")
            cls.program = cls._program(cls.vs_source, cls.fs_source)
            cls._make_targets()
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
    def _program(cls, vs_text, fs_text):
        GL = cls.GL
        shaders = []
        for kind, text in ((GL.GL_VERTEX_SHADER, vs_text), (GL.GL_FRAGMENT_SHADER, fs_text)):
            shader = GL.glCreateShader(kind)
            GL.glShaderSource(shader, text)
            GL.glCompileShader(shader)
            if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
                raise AssertionError(GL.glGetShaderInfoLog(shader).decode())
            shaders.append(shader)
        program = GL.glCreateProgram()
        for shader in shaders:
            GL.glAttachShader(program, shader)
        GL.glBindFragDataLocation(program, 0, "frag")
        GL.glLinkProgram(program)
        if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
            raise AssertionError(GL.glGetProgramInfoLog(program).decode())
        for shader in shaders:
            GL.glDeleteShader(shader)
        return program

    @classmethod
    def _make_targets(cls):
        GL = cls.GL
        cls.vram = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, cls.vram)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        cls.color = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, cls.color)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, cls.W, cls.H, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        cls.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, cls.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, cls.color, 0)
        GL.glDrawBuffers(1, [GL.GL_COLOR_ATTACHMENT0])
        if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
            raise AssertionError("RGBA FBO is incomplete")
        cls.light_context = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, cls.light_context)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        cls.vao = GL.glGenVertexArrays(1)
        cls.vbo = GL.glGenBuffers(1)

    def _render(self, pixels, *, uv=(0.0, 0.0), step=(0.0, 0.0), depth=2,
                world=1, filtering=1, limits=(0, 0, 255, 255), twin=(0, 0, 0, 0),
                tpage=(0, 0), clut=(512, 0), clear=(17, 19, 23, 255), raw=1,
                colour=(1, 1, 1), zdepth=(1, 1, 1), light=None, context=None,
                pixel_lighting=1, smooth_fog=1):
        GL = self.GL
        data = array("H", pixels)
        if len(data) < 1024 * 512:
            data.extend([0] * (1024 * 512 - len(data)))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.vram)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_R16UI, 1024, 512, 0, GL.GL_RED_INTEGER,
                        GL.GL_UNSIGNED_SHORT, data.tobytes())
        # Oversized triangle: positions map to NDC (-1,-1),(3,-1),(-1,3).
        verts = []
        light = light or [(0, 0, 0, -1, 0, 0, 0, 0)] * 3
        for i, (x, y, u, v) in enumerate(((0, 0, uv[0], uv[1]), (2048, 0, uv[0] + step[0]*64, uv[1]),
                                          (0, 1024, uv[0], uv[1] + step[1]*64))):
            verts.extend((x,y,u,v, *colour,1, *tpage, *clut, depth, raw, *limits, 0, 0, world, zdepth[i],
                          *light[i]))
        buf = array("f", verts)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(buf)*4, buf.tobytes(), GL.GL_STREAM_DRAW)
        sizes = (2,2,4,2,2,1,1,4,1,1,1,1,4,4)
        offset = 0
        for index, size in enumerate(sizes):
            GL.glVertexAttribPointer(index, size, GL.GL_FLOAT, False, 120, ctypes.c_void_p(offset*4))
            GL.glEnableVertexAttribArray(index)
            offset += size
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.W, self.H)
        GL.glDisable(GL.GL_BLEND)
        GL.glClearColor(*(c/255 for c in clear))
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glActiveTexture(GL.GL_TEXTURE0 + 2)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.light_context)
        rows = array("f", context or [0.0] * 24)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA32F, 6, len(rows) // 24, 0, GL.GL_RGBA,
                        GL.GL_FLOAT, rows.tobytes())
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUseProgram(self.program)
        for name, value in (("u_vram",0),("u_filter",filtering),("u_semipass",0),
                            ("u_semimode",0),("u_maskset",0),("u_light_context",2),
                            ("u_pixel_lighting",pixel_lighting),("u_smooth_fog",smooth_fog)):
            GL.glUniform1i(GL.glGetUniformLocation(self.program, name), value)
        for name, value in (("u_shift",0.0),("u_xhalf",512.0),("u_xoff",0.0),
                            ("u_xscale",1.0),("u_xcenter",0.0)):
            GL.glUniform1f(GL.glGetUniformLocation(self.program, name), value)
        GL.glUniform4i(GL.glGetUniformLocation(self.program, "u_twin"), *twin)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        result = bytes(GL.glReadPixels(0, 0, self.W, self.H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE))
        self.assertEqual(GL.glGetError(), GL.GL_NO_ERROR)
        return result

    @staticmethod
    def _vram(entries):
        p = [0] * (1024 * 512)
        for x, y, value in entries:
            p[y*1024+x] = value
        return p



class WorldTextureFilterGL(TexturedShaderGL):
    def test_filter_disabled_or_ineligible_is_pixel_identical(self):
        p = self._vram([(x, 0, 0x001f if x & 1 else 0x7c00) for x in range(16)])
        nearest = self._render(p, uv=(0.2,0), step=(.25,0), filtering=0)
        ineligible = self._render(p, uv=(0.2,0), step=(.25,0), filtering=1, world=0)
        self.assertEqual(nearest, ineligible)

    def test_zero_centre_discards(self):
        image = self._render(self._vram([]), uv=(0,0), clear=(17,19,23,255))
        self.assertEqual(set(zip(*[iter(image)]*4)), {(17,19,23,255)})

    def test_different_stp_neighbour_does_not_bleed(self):
        p = self._vram([(x,0,0x001f if x % 2 == 0 else 0xfc00) for x in range(64)])
        image = self._render(p, uv=(0,0), step=(1.25,0))
        # Both STP classes appear inside the filter footprint. No pixel may mix them.
        colors = set(zip(*[iter(image)]*4))
        self.assertEqual(colors, {(255, 0, 0, 0), (0, 0, 255, 255)})

    def test_4_8_15bit_palette_and_bounds_and_window_addressing(self):
        # All three decoding paths resolve to green.  Bounds clamp 9 to 2;
        # texture window mask 1/off 0 maps u=9 to 1.
        green = 31 << 5
        p15 = self._vram([(2,0,green)])
        self.assertGreater(self._render(p15, uv=(9,0), limits=(2,0,2,0), depth=2)[1], 245)
        p8 = self._vram([(0,0,3 << 8), (515,0,green)])
        self.assertGreater(self._render(p8, uv=(1,0), depth=1)[1], 245)
        p4 = self._vram([(0,0,3 << 4), (515,0,green)])
        self.assertGreater(self._render(p4, uv=(9,0), depth=0, twin=(1,0,0,0))[1], 245)

    def test_constant_color_and_magnified_interiors_are_stable(self):
        p = self._vram([(x,y,0x3def) for y in range(4) for x in range(4)])
        image = self._render(p, uv=(1.1,1.1), step=(.04,.04))
        colors = set(zip(*[iter(image)]*4))
        self.assertEqual(len(colors), 1)
        # A hard edge may blend near its boundary, but broad texel interiors remain flat.
        p = self._vram([(x,0,0x001f if x == 0 else 0x7c00) for x in range(4)])
        image = self._render(p, uv=(0,0), step=(.125,0))
        row = [image[i:i+4] for i in range(0, self.W*4, 4)]
        self.assertGreater(sum(c == row[2] for c in row[1:7]), 3)

    def test_minified_checkerboard_is_smoother_than_nearest(self):
        p = self._vram([(x,y,0x7c00 if (x+y)&1 else 0x001f) for y in range(64) for x in range(64)])
        nearest = self._render(p, uv=(0,0), step=(2.3,1.7), filtering=0)
        filtered = self._render(p, uv=(0,0), step=(2.3,1.7), filtering=1)
        def variation(image):
            reds = image[0::4]
            return sum(abs(reds[y*self.W+x]-reds[y*self.W+x-1]) for y in range(self.H) for x in range(1,self.W))
        self.assertLess(variation(filtered), variation(nearest))

    def test_long_footprint_integrates_beyond_four_texels(self):
        # Period-8 stripes (4 red, 4 blue) seen 7 texels per pixel along x. A footprint
        # capped at 4 texels can land entirely inside one stripe; a 7-texel one cannot.
        p = self._vram([(x,y,0x001f if (x // 4) % 2 == 0 else 0x7c00) for y in range(4) for x in range(256)])
        image = self._render(p, uv=(0,0), step=(7,0))
        reds = image[0::4]
        self.assertTrue(all(64 < r < 192 for r in reds), sorted(set(reds)))

    def test_anisotropic_footprint_keeps_minor_axis_sharp(self):
        # Horizontal stripes, strongly minified along x only: rows must stay pure.
        p = self._vram([(x,y,0x001f if y % 2 == 0 else 0x7c00) for y in range(8) for x in range(256)])
        image = self._render(p, uv=(0,0.5), step=(6,0.1))
        pixels = list(zip(*[iter(image)]*4))
        pure = sum(1 for r, g, b, a in pixels if r > 245 and b < 10 or b > 245 and r < 10)
        self.assertGreater(pure, len(pixels) * 0.8)



LIT, FOG, LIMIT = 1, 2, 4
LIGHT_DIFFUSE = 1.5  # src/gte_lighting.glsl enhancement strength


def _context(matrix, back, scale, far, fog_range, mode):
    """One lighting context as the six RGBA32F texels lighting_gl.h uploads."""
    rows = []
    for i in range(3):
        rows.extend((*matrix[i], back[i]))
    return rows + [*scale, mode, *far, 0, *fog_range, 0, 0]


def _gte_colour(matrix, back, scale, far, light, ir0, mode):
    """src/gte_lighting_capture.h's colour model, per channel, in 0..255."""
    low = 0.0 if mode & LIMIT else -8.0
    y = list(light)
    if mode & LIT:
        x = [min(max(v, low), 8.0) for v in light]
        y = [min(max(back[i] + sum(matrix[i][k] * x[k] for k in range(3)), low), 8.0) for i in range(3)]
    if mode & FOG:
        y = [y[i] + (far[i] - y[i]) * ir0 for i in range(3)]
    return [min(max(scale[i] * y[i], 0.0), 255.0) for i in range(3)]


class GteLightingGL(TexturedShaderGL):
    """Per-pixel GTE lighting and fog in the textured shader."""
    WHITE = ((0, 0, 0x7fff),)
    MATRIX = ((0.5, 0.1, 0.0), (0.0, 0.6, 0.1), (0.2, 0.0, 0.4))
    BACK = (0.1, 0.05, 0.0)
    FAR = (0.02, 0.03, 0.04)

    def _pixel(self, image, x, y):
        offset = (y * self.W + x) * 4
        return image[offset:offset + 3]

    def _lit(self, light, *, context, **options):
        return self._render(self._vram(self.WHITE), raw=0, depth=2, world=0, filtering=0,
                            light=light, context=context, **options)

    def test_uniform_record_reproduces_the_pushed_vertex_colour(self):
        mode = LIT | FOG | LIMIT
        scale = (100.0, 90.0, 80.0)
        light, ir0 = (0.8, 0.3, -0.2), 0.25
        expected = _gte_colour(self.MATRIX, self.BACK, scale, self.FAR, light, ir0, mode)
        context = _context(self.MATRIX, self.BACK, scale, self.FAR, (300.0, 700.0), mode)
        lit = self._lit([(*light, 0, 0, 0, 1, ir0)] * 3, context=context, pixel_lighting=0,
                        smooth_fog=0)
        reference = self._render(self._vram(self.WHITE), raw=0, depth=2, world=0, filtering=0,
                                 colour=[c / 255 for c in expected])
        for a, b in zip(lit, reference):
            self.assertLessEqual(abs(a - b), 1)

    def test_smooth_fog_follows_depth_per_pixel(self):
        mode = FOG
        light, near, far = (0.25, 0.25, 0.25), 300.0, 700.0
        context = _context(self.MATRIX, self.BACK, (256.0,) * 3, (0.0,) * 3, (near, far), mode)
        sz = (200.0, 1000.0, 200.0)
        zdepth = [1.0 - 16.0 / z for z in sz]
        # Per-pixel lighting stays on: unlit depth-cued records have no normal.
        image = self._lit([(*light, 0, 0, 0, 0, 0.5)] * 3, context=context, zdepth=zdepth)
        flat = self._lit([(*light, 0, 0, 0, 0, 0.5)] * 3, context=context, zdepth=zdepth,
                         pixel_lighting=0, smooth_fog=0)
        for x in (0, 8, 16, 24, 31):
            depth = zdepth[0] + (zdepth[1] - zdepth[0]) * (x + 0.5) / self.W / 2
            t = min(max((16.0 / (1.0 - depth) - near) * 4096.0 / (far - near), 0.0), 4065.0) / 4096.0
            expected = 2 * 256.0 * 0.25 * (1.0 - t)
            self.assertLessEqual(abs(self._pixel(image, x, 0)[0] - expected), 2, x)
            self.assertLessEqual(abs(self._pixel(flat, x, 0)[0] - 2 * 256.0 * 0.25 * 0.5), 2, x)

    def test_pixel_lighting_clamps_and_renormalises_per_pixel(self):
        mode = LIT | LIMIT
        identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        context = _context(identity, (0.0,) * 3, (64.0,) * 3, (0.0,) * 3, (0.0, 0.0), mode)
        lights = [(1.0,) * 3 + (0, 0, 0, 1, 0), (-0.6,) * 3 + (0, 1, 0, 0, 0), (1.0,) * 3 + (0, 0, 0, 1, 0)]
        pixel = self._lit(lights, context=context)
        gouraud = self._lit(lights, context=context, pixel_lighting=0,
                        smooth_fog=0)
        x = self.W - 1
        w1 = (x + 0.5) / self.W / 2
        ln = (1 - w1) * 1.0 + w1 * -0.6
        expected = 2 * 64.0 * LIGHT_DIFFUSE * max(ln / (w1 * w1 + (1 - w1) * (1 - w1)) ** 0.5, 0.0)
        self.assertLessEqual(abs(self._pixel(pixel, x, 0)[0] - expected), 2)
        self.assertLessEqual(abs(self._pixel(gouraud, x, 0)[0] - 2 * 64.0 * (1 - w1)), 2)


if __name__ == "__main__":
    unittest.main()
