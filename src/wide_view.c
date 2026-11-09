/* Shadow Tower USA: widens what the game draws. A field-of-view setting, a
 * draw-distance setting, block culling that keeps up with a wider view, and
 * full-screen fills that reach the edges of the wide render surface. */
#include "function_overrides.h"
#include "gameplay_image.h"
#include "settings_ranges.h"

#include "cpu_state.h"
#include "gpu.h"
#include "mod_plugins.h"

#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern void gte_write_ctrl(struct CPUState *cpu, uint8_t reg, uint32_t val);

/* Rebuilds the live area light record from the area's table, every frame, near the top of RENDER. */
#define LIGHT_REFRESH 0x80033110u
#define LIGHT_REFRESH_RETURN 0x80026B6Cu
#define LIGHT_RECORD_POINTER 0x8017BE98u
#define LIGHT_FOG_NEAR 0x68u /* s16 depth where fog starts */
#define LIGHT_FOG_FAR 0x6Au  /* s16 depth of full fog; also the block cull radius */
/* Drops level blocks past the fog and, unless WEDGE_OFF is set, outside a view wedge. */
#define BLOCK_CULL 0x8001C60Cu
#define BLOCK_CULL_RETURN 0x80020CB8u
#define WEDGE_OFF 0x8017BEA5u
/* Draws one first-person arm in view space; RENDER calls it for each arm. */
#define ARM 0x80021AC4u
#define ARM_RETURN_FIRST 0x80026D1Cu
#define ARM_RETURN_SECOND 0x80026D24u
/* Draws a textured quad from (a0, a1) to (a2, a3); fades and flashes cover the screen with it. */
#define SCREEN_FILL 0x80021518u

#define GTE_H 26
#define STOCK_H 300
#define HALF_WIDTH 160.0
#define SCREEN_WIDTH 320
#define FOG_LIMIT 0x7FFF

static int fov = SHADOWTOWER_FOV_DEFAULT;
static int draw_distance = SHADOWTOWER_DRAW_DISTANCE_DEFAULT;
static uint32_t projection = STOCK_H;

/* Unset keeps the default; an invalid value keeps it and says why. */
static int read_setting(const char *name, int low, int high, int fallback) {
    const char *text = getenv(name);
    if (!text) return fallback;
    char *end;
    errno = 0;
    const long value = strtol(text, &end, 10);
    if (errno || end == text || *end || value < low || value > high) {
        fprintf(stderr, "Shadow Tower: invalid %s \"%s\"; use a whole number from %d to %d. Using %d.\n",
                name, text, low, high, fallback);
        return fallback;
    }
    return (int)value;
}

static int view_widened(void) {
    return fov > SHADOWTOWER_FOV_DEFAULT || draw_distance > SHADOWTOWER_DRAW_DISTANCE_DEFAULT ||
           psx_ws_x_margin() > 0;
}

static void scale_fog(uint32_t field) {
    const uint32_t record = psx_mod_read_word(LIGHT_RECORD_POINTER);
    const int32_t value = (int16_t)psx_mod_read_half(record + field);
    int32_t scaled = value * draw_distance / 100;
    if (scaled > FOG_LIMIT) scaled = FOG_LIMIT;
    psx_mod_write_half(record + field, (uint16_t)scaled);
}

static void light_refresh(struct CPUState *cpu) {
    const int main_render = cpu->gpr[31] == LIGHT_REFRESH_RETURN;
    if (!shadowtower_call_original(cpu, LIGHT_REFRESH) || !main_render) return;
    /* The game sets the projection once at start-up and screens that change it set their own.
     * Write it every frame, stock included, so a save state made at another FoV does not keep it. */
    gte_write_ctrl(cpu, GTE_H, projection);
    if (draw_distance == SHADOWTOWER_DRAW_DISTANCE_DEFAULT) return;
    scale_fog(LIGHT_FOG_NEAR);
    scale_fog(LIGHT_FOG_FAR);
}

/* The arms are posed for the stock projection; any other one moves them off their framing. */
static void arm(struct CPUState *cpu) {
    const uint32_t ra = cpu->gpr[31];
    if (ra != ARM_RETURN_FIRST && ra != ARM_RETURN_SECOND) {
        shadowtower_call_original(cpu, ARM);
        return;
    }
    gte_write_ctrl(cpu, GTE_H, STOCK_H);
    if (!shadowtower_call_original(cpu, ARM)) return;
    gte_write_ctrl(cpu, GTE_H, projection);
}

static void block_cull(struct CPUState *cpu) {
    if (cpu->gpr[31] != BLOCK_CULL_RETURN || !view_widened()) {
        shadowtower_call_original(cpu, BLOCK_CULL);
        return;
    }
    const uint8_t wedge_off = psx_mod_read_byte(WEDGE_OFF);
    psx_mod_write_byte(WEDGE_OFF, 1);
    if (!shadowtower_call_original(cpu, BLOCK_CULL)) return;
    if (psx_mod_read_byte(WEDGE_OFF) == 1) psx_mod_write_byte(WEDGE_OFF, wedge_off);
}

static void screen_fill(struct CPUState *cpu) {
    const int margin = psx_ws_x_margin();
    if (margin > 0 && (int16_t)cpu->gpr[4] <= 0 && (int16_t)cpu->gpr[6] >= SCREEN_WIDTH) {
        cpu->gpr[4] = (uint32_t)((int16_t)cpu->gpr[4] - margin);
        cpu->gpr[6] = (uint32_t)((int16_t)cpu->gpr[6] + margin);
    }
    shadowtower_call_original(cpu, SCREEN_FILL);
}

static int register_all(void) {
#define FINGERPRINT SHADOWTOWER_GAMEPLAY_FINGERPRINT
    int ok = shadowtower_register_override("wide-view.light-refresh", LIGHT_REFRESH,
                                           FINGERPRINT(LIGHT_REFRESH, 0x27BDFFE0u, 0x3C048019u), light_refresh);
    ok &= shadowtower_register_override("wide-view.arm", ARM, FINGERPRINT(ARM, 0x27BDFFB0u, 0xAFB30044u), arm);
    ok &= shadowtower_register_override("wide-view.block-cull", BLOCK_CULL,
                                        FINGERPRINT(BLOCK_CULL, 0x27BDFFC8u, 0x3C040001u), block_cull);
    ok &= shadowtower_register_override("wide-view.screen-fill", SCREEN_FILL,
                                        FINGERPRINT(SCREEN_FILL, 0x27BDFFE0u, 0x0080C821u), screen_fill);
#undef FINGERPRINT
    return ok;
}

PSX_MOD_CONSTRUCTOR(register_wide_view) {
    fov = read_setting("SHADOWTOWER_FOV", SHADOWTOWER_FOV_MIN, SHADOWTOWER_FOV_MAX, SHADOWTOWER_FOV_DEFAULT);
    draw_distance = read_setting("SHADOWTOWER_DRAW_DISTANCE", SHADOWTOWER_DRAW_DISTANCE_MIN,
                                 SHADOWTOWER_DRAW_DISTANCE_MAX, SHADOWTOWER_DRAW_DISTANCE_DEFAULT);
    if (fov != SHADOWTOWER_FOV_DEFAULT)
        projection = (uint32_t)lround(HALF_WIDTH / tan((double)fov * M_PI / 360.0));
    if (!register_all())
        fprintf(stderr, "Shadow Tower: wide view overrides could not be registered; the game draws its stock view.\n");
}
