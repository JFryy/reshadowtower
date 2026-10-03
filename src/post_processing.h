#pragma once
#include <math.h>
#include <stdio.h>
#include <string.h>

/* Launch-time display effects only; guest VRAM and game state stay untouched. */
typedef struct ShadowtowerPostFx {
    int enabled;
    float exposure, contrast, saturation, grain, dither, bloom, scanlines, mask, curvature;
} ShadowtowerPostFx;

/* Validate the complete launcher payload before enabling any effect. */
static int shadowtower_postfx_parse(const char *text, ShadowtowerPostFx *out) {
    const ShadowtowerPostFx neutral = {0, 0.f, 1.f, 1.f, 0.f, 0.f, 0.f, 0.f, 0.f, 0.f};
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
    const float low[] = {-2.f, .5f, 0.f, 0.f, 0.f, 0.f, 0.f, 0.f, 0.f};
    const float high[] = {2.f, 1.5f, 2.f, .2f, 1.f, 1.f, 1.f, 1.f, .2f};
    for (int i = 0; i < 9; ++i)
        if (!isfinite(values[i]) || values[i] < low[i] || values[i] > high[i]) return 0;
    value.enabled = 1;
    *out = value;
    return 1;
}
