#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PSX_SDL3 1
#include "psx_sdl.h"
typedef struct CPUState CPUState;
static int window_token, other_window_token;
SDL_Window *win = (SDL_Window *)&window_token;
SDL_Window *other = (SDL_Window *)&other_window_token;
SDL_Window *focus = (SDL_Window *)&window_token;
Uint64 ticks = 100; float mx, my; unsigned int mb; uint16_t mem[0x200000];
bool event_available; SDL_Event event_value;
uint16_t pad_value; int pad_player; uint8_t pad_keys[SDL_NUM_SCANCODES];
static int gamepad_token; int gamepad_open; Sint16 rx, ry;
SDL_JoystickID *SDL_GetGamepads(int *count) {
    static SDL_JoystickID ids[1] = {7};
    SDL_JoystickID *copy = malloc(sizeof ids);
    memcpy(copy, ids, sizeof ids);
    *count = 1;
    return copy;
}
SDL_Gamepad *SDL_GetGamepadFromID(SDL_JoystickID id) { return gamepad_open && id == 7 ? (SDL_Gamepad *)&gamepad_token : NULL; }
Sint16 SDL_GetGamepadAxis(SDL_Gamepad *g, SDL_GamepadAxis a) { (void)g; return a == SDL_GAMEPAD_AXIS_RIGHTX ? rx : a == SDL_GAMEPAD_AXIS_RIGHTY ? ry : 0; }
void SDL_free(void *p) { if (p) free(p); }
Uint64 SDL_GetTicks(void) { return ticks; }
SDL_Window *SDL_GetKeyboardFocus(void) { return focus; }
unsigned int SDL_GetMouseState(float *x, float *y) { if (x) *x=0; if (y) *y=0; return mb; }
SDL_MouseButtonFlags SDL_GetRelativeMouseState(float *x, float *y) { *x=mx; *y=my; mx=my=0; return mb; }
bool SDL_SetWindowRelativeMouseMode(SDL_Window *w, bool on) { (void)w; (void)on; return 1; }
SDL_WindowID SDL_GetWindowID(SDL_Window *w) { return w == win ? 1 : 2; }
const char *SDL_GetError(void) { return "fake"; }
bool SDL_SetHint(const char *a, const char *b) { (void)a; (void)b; return true; }
bool SDL_PollEvent(SDL_Event *e) { if (!event_available) return false; *e=event_value; event_available=false; return true; }
/* A small framework keyboard: [player1] binds per button, applied by pad_word. */
static const char *const button_names[] = {"up", "down", "left", "right", "cross", "circle", "square", "triangle",
                                           "l1", "r1", "l2", "r2", "l3", "r3", "start", "select"};
static const uint16_t stub_bits[] = {0x10, 0x40, 0x80, 0x20, 0x4000, 0x2000, 0x8000, 0x1000,
                                     0x400, 0x800, 0x100, 0x200, 0x2, 0x4, 0x8, 0x1};
SDL_Scancode bind[16][2];
static const struct { const char *name; SDL_Scancode code; } key_names[] = {
    {"A", SDL_SCANCODE_A}, {"C", SDL_SCANCODE_C}, {"D", SDL_SCANCODE_D}, {"E", SDL_SCANCODE_E},
    {"F", SDL_SCANCODE_F}, {"Q", SDL_SCANCODE_Q}, {"R", SDL_SCANCODE_R}, {"S", SDL_SCANCODE_S},
    {"T", SDL_SCANCODE_T}, {"W", SDL_SCANCODE_W}, {"X", SDL_SCANCODE_X}, {"Y", SDL_SCANCODE_Y},
    {"Z", SDL_SCANCODE_Z}, {"Up", SDL_SCANCODE_UP}, {"Down", SDL_SCANCODE_DOWN}, {"Left", SDL_SCANCODE_LEFT},
    {"Right", SDL_SCANCODE_RIGHT}, {"Return", SDL_SCANCODE_RETURN}, {"Tab", SDL_SCANCODE_TAB},
    {"Right Shift", SDL_SCANCODE_RSHIFT},
};
SDL_Scancode SDL_GetScancodeFromName(const char *name) {
    if (!name) return SDL_SCANCODE_UNKNOWN;
    for (size_t i = 0; i < sizeof key_names / sizeof key_names[0]; ++i)
        if (!strcmp(name, key_names[i].name)) return key_names[i].code;
    return SDL_SCANCODE_UNKNOWN;
}
const char *SDL_GetBasePath(void) { const char *dir = getenv("KEYBINDS_DIR"); return dir ? dir : "/nonexistent/"; }
char keybinds_dir[1024];
void psx_keybinds_init(const char *path) { snprintf(keybinds_dir, sizeof keybinds_dir, "%s", path); }
const char *psx_keybinds_button_name(int b) { return button_names[b]; }
SDL_Scancode psx_keybinds_get_button(int p, int b) { (void)p; return bind[b][0]; }
SDL_Scancode psx_keybinds_get_button_alt(int p, int b) { (void)p; return bind[b][1]; }
void psx_keybinds_set_button(int p, int b, SDL_Scancode sc) { (void)p; bind[b][0] = sc; }
void psx_keybinds_set_button_alt(int p, int b, SDL_Scancode sc) { (void)p; bind[b][1] = sc; }
uint16_t psx_keybinds_pad_word(const uint8_t *keys, int p) {
    pad_player=p;
    uint16_t word = pad_value;
    if (!keys) return word;
    memcpy(pad_keys, keys, sizeof pad_keys);
    for (int b = 0; b < 16; ++b)
        if ((bind[b][0] && keys[bind[b][0]]) || (bind[b][1] && keys[bind[b][1]])) word &= (uint16_t)~stub_bits[b];
    return word;
}
int wrong_code;
uint32_t psx_mod_read_word(uint32_t a) { if (wrong_code && a==0x80041EA4) return 0xDEADBEEF; if (a==0x80041D4c) return 0x27BDFFE8; if (a==0x80041D50) return 0x3C02801D; if (a==0x80041EA4) return 0xA4C3027A; if (a==0x80042088) return 0xA6020278; return 0; }
uint16_t psx_mod_read_half(uint32_t a) { return mem[(a-0x801991A0)/2]; }
void psx_mod_write_half(uint32_t a, uint16_t v) { mem[(a-0x801991A0)/2]=v; }
bool psx_mod_register_function_entry_plugin(const char*a,uint32_t b,void(*c)(CPUState*,uint32_t)) { (void)a; (void)b; (void)c; return true; }
#define PSX_MOD_CONSTRUCTOR(x) static void x(void) __attribute__((constructor)); static void x(void)
#include "modern_controls.c"
#define T(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s\n", #x); return 1; } } while (0)
static uint16_t poll(uint8_t *k, int p) { return shadowtower_pad_word(k,p); }

/* KEYBINDS_DIR holds a keybinds.ini with a [shadowtower] section; [player1] stays as the framework read it. */
static int custom_keybinds(uint8_t *keys) {
    pad_value = 0xFFFF;
    last_look = last_sample = ticks;
    poll(keys, 1);
    const char *dir = getenv("KEYBINDS_DIR");
    T(dir && !strcmp(keybinds_dir, dir)); /* Framework reloads from the executable's directory. */
    T(bind[0][0] == SDL_SCANCODE_UP && bind[7][0] == SDL_SCANCODE_A); /* No default layout over edits. */
    keys[SDL_SCANCODE_T] = 1; /* strafe_left = T, Q */
    T(poll(keys, 1) == (uint16_t)(0xFFFF & ~0x0400) && !pad_keys[SDL_SCANCODE_T]);
    keys[SDL_SCANCODE_T] = 0;
    keys[SDL_SCANCODE_D] = 1; /* Invalid strafe_right keeps D. */
    T(poll(keys, 1) == (uint16_t)(0xFFFF & ~0x0800));
    keys[SDL_SCANCODE_D] = 0;
    mb = SDL_BUTTON_LMASK;
    poll(keys, 1);
    mb = 0;
    poll(keys, 1);
    mb = SDL_BUTTON_LMASK;
    T(captured_window == win && poll(keys, 1) == 0xBFFF); /* mouse_left = cross */
    mb = SDL_BUTTON_RMASK;
    T(poll(keys, 1) == 0xFFFF); /* mouse_right = None */
    return 0;
}

int main(void) {
    uint8_t keys[SDL_NUM_SCANCODES] = {0};
    for (int b = 0; b < 16; ++b) bind[b][0] = key_from_name(shadowtower_button_rows[b].framework);
    if (getenv("KEYBINDS_DIR")) return custom_keybinds(keys);
    const char *sensitivity_env = getenv("SHADOWTOWER_MOUSE_SENSITIVITY");
    T(sensitivity_env != NULL);
    const int custom = strcmp(sensitivity_env, "2") == 0;
    const float expected_sensitivity = custom ? 2.0f : 1.0f;
    T(mouse_sensitivity == expected_sensitivity);
    T(stick_sensitivity == (custom ? 2.0f : 1.0f));
    T(stick_deadzone == (custom ? 0.25f : 0.15f));
    last_look = last_sample = ticks;

    /* Non-player-one calls and unrelated bindings pass through. */
    pad_value = 0xBFFF;
    keys[100] = 1;
    T(poll(keys, 2) == pad_value && pad_player == 2);
    T(memcmp(pad_keys, keys, sizeof keys) == 0);
    T(poll(keys, 1) == pad_value && pad_keys[100] == 1);
    pad_value = 0xFFFF;
    keys[100] = 0;

    /* An untouched framework [player1] gets the Shadow Tower layout. */
    T(bind[0][0] == SDL_SCANCODE_W && bind[0][1] == SDL_SCANCODE_UP);
    T(bind[4][0] == SDL_SCANCODE_E && bind[4][1] == SDL_SCANCODE_X);
    T(bind[5][0] == SDL_SCANCODE_C && bind[7][0] == SDL_SCANCODE_F);
    T(bind[9][0] == SDL_SCANCODE_UNKNOWN && bind[10][0] == SDL_SCANCODE_UNKNOWN);
    T(bind[15][0] == SDL_SCANCODE_TAB && bind[15][1] == SDL_SCANCODE_RSHIFT);
    keys[SDL_SCANCODE_E] = 1;
    T(poll(keys, 1) == 0xBFFF);
    keys[SDL_SCANCODE_E] = 0;

    keys[SDL_SCANCODE_W] = keys[SDL_SCANCODE_A] = 1;
    T(poll(keys, 1) == (uint16_t)(0xFFFF & ~0x0010 & ~0x0400));
    T(pad_keys[SDL_SCANCODE_W] && !pad_keys[SDL_SCANCODE_A]);
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
    T(poll(keys, 1) == 0xFFFF && captured_window == win);
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
    event_value = (SDL_Event){.key={.type=SDL_EVENT_KEY_DOWN,
                                  .scancode=SDL_SCANCODE_ESCAPE}};
    event_available = true;
    T(shadowtower_poll_event(&event_value));
    T(!captured_window && pending_x == 0);
    last_look = ticks;
    mb = 0;
    poll(keys, 1);
    mb = SDL_BUTTON_LMASK;
    poll(keys, 1);
    T(captured_window == win);
    event_value = (SDL_Event){.window={.type=SDL_EVENT_WINDOW_FOCUS_LOST,
                                     .windowID=2}};
    event_available = true;
    shadowtower_poll_event(&event_value);
    T(captured_window == win);
    event_value.window.windowID = 1;
    event_available = true;
    shadowtower_poll_event(&event_value);
    T(!captured_window);
    focus = NULL;
    T(poll(keys, 1) == 0xFFFF);
    focus = win;

    /* Camera math preserves fractions, wraps yaw, and clamps signed pitch. */
    captured_window = win;
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

    /* Right stick looks without mouse capture, at a frame-rate independent rate. */
    captured_window = NULL;
    pending_x = pending_y = 0;
    mem[0] = mem[1] = 0;
    gamepad_open = 1;
    last_look = ticks;
    poll(keys, 1);
    rx = (Sint16)(0.1f * 32767); /* Inside both deadzones. */
    ticks += 16;
    T(poll(keys, 1) == 0xFFFF && pending_x == 0 && pending_y == 0);
    rx = 32767;
    ry = 0;
    ticks += 16;
    T(poll(keys, 1) == 0xFFFF);
    const float full_step = STICK_RATE * stick_sensitivity * 0.016f;
    T(fabsf(pending_x - full_step) < 0.01f && pending_y == 0);
    last_look = ticks;
    update_camera(NULL, 0);
    T(mem[1] == 4096 - (int)full_step && mem[0] == 0);
    pending_x = 0;
    rx = 0;
    ry = -32767; /* Up decreases pitch like upward mouse motion. */
    ticks += 1000; /* A stalled sample cannot queue more than one capped step. */
    last_look = ticks;
    poll(keys, 1);
    T(fabsf(pending_y + STICK_RATE * stick_sensitivity * STICK_MAX_STEP_MS / 1000.0f) < 0.01f);

    /* Stick look needs gameplay, focus, and an opened gamepad. */
    ry = 32767;
    last_look = 0;
    ticks += 16;
    poll(keys, 1);
    T(pending_x == 0 && pending_y == 0);
    last_look = ticks;
    focus = NULL;
    ticks += 16;
    poll(keys, 1);
    T(pending_y == 0);
    focus = win;
    gamepad_open = 0;
    ticks += 16;
    poll(keys, 1);
    T(pending_y == 0);

    /* Digital movement still works while the stick is deflected. */
    gamepad_open = 1;
    keys[SDL_SCANCODE_A] = 1;
    ticks += 16;
    T(poll(keys, 1) == (uint16_t)(0xFFFF & ~0x0400) && pending_y > 0);
    keys[SDL_SCANCODE_A] = 0;

    /* Stick down raises the stored pitch, matching downward mouse motion. */
    pending_x = pending_y = 0;
    mem[0] = 0;
    ticks += 16;
    poll(keys, 1);
    update_camera(NULL, 0);
    T(mem[0] == (int)(STICK_RATE * stick_sensitivity * 0.016f));

    /* The capturing click drops stale mouse motion but keeps the stick. */
    ry = 0;
    rx = 32767;
    pending_x = pending_y = 0;
    mb = SDL_BUTTON_LMASK;
    mx = 500;
    mouse_was_down = 0;
    ticks += 16;
    poll(keys, 1);
    T(captured_window == win && fabsf(pending_x - full_step) < 0.01f);

    /* Captured mouse and stick motion add together. */
    mx = 10;
    ticks += 16;
    poll(keys, 1);
    T(fabsf(pending_x - (2 * full_step + 10 * mouse_sensitivity)) < 0.01f);

    /* A foreign executable at the hook addresses disables look and logs once. */
    wrong_code = 1;
    pending_x = 5;
    last_look = 0;
    update_camera(NULL, 0);
    update_camera(NULL, 0);
    T(last_look == 0 && pending_x == 5);
    last_look = ticks;
    poll(keys, 1);
    return 0;
}
