/* Shadow Tower USA: keyboard movement and direct player-camera mouse and right-stick input. */
#include "modern_controls.h"
#include "mod_plugins.h"
#include "psx_keybinds.h"
#include "settings_ranges.h"

#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if !defined(PSX_SDL3)
#error "Shadow Tower modern controls currently require SDL3"
#endif

#define LOOK_UPDATE 0x80041D4Cu
#define PLAYER_PITCH 0x801991A0u
#define PLAYER_YAW 0x801991A2u
#define ANGLE_MASK 4095
#define PITCH_LIMIT 700
#define STICK_RATE 2048.0f /* PS1 angle units per second at full deflection */
#define STICK_MAX_STEP_MS 50

static float mouse_sensitivity = (float)SHADOWTOWER_MOUSE_SENSITIVITY_DEFAULT; /* PS1 angle units per relative mouse count */
static float pending_x, pending_y;
static float stick_sensitivity = (float)SHADOWTOWER_STICK_SENSITIVITY_DEFAULT; /* multiplier on STICK_RATE */
static float stick_deadzone = (float)SHADOWTOWER_STICK_DEADZONE_DEFAULT; /* fraction of full deflection */
static Uint64 last_look, last_sample, last_stick;
static int applied_yaw, applied_pitch; /* angle change the last look update made */
static SDL_Window *captured_window;
static int mouse_was_down, suppress_click;

/* Active-low PSX pad bits: a pressed button clears its bit. */
#define PAD_NONE_PRESSED 0xFFFFu
#define PAD_SELECT 0x0001u
#define PAD_UP 0x0010u
#define PAD_RIGHT 0x0020u
#define PAD_DOWN 0x0040u
#define PAD_LEFT 0x0080u
#define PAD_L1 0x0400u
#define PAD_R1 0x0800u
#define PAD_TRIANGLE 0x1000u
#define PAD_CIRCLE 0x2000u
#define PAD_CROSS 0x4000u
#define PAD_SQUARE 0x8000u

typedef struct CodeWord {
    uint32_t address, expected;
} CodeWord;

static const CodeWord gameplay_fingerprint[] = {
    {LOOK_UPDATE, 0x27BDFFE8u},     /* addiu sp,sp,-24 */
    {LOOK_UPDATE + 4, 0x3C02801Du}, /* lui v0,0x801D */
    {0x80041EA4u, 0xA4C3027Au},     /* sh v1,0x27A(a2) */
    {0x80042088u, 0xA6020278u},     /* sh v0,0x278(s0) */
};

/* Refuse camera writes when another disc executable occupies these addresses. */
static int gameplay_image_loaded(void) {
    static int reported;
    for (size_t i = 0; i < sizeof gameplay_fingerprint / sizeof gameplay_fingerprint[0]; ++i) {
        const uint32_t found = psx_mod_read_word(gameplay_fingerprint[i].address);
        if (found == gameplay_fingerprint[i].expected) continue;
        if (!reported) {
            reported = 1;
            fprintf(stderr, "Shadow Tower: gameplay code at 0x%08X does not match "
                    "(found 0x%08X, expected 0x%08X); camera look paused while it differs.\n",
                    gameplay_fingerprint[i].address, found, gameplay_fingerprint[i].expected);
        }
        return 0;
    }
    return 1;
}

static void release_mouse(void) {
    if (captured_window && !SDL_SetWindowRelativeMouseMode(captured_window, false))
        fprintf(stderr, "Shadow Tower: cannot release mouse: %s\n", SDL_GetError());
    captured_window = NULL;
    pending_x = pending_y = 0;
    suppress_click = 1;
}

/* Event handling catches quick Escape taps between guest input samples. */
bool shadowtower_poll_event(SDL_Event *event) {
    const bool available = SDL_PollEvent(event);
    if (!available || !event || !captured_window) return available;
    if ((event->type == SDL_EVENT_KEY_DOWN && event->key.scancode == SDL_SCANCODE_ESCAPE) ||
        (event->type == SDL_EVENT_WINDOW_FOCUS_LOST &&
         event->window.windowID == SDL_GetWindowID(captured_window)))
        release_mouse();
    return available;
}

/* Runs at the original look routine, not during arbitrary guest VBlanks. */
static void update_camera(struct CPUState *cpu, uint32_t address) {
    (void)cpu;
    (void)address;
    applied_yaw = applied_pitch = 0;
    if (!gameplay_image_loaded()) return;
    const Uint64 now = SDL_GetTicks();
    last_look = now;
    SDL_Window *focus = SDL_GetKeyboardFocus();
    if (!focus || (captured_window && focus != captured_window) ||
        now - last_sample > 100) {
        pending_x = pending_y = 0;
        return;
    }
    const int dx = (int)pending_x;
    const int dy = (int)pending_y;
    pending_x -= (float)dx;
    pending_y -= (float)dy;
    if (!dx && !dy) return;

    const int yaw = psx_mod_read_half(PLAYER_YAW);
    int pitch = psx_mod_read_half(PLAYER_PITCH);
    if (yaw > ANGLE_MASK || pitch > ANGLE_MASK) {
        pending_x = pending_y = 0;
        return;
    }
    if (pitch > 2047) pitch -= 4096;
    const int old_pitch = pitch;
    pitch += dy;
    if (pitch > PITCH_LIMIT) pitch = PITCH_LIMIT;
    if (pitch < -PITCH_LIMIT) pitch = -PITCH_LIMIT;
    applied_yaw = -dx;
    applied_pitch = pitch - old_pitch;
    psx_mod_write_half(PLAYER_YAW, (uint16_t)((yaw - dx) & ANGLE_MASK));
    psx_mod_write_half(PLAYER_PITCH, (uint16_t)(pitch & ANGLE_MASK));
}

void shadowtower_look_render_offset(float behind, int *yaw, int *pitch) {
    *yaw = (int)lroundf(behind * (float)applied_yaw);
    *pitch = (int)lroundf(behind * (float)applied_pitch);
    SDL_Window *focus = SDL_GetKeyboardFocus();
    if (!focus || (captured_window && focus != captured_window) || SDL_GetTicks() - last_sample > 100)
        return;
    *yaw -= (int)pending_x;
    *pitch += (int)pending_y;
}

/* Radial deadzone with the remaining travel rescaled to 0..1. */
static void stick_deflection(Sint16 raw_x, Sint16 raw_y, float *x, float *y) {
    const float sx = raw_x / 32767.0f;
    const float sy = raw_y / 32767.0f;
    const float magnitude = sqrtf(sx * sx + sy * sy);
    *x = *y = 0;
    if (magnitude <= stick_deadzone) return;
    const float scaled = fminf(1, (magnitude - stick_deadzone) / (1 - stick_deadzone));
    *x = sx / magnitude * scaled;
    *y = sy / magnitude * scaled;
}

/* First gamepad the framework has opened; SDL_GetGamepadFromID never opens one itself. */
static SDL_Gamepad *open_gamepad(void) {
    int count = 0;
    SDL_JoystickID *ids = SDL_GetGamepads(&count);
    if (!ids) return NULL;
    SDL_Gamepad *gamepad = NULL;
    for (int i = 0; i < count && !gamepad; ++i)
        gamepad = SDL_GetGamepadFromID(ids[i]);
    SDL_free(ids);
    return gamepad;
}

/* Right-stick rate in angle units for the time since the previous sample. */
static int sample_stick(Uint64 now, int active, float *dx, float *dy) {
    *dx = *dy = 0;
    const Uint64 elapsed = last_stick ? now - last_stick : 0;
    last_stick = now;
    if (!active) return 0;
    SDL_Gamepad *gamepad = open_gamepad();
    if (!gamepad) return 0;
    float x, y;
    stick_deflection(SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_RIGHTX),
                     SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_RIGHTY), &x, &y);
    if (!x && !y) return 0;
    const float seconds = (elapsed > STICK_MAX_STEP_MS ? STICK_MAX_STEP_MS : elapsed) / 1000.0f;
    *dx = x * STICK_RATE * stick_sensitivity * seconds;
    *dy = y * STICK_RATE * stick_sensitivity * seconds;
    return 1;
}

/* Sample SDL on the existing main-thread keyboard path; retain gamepad merging. */
uint16_t shadowtower_pad_word(const uint8_t *keys, int player) {
    if (!keys || player != 1) return psx_keybinds_pad_word(keys, player);
    SDL_Window *focus = SDL_GetKeyboardFocus();
    const Uint64 now = SDL_GetTicks();
    const int gameplay = last_look && now - last_look < 200 && gameplay_image_loaded();
    const SDL_MouseButtonFlags mouse_buttons = SDL_GetMouseState(NULL, NULL);
    const int mouse_down = (mouse_buttons & SDL_BUTTON_LMASK) != 0;
    int just_captured = 0;

    if (captured_window && (focus != captured_window || keys[SDL_SCANCODE_ESCAPE]))
        release_mouse();
    if (!mouse_down) suppress_click = 0;
    if (!captured_window && focus && gameplay && mouse_down && !mouse_was_down &&
        !keys[SDL_SCANCODE_ESCAPE]) {
        if (SDL_SetWindowRelativeMouseMode(focus, true)) {
            captured_window = focus;
            just_captured = 1;
            suppress_click = 1; /* The click that captures must not swing a weapon. */
        } else {
            fprintf(stderr, "Shadow Tower: cannot capture mouse: %s\n", SDL_GetError());
        }
    }
    mouse_was_down = mouse_down;

    float dx = 0, dy = 0;
    SDL_GetRelativeMouseState(&dx, &dy);
    const int mouse_look = captured_window && gameplay && !just_captured &&
                           isfinite(dx) && isfinite(dy);
    if (mouse_look) {
        dx *= mouse_sensitivity;
        dy *= mouse_sensitivity;
    } else {
        dx = dy = 0;
    }
    float stick_x, stick_y;
    const int stick_look = sample_stick(now, focus && gameplay, &stick_x, &stick_y);
    if (stick_look) {
        dx += stick_x;
        dy += stick_y;
    }
    if (mouse_look || stick_look) {
        /* Bound a single sample so focus changes cannot queue a full spin. */
        pending_x = fmaxf(-1024, fminf(1024, pending_x + dx));
        pending_y = fmaxf(-1024, fminf(1024, pending_y + dy));
        last_sample = now;
    } else {
        pending_x = pending_y = 0;
    }

    if (!focus) return PAD_NONE_PRESSED;
    uint8_t original_keys[SDL_NUM_SCANCODES];
    memcpy(original_keys, keys, sizeof original_keys);
    const SDL_Scancode remapped[] = {
        SDL_SCANCODE_W, SDL_SCANCODE_A, SDL_SCANCODE_S, SDL_SCANCODE_D,
        SDL_SCANCODE_E, SDL_SCANCODE_F, SDL_SCANCODE_C, SDL_SCANCODE_TAB,
        SDL_SCANCODE_ESCAPE
    };
    for (size_t i = 0; i < sizeof remapped / sizeof remapped[0]; ++i)
        original_keys[remapped[i]] = 0;
    uint16_t buttons = psx_keybinds_pad_word(original_keys, player);
    if (keys[SDL_SCANCODE_W]) buttons &= (uint16_t)~PAD_UP;
    if (keys[SDL_SCANCODE_S]) buttons &= (uint16_t)~PAD_DOWN;
    if (keys[SDL_SCANCODE_A]) buttons &= (uint16_t)~(gameplay ? PAD_L1 : PAD_LEFT);
    if (keys[SDL_SCANCODE_D]) buttons &= (uint16_t)~(gameplay ? PAD_R1 : PAD_RIGHT);
    if (keys[SDL_SCANCODE_E]) buttons &= (uint16_t)~PAD_CROSS;
    if (keys[SDL_SCANCODE_F]) buttons &= (uint16_t)~PAD_TRIANGLE;
    if (keys[SDL_SCANCODE_C] || (!gameplay && keys[SDL_SCANCODE_ESCAPE]))
        buttons &= (uint16_t)~PAD_CIRCLE;
    if (keys[SDL_SCANCODE_TAB]) buttons &= (uint16_t)~PAD_SELECT;
    if (captured_window && gameplay && mouse_down && !suppress_click)
        buttons &= (uint16_t)~PAD_TRIANGLE;
    if (captured_window && gameplay && !just_captured &&
        (mouse_buttons & SDL_BUTTON_RMASK))
        buttons &= (uint16_t)~PAD_SQUARE;
    return buttons;
}

/* Read a launch-time float override, keeping the default when it is missing or out of range. */
static void read_setting(const char *name, float min, float max, float *target) {
    const char *value = getenv(name);
    if (!value) return;
    char *end;
    errno = 0;
    const float parsed = strtof(value, &end);
    if (errno || end == value || *end || !isfinite(parsed) || parsed < min || parsed > max) {
        fprintf(stderr, "Shadow Tower: invalid %s '%s'; use a number from %g to %g. "
                "Using default %g.\n", name, value, min, max, *target);
        return;
    }
    *target = parsed;
}

static void configure_look(void) {
    read_setting("SHADOWTOWER_MOUSE_SENSITIVITY", (float)SHADOWTOWER_MOUSE_SENSITIVITY_MIN, (float)SHADOWTOWER_MOUSE_SENSITIVITY_MAX,
                  &mouse_sensitivity);
    read_setting("SHADOWTOWER_STICK_SENSITIVITY", (float)SHADOWTOWER_STICK_SENSITIVITY_MIN, (float)SHADOWTOWER_STICK_SENSITIVITY_MAX,
                  &stick_sensitivity);
    read_setting("SHADOWTOWER_STICK_DEADZONE", (float)SHADOWTOWER_STICK_DEADZONE_MIN, (float)SHADOWTOWER_STICK_DEADZONE_MAX,
                  &stick_deadzone);
    /* Keep camera motion linear instead of applying desktop pointer acceleration. */
    if (!SDL_SetHint(SDL_HINT_MOUSE_RELATIVE_SYSTEM_SCALE, "0"))
        fprintf(stderr, "Shadow Tower: cannot disable system mouse scaling; "
                "check SDL_MOUSE_RELATIVE_SYSTEM_SCALE environment override.\n");
}

PSX_MOD_CONSTRUCTOR(register_shadow_tower_controls) {
    configure_look();
    if (!psx_mod_register_function_entry_plugin("shadowtower.mouse-look", LOOK_UPDATE, update_camera)) {
        fprintf(stderr, "Shadow Tower: camera hook registration failed; check duplicate plugin IDs.\n");
        abort();
    }
}
