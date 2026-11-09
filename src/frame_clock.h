#pragma once
/* Shadow Tower USA: the frame-rate unlock's logic clock and interpolation arithmetic. */
#include <math.h>
#include <stdint.h>

#define SHADOWTOWER_VBLANK_CYCLES 564480u
#define SHADOWTOWER_CPU_HZ (SHADOWTOWER_VBLANK_CYCLES * 60u)
/* The game simulates once per VSync(3): every third VBlank, 20 times a second. */
#define SHADOWTOWER_TICK_CYCLES (3u * SHADOWTOWER_VBLANK_CYCLES)
#define SHADOWTOWER_STOCK_FPS 20u
#define SHADOWTOWER_ANGLE_MASK 4095
#define SHADOWTOWER_STOCK_CYCLE_SCALE 256u

typedef struct ShadowTowerTickClock {
    uint64_t base;  /* guest cycle of the latest tick */
    uint32_t count; /* ticks since the clock started */
    int running;
} ShadowTowerTickClock;

/* Whether the loop iteration starting at `now` runs the simulation. After a
 * stall the clock skips ahead, so a stall costs one tick instead of a burst of
 * catch-up ticks. */
static inline int shadowtower_tick_due(ShadowTowerTickClock *clock, uint64_t now) {
    if (!clock->running) {
        clock->running = 1;
        clock->base = now;
        ++clock->count;
        return 1;
    }
    if (now - clock->base < SHADOWTOWER_TICK_CYCLES) return 0;
    clock->base += SHADOWTOWER_TICK_CYCLES;
    if (now - clock->base >= SHADOWTOWER_TICK_CYCLES) clock->base = now;
    ++clock->count;
    return 1;
}

/* How far `now` is between the latest tick and the next one, 0..1. */
static inline float shadowtower_tick_phase(const ShadowTowerTickClock *clock, uint64_t now) {
    const uint64_t elapsed = now - clock->base;
    if (elapsed >= SHADOWTOWER_TICK_CYCLES) return 1.f;
    return (float)elapsed / (float)SHADOWTOWER_TICK_CYCLES;
}

static inline int32_t shadowtower_lerp(int32_t from, int32_t to, float t) {
    return (int32_t)((int64_t)from + llroundf((float)((int64_t)to - from) * t));
}

/* Shortest signed step between two 12-bit PS1 angles. */
static inline int shadowtower_angle_delta(int from, int to) {
    return ((to - from + 2048) & SHADOWTOWER_ANGLE_MASK) - 2048;
}

static inline uint16_t shadowtower_lerp_angle(uint16_t from, uint16_t to, float t) {
    return (uint16_t)(from + (int)lroundf((float)shadowtower_angle_delta(from, to) * t));
}

/* Guest cycles between frames at `fps`. */
static inline uint64_t shadowtower_frame_cycles(unsigned fps) {
    return SHADOWTOWER_CPU_HZ / fps;
}

/* CPU cycle charge (of 256) that fits a stock 20 fps frame's work into one
 * frame at `fps`. */
static inline uint32_t shadowtower_cycle_scale(unsigned fps) {
    const uint32_t scale = SHADOWTOWER_STOCK_CYCLE_SCALE * SHADOWTOWER_STOCK_FPS / fps;
    if (scale < 1) return 1;
    return scale > SHADOWTOWER_STOCK_CYCLE_SCALE ? SHADOWTOWER_STOCK_CYCLE_SCALE : scale;
}
