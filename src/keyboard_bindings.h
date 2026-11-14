/* Shadow Tower keyboard layout shared by the runtime and the launcher.
 *
 * keybinds.ini [player1] binds keys to PlayStation buttons (read by the framework).
 * keybinds.ini [shadowtower] holds the game's context-dependent actions: strafe keys
 * press L1/R1 in gameplay and Left/Right in menus, and each captured mouse button
 * presses one PlayStation button during gameplay.
 *
 * A file with no [shadowtower] section whose [player1] buttons still hold the
 * framework's generated defaults has never been edited, so it gets this layout. */
#pragma once

typedef struct ShadowTowerKeyRow {
    const char *key;       /* keybinds.ini key */
    const char *label;     /* launcher label */
    const char *primary;   /* default SDL scancode name (mouse rows: button key); NULL = None */
    const char *alt;       /* default second key; NULL = none */
    const char *framework; /* framework-generated default for [player1] rows; NULL = None */
} ShadowTowerKeyRow;

/* Same order as the framework's PsxKeybindButton enum. */
static const ShadowTowerKeyRow shadowtower_button_rows[] = {
    {"up", "Move forward", "W", "Up", "Up"},
    {"down", "Move back", "S", "Down", "Down"},
    {"left", "Turn left", "Left", 0, "Left"},
    {"right", "Turn right", "Right", 0, "Right"},
    {"cross", "Interact (Cross)", "E", "X", "X"},
    {"circle", "Inventory / back (Circle)", "C", 0, "S"},
    {"square", "Shield (Square)", "Z", 0, "Z"},
    {"triangle", "Attack (Triangle)", "F", 0, "A"},
    {"l1", "L1", "Q", 0, "Q"},
    {"r1", "R1", 0, 0, "W"},
    {"l2", "L2", 0, 0, "E"},
    {"r2", "R2", "R", 0, "R"},
    {"l3", "L3", "T", 0, "T"},
    {"r3", "R3", "Y", 0, "Y"},
    {"start", "Pause (Start)", "Return", 0, "Return"},
    {"select", "Main menu (Select)", "Tab", "Right Shift", "Right Shift"},
};

static const ShadowTowerKeyRow shadowtower_strafe_rows[] = {
    {"strafe_left", "Strafe left", "A", 0, 0},
    {"strafe_right", "Strafe right", "D", 0, 0},
};

static const ShadowTowerKeyRow shadowtower_mouse_rows[] = {
    {"mouse_left", "Left mouse button", "triangle", 0, 0},
    {"mouse_right", "Right mouse button", "square", 0, 0},
};

#define SHADOWTOWER_BUTTON_ROWS (sizeof shadowtower_button_rows / sizeof shadowtower_button_rows[0])
#define SHADOWTOWER_STRAFE_ROWS (sizeof shadowtower_strafe_rows / sizeof shadowtower_strafe_rows[0])
#define SHADOWTOWER_MOUSE_ROWS (sizeof shadowtower_mouse_rows / sizeof shadowtower_mouse_rows[0])

/* Escape releases the mouse; the rest are host hotkeys. Key names containing a comma are also
 * refused because the comma separates two keys in keybinds.ini. */
static const char *const shadowtower_reserved_keys[] = {
    "Escape", "Keypad +", "Keypad -", "F6", "F7", "F8", "F9", "F10",
};
