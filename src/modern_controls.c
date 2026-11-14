/* Shadow Tower USA: keyboard movement and direct player-camera mouse and right-stick input. */
#include "modern_controls.h"
#include "keyboard_bindings.h"
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

/* Pad bits in the framework's button order (keyboard_bindings.h rows). */
static const uint16_t button_bits[] = {
    PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_CROSS, PAD_CIRCLE, PAD_SQUARE, PAD_TRIANGLE,
    PAD_L1, PAD_R1, 0x0100u /* L2 */, 0x0200u /* R2 */, 0x0002u /* L3 */, 0x0004u /* R3 */,
    0x0008u /* Start */, PAD_SELECT,
};

static int keyboard_loaded;
static SDL_Scancode strafe_keys[SHADOWTOWER_STRAFE_ROWS][2]; /* primary, alternate */
static uint16_t mouse_bits[SHADOWTOWER_MOUSE_ROWS];         /* 0 leaves the button unbound */

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

_Static_assert(sizeof button_bits / sizeof button_bits[0] == SHADOWTOWER_BUTTON_ROWS,
               "one pad bit per keyboard_bindings.h button row");

/* keybinds.ini is ASCII; plain comparisons avoid locale tables indexed by file bytes. */
static int blank(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
static char lower(char c) { return c >= 'A' && c <= 'Z' ? (char)(c - 'A' + 'a') : c; }

static void trim(char *text) {
    size_t length = strlen(text);
    while (length && blank(text[length - 1])) text[--length] = '\0';
    size_t start = 0;
    while (blank(text[start])) ++start;
    memmove(text, text + start, length - start + 1);
}

static int same_name(const char *a, const char *b) {
    for (; *a && *b; ++a, ++b)
        if (lower(*a) != lower(*b)) return 0;
    return !*a && !*b;
}

static SDL_Scancode key_from_name(const char *name) {
    return name && *name && !same_name(name, "None") ? SDL_GetScancodeFromName(name) : SDL_SCANCODE_UNKNOWN;
}

/* Pad bit for a PlayStation button key such as "triangle"; 0 for None, -1 when unknown. */
static int bit_from_name(const char *name) {
    if (!*name || same_name(name, "None")) return 0;
    for (size_t i = 0; i < SHADOWTOWER_BUTTON_ROWS; ++i)
        if (same_name(name, shadowtower_button_rows[i].key)) return button_bits[i];
    return -1;
}

/* Parse "Key" or "Key, Second key"; returns 0 when a name is not an SDL key. */
static int parse_keys(char *value, SDL_Scancode keys[2]) {
    char *second = strchr(value, ',');
    if (second) *second++ = '\0';
    trim(value);
    keys[0] = key_from_name(value);
    keys[1] = SDL_SCANCODE_UNKNOWN;
    if (second) {
        trim(second);
        keys[1] = key_from_name(second);
    }
    return (keys[0] != SDL_SCANCODE_UNKNOWN || !*value || same_name(value, "None")) &&
           (!second || keys[1] != SDL_SCANCODE_UNKNOWN || !*second || same_name(second, "None"));
}

static void apply_action(const char *key, char *value) {
    for (size_t i = 0; i < SHADOWTOWER_STRAFE_ROWS; ++i) {
        if (!same_name(key, shadowtower_strafe_rows[i].key)) continue;
        SDL_Scancode keys[2];
        if (!parse_keys(value, keys)) {
            fprintf(stderr, "Shadow Tower: keybinds.ini %s has an unknown key; keeping the default.\n", key);
            return;
        }
        memcpy(strafe_keys[i], keys, sizeof keys);
        return;
    }
    for (size_t i = 0; i < SHADOWTOWER_MOUSE_ROWS; ++i) {
        if (!same_name(key, shadowtower_mouse_rows[i].key)) continue;
        trim(value);
        const int bit = bit_from_name(value);
        if (bit < 0) {
            fprintf(stderr, "Shadow Tower: keybinds.ini %s = %s is not a PlayStation button; "
                    "keeping the default.\n", key, value);
            return;
        }
        mouse_bits[i] = (uint16_t)bit;
        return;
    }
}

/* Read the [shadowtower] section of <base>/keybinds.ini. */
static int load_actions(const char *base) {
    for (size_t i = 0; i < SHADOWTOWER_STRAFE_ROWS; ++i) {
        strafe_keys[i][0] = key_from_name(shadowtower_strafe_rows[i].primary);
        strafe_keys[i][1] = key_from_name(shadowtower_strafe_rows[i].alt);
    }
    for (size_t i = 0; i < SHADOWTOWER_MOUSE_ROWS; ++i)
        mouse_bits[i] = (uint16_t)bit_from_name(shadowtower_mouse_rows[i].primary);
    if (!base) return 0;
    char path[1024];
    snprintf(path, sizeof path, "%skeybinds.ini", base);
    FILE *file = fopen(path, "r");
    if (!file) {
        if (errno != ENOENT)
            fprintf(stderr, "Shadow Tower: cannot read %s: %s; using default keys.\n", path, strerror(errno));
        return 0;
    }
    int found = 0, in_section = 0;
    char line[256];
    while (fgets(line, sizeof line, file)) {
        trim(line);
        if (!line[0] || line[0] == '#' || line[0] == ';') continue;
        if (line[0] == '[') {
            char *end = strchr(line, ']');
            if (end) *end = '\0';
            in_section = same_name(line + 1, "shadowtower");
            found |= in_section;
            continue;
        }
        char *equals = strchr(line, '=');
        if (!in_section || !equals) continue;
        *equals = '\0';
        trim(line);
        apply_action(line, equals + 1);
    }
    fclose(file);
    return found;
}

/* A [player1] still holding the framework's generated defaults gets the Shadow Tower layout. */
static void apply_default_layout(void) {
    for (size_t i = 0; i < SHADOWTOWER_BUTTON_ROWS; ++i) {
        const ShadowTowerKeyRow *row = &shadowtower_button_rows[i];
        if (strcmp(psx_keybinds_button_name((int)i), row->key) != 0) {
            fprintf(stderr, "Shadow Tower: keyboard button %zu is '%s', expected '%s'; "
                    "keeping keybinds.ini as written.\n", i, psx_keybinds_button_name((int)i), row->key);
            return;
        }
        if (psx_keybinds_get_button(1, (int)i) != key_from_name(row->framework) ||
            psx_keybinds_get_button_alt(1, (int)i) != SDL_SCANCODE_UNKNOWN)
            return;
    }
    /* Setting a key unbinds it from every other row, the hidden left-stick rows included, so
     * unchanged rows are skipped to keep Left/Right on the stick. Up/Down move to the d-pad. */
    for (size_t i = 0; i < SHADOWTOWER_BUTTON_ROWS; ++i) {
        SDL_Scancode primary = key_from_name(shadowtower_button_rows[i].primary);
        SDL_Scancode alt = key_from_name(shadowtower_button_rows[i].alt);
        if (psx_keybinds_get_button(1, (int)i) != primary) psx_keybinds_set_button(1, (int)i, primary);
        if (alt != SDL_SCANCODE_UNKNOWN) psx_keybinds_set_button_alt(1, (int)i, alt);
    }
}

/* Runs on the first pad read, after the framework's own keyboard setup. */
static void load_keyboard(void) {
    keyboard_loaded = 1;
    const char *base = SDL_GetBasePath();
    if (base) {
        /* The framework finds keybinds.ini from argv[0] but treats an executable name without
         * an extension as a directory, so on Linux and macOS it never reads the file. */
        psx_keybinds_init(base);
    } else {
        fprintf(stderr, "Shadow Tower: cannot locate keybinds.ini (%s); using default keys.\n", SDL_GetError());
    }
    if (!load_actions(base)) apply_default_layout();
}

static int strafe_held(const uint8_t *keys, size_t row) {
    return (strafe_keys[row][0] != SDL_SCANCODE_UNKNOWN && keys[strafe_keys[row][0]]) ||
           (strafe_keys[row][1] != SDL_SCANCODE_UNKNOWN && keys[strafe_keys[row][1]]);
}

/* Sample SDL on the existing main-thread keyboard path; retain gamepad merging. */
uint16_t shadowtower_pad_word(const uint8_t *keys, int player) {
    if (!keys || player != 1) return psx_keybinds_pad_word(keys, player);
    if (!keyboard_loaded) load_keyboard();
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
    /* Strafe keys and Escape belong to the game, never to a [player1] button. */
    original_keys[SDL_SCANCODE_ESCAPE] = 0;
    for (size_t i = 0; i < SHADOWTOWER_STRAFE_ROWS; ++i)
        for (int slot = 0; slot < 2; ++slot)
            if (strafe_keys[i][slot] != SDL_SCANCODE_UNKNOWN) original_keys[strafe_keys[i][slot]] = 0;
    uint16_t buttons = psx_keybinds_pad_word(original_keys, player);
    if (strafe_held(keys, 0)) buttons &= (uint16_t)~(gameplay ? PAD_L1 : PAD_LEFT);
    if (strafe_held(keys, 1)) buttons &= (uint16_t)~(gameplay ? PAD_R1 : PAD_RIGHT);
    if (!gameplay && keys[SDL_SCANCODE_ESCAPE]) buttons &= (uint16_t)~PAD_CIRCLE;
    if (captured_window && gameplay && mouse_down && !suppress_click)
        buttons &= (uint16_t)~mouse_bits[0];
    if (captured_window && gameplay && !just_captured &&
        (mouse_buttons & SDL_BUTTON_RMASK))
        buttons &= (uint16_t)~mouse_bits[1];
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
