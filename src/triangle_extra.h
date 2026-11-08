#ifndef SHADOWTOWER_TRIANGLE_EXTRA_H
#define SHADOWTOWER_TRIANGLE_EXTRA_H

#include <stdint.h>

/* Per-vertex data that the 15-bit backend interface cannot carry. gpu.c
 * publishes it for the triangle it is about to draw, in that draw call's
 * vertex order; the GL renderer reads it while building the triangle and
 * clears it once the triangle is consumed. */
typedef struct {
    int valid;
    uint32_t rgb[3]; /* packet colours, 0x00BBGGRR */
} ShadowtowerTriangleExtra;

extern ShadowtowerTriangleExtra g_shadowtower_triangle_extra;

#endif
