#pragma once

#define SHADOWTOWER_MAX_INTERNAL_SCALE 8

/* Bound canonical VRAM targets by both texture and depth/stencil limits. */
static inline int shadowtower_scale_for_limits(int requested, int texture_limit, int renderbuffer_limit) {
    int limit = texture_limit < renderbuffer_limit ? texture_limit : renderbuffer_limit;
    limit /= 1024;
    if (limit < 1) return 0;
    if (requested < 1) requested = 1;
    if (requested > SHADOWTOWER_MAX_INTERNAL_SCALE) requested = SHADOWTOWER_MAX_INTERNAL_SCALE;
    return requested < limit ? requested : limit;
}

/* Retry substantially smaller targets instead of repeatedly exhausting VRAM. */
static inline int shadowtower_lower_scale(int scale) {
    return scale > 4 ? 4 : scale > 2 ? 2 : scale > 1 ? 1 : 0;
}
