#pragma once

/* Records the inputs behind each colour the GTE lighting and depth-cue ops
 * push, and follows those colours through SWC2 into RAM. Included once, by
 * the patched gte.cpp, which owns the storage. */

#include <cmath>
#include <cstring>

#include "gte.h"
#include "gte_lighting.h"

extern "C" uint8_t *memory_get_scratchpad_ptr(void);

ShadowtowerLightVertex g_shadowtower_light_ring[SHADOWTOWER_LIGHT_RING];
uint32_t g_shadowtower_light_words[SHADOWTOWER_LIGHT_WORDS];

static uint32_t s_light_next = 1;
static uint32_t s_light_fifo[3]; /* record ids shadowing RGB0..RGB2 */

static void light_fifo_push(uint32_t id) {
    s_light_fifo[0] = s_light_fifo[1];
    s_light_fifo[1] = s_light_fifo[2];
    s_light_fifo[2] = id;
}

/* Shadow Tower keeps its fog ramp as int32 SZ bounds in scratchpad. */
static float light_scratch_word(uint32_t offset) {
    const uint8_t *p = memory_get_scratchpad_ptr() + offset;
    return (float)(int32_t)((uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
                            (uint32_t)p[3] << 24);
}

/* The colour the record's model predicts; must match what the GTE pushed. */
static int light_model_matches(const ShadowtowerLightVertex *v) {
    const ShadowtowerLightContext *c = &v->context;
    const float low = (c->mode & SHADOWTOWER_LIGHT_LIMIT) ? 0.0f : -8.0f;
    for (int i = 0; i < 3; i++) {
        float y = v->light[i];
        if (c->mode & SHADOWTOWER_LIGHT_LIT) {
            y = c->back[i];
            for (int k = 0; k < 3; k++)
                y += c->matrix[i * 3 + k] * std::fmin(std::fmax(v->light[k], low), 8.0f);
            y = std::fmin(std::fmax(y, low), 8.0f);
        }
        if (c->mode & SHADOWTOWER_LIGHT_FOG) y += (c->far_colour[i] - y) * v->ir0;
        const float predicted = std::fmin(std::fmax(c->scale[i] * y, 0.0f), 255.0f);
        const float pushed = (float)((v->rgb >> (8 * i)) & 0xFFu);
        if (std::fabs(predicted - pushed) > 2.0f) return 0;
    }
    return 1;
}

/* Record one pushed colour; returns its id, or 0 when the model disagrees. */
static uint32_t light_capture_vertex(const PSXRecomp::GTE::GTEState *gte, const int16_t *normal,
                                     int mode, int uses_rgbc, uint32_t rgb) {
    const uint32_t id = s_light_next;
    ShadowtowerLightVertex *v = &g_shadowtower_light_ring[id % SHADOWTOWER_LIGHT_RING];
    std::memset(v, 0, sizeof(*v));
    v->rgb = rgb & 0xFFFFFFu;
    ShadowtowerLightContext *c = &v->context;
    c->mode = mode;
    for (int i = 0; i < 3; i++) {
        const float rgbc = (float)((gte->RGBC >> (8 * i)) & 0xFFu);
        c->scale[i] = uses_rgbc ? rgbc : 256.0f;
        c->back[i] = (float)gte->BK[i] / 4096.0f;
        c->far_colour[i] = (float)gte->FC[i] / 4096.0f;
        for (int k = 0; k < 3; k++) c->matrix[i * 3 + k] = (float)gte->LC[i][k] / 4096.0f;
        if (mode & SHADOWTOWER_LIGHT_LIT) {
            const int64_t mac = (int64_t)gte->L[i][0] * normal[0] + (int64_t)gte->L[i][1] * normal[1] +
                                (int64_t)gte->L[i][2] * normal[2];
            v->light[i] = (float)(mac >> 12) / 4096.0f;
            v->normal[i] = (float)normal[i] / 4096.0f;
        } else {
            v->light[i] = rgbc / 256.0f;
        }
    }
    if (mode & SHADOWTOWER_LIGHT_FOG) {
        c->fog_near = light_scratch_word(0x64);
        c->fog_far = light_scratch_word(0x68);
    }
    v->ir0 = (float)gte->IR0 / 4096.0f;
    if (!light_model_matches(v)) return 0;
    v->id = id;
    s_light_next = id + 1 == 0 ? 1 : id + 1;
    return id;
}

/* Call after a GTE command ran, before its state is exported. */
static void shadowtower_light_capture(const PSXRecomp::GTE::GTEState *gte, uint32_t cmd) {
    const int sf = (cmd >> 19) & 1;
    const int limit = (cmd >> 10) & 1 ? SHADOWTOWER_LIGHT_LIMIT : 0;
    int pushes = 0, mode = 0, uses_rgbc = 1;
    switch (cmd & 0x3F) {
    case 0x13: pushes = 1; mode = SHADOWTOWER_LIGHT_LIT | SHADOWTOWER_LIGHT_FOG; break; /* NCDS */
    case 0x16: pushes = 3; mode = SHADOWTOWER_LIGHT_LIT | SHADOWTOWER_LIGHT_FOG; break; /* NCDT */
    case 0x1B: pushes = 1; mode = SHADOWTOWER_LIGHT_LIT; break;                         /* NCCS */
    case 0x3F: pushes = 3; mode = SHADOWTOWER_LIGHT_LIT; break;                         /* NCCT */
    case 0x1E: pushes = 1; mode = SHADOWTOWER_LIGHT_LIT; uses_rgbc = 0; break;          /* NCS */
    case 0x20: pushes = 3; mode = SHADOWTOWER_LIGHT_LIT; uses_rgbc = 0; break;          /* NCT */
    case 0x10: pushes = 1; mode = SHADOWTOWER_LIGHT_FOG; uses_rgbc = 0; break;          /* DPCS */
    case 0x11: case 0x14: case 0x1C: case 0x29: case 0x3D: case 0x3E:
        pushes = 1; /* other colour ops: untracked */
        break;
    case 0x2A: pushes = 3; break; /* DPCT */
    default: return;
    }
    const int16_t *normals[3] = { gte->V0, gte->V1, gte->V2 };
    for (int i = 0; i < pushes; i++) {
        const uint32_t rgb = gte->RGB[3 - pushes + i];
        light_fifo_push(mode && sf ? light_capture_vertex(gte, normals[i], mode | limit, uses_rgbc, rgb)
                                   : 0);
    }
}

/* SWC2 of RGB0..RGB2: remember which record now lives in that RAM word. */
static void shadowtower_light_store(uint32_t addr, uint8_t reg) {
    if ((addr & 0x1FFFFFFFu) >= 0x800000u) return; /* scratchpad, I/O */
    g_shadowtower_light_words[(addr & 0x1FFFFCu) >> 2] = s_light_fifo[reg - 20];
}

/* A guest write to RGB0..RGB2 replaces the colour, so drop its record. */
static void shadowtower_light_register_written(uint8_t reg) {
    s_light_fifo[reg - 20] = 0;
}
