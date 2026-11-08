#pragma once

#include <stdint.h>

/* GTE lighting kept for every colour the GTE pushes, so the renderer can
 * light and fog per pixel. Fixed-point GTE values are scaled so 4096 = 1.0;
 * colours are 0..255. A pushed colour reproduces as
 *   clamp(scale * mix(y, far_colour, ir0), 0, 255)
 * where y = clamp(back + matrix * clamp(light)) for lit records and
 * y = light for depth-cued vertex colours. */
enum {
    SHADOWTOWER_LIGHT_LIT = 1,   /* light holds L*n; NCS/NCCS/NCDS and triples */
    SHADOWTOWER_LIGHT_FOG = 2,   /* depth cued towards far_colour by IR0 */
    SHADOWTOWER_LIGHT_LIMIT = 4, /* lm: lighting terms clamp at zero */
};

typedef struct {
    float matrix[9];     /* light colour matrix LC, row major */
    float back[3];       /* background colour BK */
    float scale[3];      /* RGBC per channel, or 256 when the op ignores RGBC */
    float far_colour[3]; /* FC */
    float fog_near;      /* SZ where the game's fog ramp starts */
    float fog_far;       /* SZ where it reaches 4096 */
    int mode;
} ShadowtowerLightContext;

typedef struct {
    uint32_t id; /* 0 = empty slot */
    uint32_t rgb; /* pushed colour, 0x00BBGGRR */
    ShadowtowerLightContext context;
    float light[3];  /* L*n when lit, else the colour before depth cueing */
    float normal[3]; /* vertex normal; meaningful only when lit */
    float ir0;
} ShadowtowerLightVertex;

#define SHADOWTOWER_LIGHT_RING 65536u
#define SHADOWTOWER_LIGHT_WORDS (0x200000u >> 2)

#ifdef __cplusplus
extern "C" {
#endif
extern ShadowtowerLightVertex g_shadowtower_light_ring[SHADOWTOWER_LIGHT_RING];
/* Per 2 MB RAM word: id of the lighting record last stored there by SWC2. */
extern uint32_t g_shadowtower_light_words[SHADOWTOWER_LIGHT_WORDS];
#ifdef __cplusplus
}
#endif

/* Lighting record for the colour word at a RAM address, or NULL when the word
 * no longer holds the colour the GTE pushed for it. */
static inline const ShadowtowerLightVertex *shadowtower_light_lookup(uint32_t addr,
                                                                     uint32_t word) {
    const uint32_t id = g_shadowtower_light_words[(addr & 0x1FFFFCu) >> 2];
    if (id == 0) return 0;
    const ShadowtowerLightVertex *vertex = &g_shadowtower_light_ring[id % SHADOWTOWER_LIGHT_RING];
    return vertex->id == id && vertex->rgb == (word & 0xFFFFFFu) ? vertex : 0;
}
