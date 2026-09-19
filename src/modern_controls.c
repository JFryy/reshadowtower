/* Shadow Tower USA: keyboard movement and direct player-camera mouse input. */
#include "modern_controls.h"
#include "mod_plugins.h"
#include "psx_keybinds.h"

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

static float mouse_sensitivity = 1.0f; /* PS1 angle units per relative mouse count */
static float pending_x, pending_y;
static Uint64 last_look, last_sample;
static SDL_Window *captured_window;
static int mouse_was_down, suppress_click;

/* Refuse camera writes when another disc executable occupies these addresses. */
static int gameplay_image_loaded(void) {
    return psx_mod_read_word(LOOK_UPDATE) == 0x27BDFFE8u &&
           psx_mod_read_word(LOOK_UPDATE + 4) == 0x3C02801Du &&
           psx_mod_read_word(0x80041EA4u) == 0xA4C3027Au &&
           psx_mod_read_word(0x80042088u) == 0xA6020278u;
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
    if (!gameplay_image_loaded()) return;
    const Uint64 now = SDL_GetTicks();
    last_look = now;
    if (!captured_window || SDL_GetKeyboardFocus() != captured_window ||
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
    pitch += dy;
    if (pitch > PITCH_LIMIT) pitch = PITCH_LIMIT;
    if (pitch < -PITCH_LIMIT) pitch = -PITCH_LIMIT;
    psx_mod_write_half(PLAYER_YAW, (uint16_t)((yaw - dx) & ANGLE_MASK));
    psx_mod_write_half(PLAYER_PITCH, (uint16_t)(pitch & ANGLE_MASK));
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
    if (captured_window && gameplay && !just_captured &&
        isfinite(dx) && isfinite(dy)) {
        /* Bound a single sample so focus changes cannot queue a full spin. */
        pending_x = fmaxf(-1024, fminf(1024, pending_x + dx * mouse_sensitivity));
        pending_y = fmaxf(-1024, fminf(1024, pending_y + dy * mouse_sensitivity));
        last_sample = now;
    } else {
        pending_x = pending_y = 0;
    }

    if (!focus) return 0xFFFF;
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
    if (keys[SDL_SCANCODE_W]) buttons &= (uint16_t)~0x0010u;
    if (keys[SDL_SCANCODE_S]) buttons &= (uint16_t)~0x0040u;
    if (keys[SDL_SCANCODE_A]) buttons &= (uint16_t)~(gameplay ? 0x0400u : 0x0080u);
    if (keys[SDL_SCANCODE_D]) buttons &= (uint16_t)~(gameplay ? 0x0800u : 0x0020u);
    if (keys[SDL_SCANCODE_E]) buttons &= (uint16_t)~0x4000u;
    if (keys[SDL_SCANCODE_F]) buttons &= (uint16_t)~0x1000u;
    if (keys[SDL_SCANCODE_C] || (!gameplay && keys[SDL_SCANCODE_ESCAPE]))
        buttons &= (uint16_t)~0x2000u;
    if (keys[SDL_SCANCODE_TAB]) buttons &= (uint16_t)~0x0001u;
    if (captured_window && gameplay && mouse_down && !suppress_click)
        buttons &= (uint16_t)~0x1000u;
    if (captured_window && gameplay && !just_captured &&
        (mouse_buttons & SDL_BUTTON_RMASK))
        buttons &= (uint16_t)~0x8000u;
    return buttons;
}

/* Read a launch-time sensitivity override without accepting invalid camera deltas. */
static void configure_mouse(void) {
    const char *value = getenv("SHADOWTOWER_MOUSE_SENSITIVITY");
    if (value) {
        char *end;
        errno = 0;
        const float sensitivity = strtof(value, &end);
        if (errno || end == value || *end || !isfinite(sensitivity) ||
            sensitivity < 0.05f || sensitivity > 10.0f) {
            fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_MOUSE_SENSITIVITY '%s'; "
                    "use a number from 0.05 to 10. Using default 1.0.\n", value);
        } else {
            mouse_sensitivity = sensitivity;
        }
    }
    /* Keep camera motion linear instead of applying desktop pointer acceleration. */
    if (!SDL_SetHint(SDL_HINT_MOUSE_RELATIVE_SYSTEM_SCALE, "0"))
        fprintf(stderr, "Shadow Tower: cannot disable system mouse scaling; "
                "check SDL_MOUSE_RELATIVE_SYSTEM_SCALE environment override.\n");
}

PSX_MOD_CONSTRUCTOR(register_shadow_tower_controls) {
    configure_mouse();
    if (!psx_mod_register_function_entry_plugin("shadowtower.mouse-look", LOOK_UPDATE, update_camera)) {
        fprintf(stderr, "Shadow Tower: camera hook registration failed; check duplicate plugin IDs.\n");
        abort();
    }
}
