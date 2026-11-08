#pragma once
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "settings_ranges.h"

/* Launch-time display effects only; guest VRAM and game state stay untouched. */
typedef struct ShadowtowerPostFx {
    int enabled;
    float exposure, contrast, saturation, grain, dither, bloom, scanlines, mask, curvature;
} ShadowtowerPostFx;

/* Parse one optional advanced-effect strength, defaulting safely to off. */
static int shadowtower_postfx_strength(const char *text, float *out) {
    *out = SHADOWTOWER_POSTFX_UNIT_MIN;
    if (!text) return 1;
    float value;
    int consumed = 0;
    if (sscanf(text, "%f%n", &value, &consumed) != 1 || text[consumed] != '\0' ||
        !isfinite(value) || value < SHADOWTOWER_POSTFX_UNIT_MIN || value > SHADOWTOWER_POSTFX_UNIT_MAX) return 0;
    *out = value;
    return 1;
}

/* Validate the complete launcher payload before enabling any effect. */
static int shadowtower_postfx_parse(const char *text, ShadowtowerPostFx *out) {
    const ShadowtowerPostFx neutral = {
        0, SHADOWTOWER_POSTFX_EXPOSURE_DEFAULT, SHADOWTOWER_POSTFX_CONTRAST_DEFAULT,
        SHADOWTOWER_POSTFX_SATURATION_DEFAULT, SHADOWTOWER_POSTFX_GRAIN_MIN,
        SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_UNIT_MIN,
        SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_CURVATURE_MIN};
    *out = neutral;
    if (!text || strcmp(text, "0") == 0) return 1;
    ShadowtowerPostFx value = neutral;
    int consumed = 0;
    if (sscanf(text, "1,%f,%f,%f,%f,%f,%f,%f,%f,%f%n",
               &value.exposure, &value.contrast, &value.saturation,
               &value.grain, &value.dither, &value.bloom,
               &value.scanlines, &value.mask, &value.curvature, &consumed) != 9 ||
        text[consumed] != '\0') return 0;
    const float values[] = {value.exposure, value.contrast, value.saturation,
                            value.grain, value.dither, value.bloom,
                            value.scanlines, value.mask, value.curvature};
    const float low[] = {
        SHADOWTOWER_POSTFX_EXPOSURE_MIN, SHADOWTOWER_POSTFX_CONTRAST_MIN,
        SHADOWTOWER_POSTFX_SATURATION_MIN, SHADOWTOWER_POSTFX_GRAIN_MIN,
        SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_UNIT_MIN,
        SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_CURVATURE_MIN};
    const float high[] = {
        SHADOWTOWER_POSTFX_EXPOSURE_MAX, SHADOWTOWER_POSTFX_CONTRAST_MAX,
        SHADOWTOWER_POSTFX_SATURATION_MAX, SHADOWTOWER_POSTFX_GRAIN_MAX,
        SHADOWTOWER_POSTFX_UNIT_MAX, SHADOWTOWER_POSTFX_UNIT_MAX, SHADOWTOWER_POSTFX_UNIT_MAX,
        SHADOWTOWER_POSTFX_UNIT_MAX, SHADOWTOWER_POSTFX_CURVATURE_MAX};
    for (int i = 0; i < 9; ++i)
        if (!isfinite(values[i]) || values[i] < low[i] || values[i] > high[i]) return 0;
    value.enabled = 1;
    *out = value;
    return 1;
}
