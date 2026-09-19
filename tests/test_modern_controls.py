import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]

HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long long Uint64;
typedef unsigned int Uint32;
typedef unsigned short Uint16;
typedef unsigned char Uint8;
typedef struct SDL_Window { int id; } SDL_Window;
typedef int SDL_Scancode;
typedef unsigned int SDL_MouseButtonFlags;
#define SDL_NUM_SCANCODES 512
#define SDL_SCANCODE_ESCAPE 41
#define SDL_SCANCODE_W 26
#define SDL_SCANCODE_A 4
#define SDL_SCANCODE_S 22
#define SDL_SCANCODE_D 7
#define SDL_SCANCODE_E 8
#define SDL_SCANCODE_F 9
#define SDL_SCANCODE_C 6
#define SDL_SCANCODE_TAB 43
#define SDL_BUTTON_LMASK 1
#define SDL_BUTTON_RMASK 2
#define SDL_EVENT_KEY_DOWN 1
#define SDL_EVENT_WINDOW_FOCUS_LOST 2
#define SDL_HINT_MOUSE_RELATIVE_SYSTEM_SCALE "scale"
typedef struct { int type; struct { int scancode; } key; struct { int windowID; } window; } SDL_Event;
typedef struct CPUState CPUState;
SDL_Window win = {1}, other = {2}, *focus = &win;
Uint64 ticks = 100; float mx, my; unsigned int mb; uint16_t mem[0x200000];
bool event_available; SDL_Event event_value;
uint16_t pad_value; int pad_player; uint8_t pad_keys[SDL_NUM_SCANCODES];
Uint64 SDL_GetTicks(void) { return ticks; }
SDL_Window *SDL_GetKeyboardFocus(void) { return focus; }
unsigned int SDL_GetMouseState(float *x, float *y) { if (x) *x=0; if (y) *y=0; return mb; }
void SDL_GetRelativeMouseState(float *x, float *y) { *x=mx; *y=my; mx=my=0; }
int SDL_SetWindowRelativeMouseMode(SDL_Window *w, bool on) { (void)w; (void)on; return 1; }
int SDL_GetWindowID(SDL_Window *w) { return w->id; }
const char *SDL_GetError(void) { return "fake"; }
bool SDL_SetHint(const char *a, const char *b) { (void)a; (void)b; return true; }
bool SDL_PollEvent(SDL_Event *e) { if (!event_available) return false; *e=event_value; event_available=false; return true; }
uint16_t psx_keybinds_pad_word(const uint8_t *keys, int p) { pad_player=p; memcpy(pad_keys, keys, sizeof pad_keys); return pad_value; }
uint32_t psx_mod_read_word(uint32_t a) { if (a==0x80041D4c) return 0x27BDFFE8; if (a==0x80041D50) return 0x3C02801D; if (a==0x80041EA4) return 0xA4C3027A; if (a==0x80042088) return 0xA6020278; return 0; }
uint16_t psx_mod_read_half(uint32_t a) { return mem[(a-0x801991A0)/2]; }
void psx_mod_write_half(uint32_t a, uint16_t v) { mem[(a-0x801991A0)/2]=v; }
bool psx_mod_register_function_entry_plugin(const char*a,uint32_t b,void(*c)(CPUState*,uint32_t)) { return true; }
#define PSX_SDL3 1
#define PSX_MOD_CONSTRUCTOR(x) static void x(void) __attribute__((constructor)); static void x(void)
#include "src/modern_controls.c"
#define T(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s\n", #x); return 1; } } while (0)
static uint16_t poll(uint8_t *k, int p) { return shadowtower_pad_word(k,p); }
int main(void) {
    uint8_t keys[SDL_NUM_SCANCODES] = {0};
    const float expected_sensitivity =
        strcmp(getenv("SHADOWTOWER_MOUSE_SENSITIVITY"), "2") == 0 ? 2.0f : 1.0f;
    T(mouse_sensitivity == expected_sensitivity);
    last_look = last_sample = ticks;

    /* Non-player-one calls and unrelated bindings pass through. */
    pad_value = 0xBFFF;
    keys[100] = 1;
    T(poll(keys, 2) == pad_value && pad_player == 2);
    T(memcmp(pad_keys, keys, sizeof keys) == 0);
    T(poll(keys, 1) == pad_value && pad_keys[100] == 1);
    pad_value = 0xFFFF;
    keys[SDL_SCANCODE_W] = keys[SDL_SCANCODE_A] = 1;
    T(poll(keys, 1) == (uint16_t)(0xFFFF & ~0x0010 & ~0x0400));
    T(!pad_keys[SDL_SCANCODE_W] && !pad_keys[SDL_SCANCODE_A]);
    last_look = 0;
    T(poll(keys, 1) == (uint16_t)(0xFFFF & ~0x0010 & ~0x0080));
    memset(keys, 0, sizeof keys);

    /* RMB cannot capture or shield outside captured gameplay. */
    mb = SDL_BUTTON_RMASK;
    T(poll(keys, 1) == 0xFFFF && !captured_window);
    last_look = ticks;
    T(poll(keys, 1) == 0xFFFF && !captured_window);
    mb = SDL_BUTTON_LMASK;
    mx = 500;
    T(poll(keys, 1) == 0xFFFF && captured_window == &win);
    T(pending_x == 0); /* Discard pre-capture motion. */
    mx = 2;
    T(poll(keys, 1) == 0xFFFF); /* Capture click still cannot attack. */
    update_camera(NULL, 0);
    T(mem[1] == 4096 - (int)(2 * expected_sensitivity));
    mb = 0;
    poll(keys, 1);
    mb = SDL_BUTTON_LMASK;
    T(poll(keys, 1) == 0xEFFF);
    mb = SDL_BUTTON_RMASK;
    T(poll(keys, 1) == 0x7FFF); /* Square, not Triangle. */
    last_look = 0;
    mx = 100;
    T(poll(keys, 1) == 0xFFFF && pending_x == 0);

    /* Delivered Escape and focus events release and clear motion. */
    pending_x = 20;
    event_value = (SDL_Event){.type=SDL_EVENT_KEY_DOWN,
                             .key.scancode=SDL_SCANCODE_ESCAPE};
    event_available = true;
    T(shadowtower_poll_event(&event_value));
    T(!captured_window && pending_x == 0);
    last_look = ticks;
    mb = 0;
    poll(keys, 1);
    mb = SDL_BUTTON_LMASK;
    poll(keys, 1);
    T(captured_window == &win);
    event_value = (SDL_Event){.type=SDL_EVENT_WINDOW_FOCUS_LOST,
                             .window.windowID=2};
    event_available = true;
    shadowtower_poll_event(&event_value);
    T(captured_window == &win);
    event_value.window.windowID = 1;
    event_available = true;
    shadowtower_poll_event(&event_value);
    T(!captured_window);
    focus = NULL;
    T(poll(keys, 1) == 0xFFFF);
    focus = &win;

    /* Camera math preserves fractions, wraps yaw, and clamps signed pitch. */
    captured_window = &win;
    last_sample = ticks;
    pending_x = 0.75f;
    pending_y = -0.75f;
    mem[0] = mem[1] = 0;
    update_camera(NULL, 0);
    T(mem[0] == 0 && mem[1] == 0);
    pending_x += 0.5f;
    pending_y -= 0.5f;
    update_camera(NULL, 0);
    T(mem[0] == 4095 && mem[1] == 4095);
    T(pending_x == 0.25f && pending_y == -0.25f);
    pending_y = 1000;
    update_camera(NULL, 0);
    T(mem[0] == 700);
    pending_y = -2000;
    update_camera(NULL, 0);
    T(mem[0] == 4096 - 700);
    pending_x = 100;
    ticks += 101;
    update_camera(NULL, 0);
    T(pending_x == 0 && mem[1] == 4095);
    return 0;
}

'''


class ModernControls(unittest.TestCase):
    def test_regressions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "mod_plugins.h").write_text("")
            (path / "psx_keybinds.h").write_text("")
            (path / "psx_sdl.h").write_text("")
            source = HARNESS.replace('#include "src/modern_controls.c"', f'#include "{ROOT}/src/modern_controls.c"')
            (path / "h.c").write_text(source)
            executable = path / "h"
            subprocess.run(["cc", "-std=c11", "-I", directory, str(path / "h.c"), "-lm", "-o", str(executable)], check=True)
            result = subprocess.run([str(executable)], capture_output=True, text=True, check=True, env={**os.environ, "SHADOWTOWER_MOUSE_SENSITIVITY": "invalid"})
            self.assertIn("invalid SHADOWTOWER_MOUSE_SENSITIVITY", result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(executable)], check=True, env={**os.environ, "SHADOWTOWER_MOUSE_SENSITIVITY": "2"})


if __name__ == "__main__":
    unittest.main()
