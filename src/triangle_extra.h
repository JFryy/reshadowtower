#ifndef SHADOWTOWER_TRIANGLE_EXTRA_H
#define SHADOWTOWER_TRIANGLE_EXTRA_H

#include <stdint.h>

#include "gte_lighting.h"

/* Per-vertex data that the 15-bit backend interface cannot carry. gpu.c
 * publishes it for the triangle it is about to draw, in that draw call's
 * vertex order; the GL renderer reads it while building the triangle and
 * clears it once the triangle is consumed. */
typedef struct {
    int valid;
    uint32_t rgb[3]; /* packet colours, 0x00BBGGRR */
    int has_depth;   /* every vertex has a nonzero GTE SZ from PGXP */
    uint16_t sz[3];
    const ShadowtowerLightVertex *light[3]; /* GTE lighting behind each colour, or NULL */
} ShadowtowerTriangleExtra;

extern ShadowtowerTriangleExtra g_shadowtower_triangle_extra;

#endif
