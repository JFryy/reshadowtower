#include "frame_clock.h"

#include <stdio.h>

#define T(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s\n", #x); return 1; } } while (0)

int main(void) {
    /* Ticks every third VBlank of guest time, whatever the frame rate. */
    for (unsigned fps = 20; fps <= 240; fps += 4) {
        ShadowTowerTickClock clock = {0};
        const uint64_t frame = shadowtower_frame_cycles(fps);
        unsigned ticks = 0;
        for (uint64_t now = 1000; now < 1000 + 60ull * SHADOWTOWER_CPU_HZ; now += frame)
            ticks += (unsigned)shadowtower_tick_due(&clock, now);
        T(ticks >= 60 * 20 - 1 && ticks <= 60 * 20 + 1);
    }
    /* A stall yields one tick, not a catch-up burst, and the phase restarts. */
    ShadowTowerTickClock clock = {0};
    T(shadowtower_tick_due(&clock, 0));
    T(!shadowtower_tick_due(&clock, SHADOWTOWER_TICK_CYCLES - 1));
    T(shadowtower_tick_phase(&clock, SHADOWTOWER_TICK_CYCLES / 2) == .5f);
    T(shadowtower_tick_due(&clock, 10 * SHADOWTOWER_TICK_CYCLES));
    T(!shadowtower_tick_due(&clock, 10 * SHADOWTOWER_TICK_CYCLES + 1));
    T(clock.count == 2 && shadowtower_tick_phase(&clock, 10 * SHADOWTOWER_TICK_CYCLES) == 0.f);
    T(shadowtower_tick_phase(&clock, 12 * SHADOWTOWER_TICK_CYCLES) == 1.f);

    /* Positions blend linearly; angles take the short way round. */
    T(shadowtower_lerp(-100, 100, .25f) == -50);
    T(shadowtower_lerp(INT32_MAX - 10, INT32_MAX, 1.f) == INT32_MAX);
    T(shadowtower_angle_delta(4000, 100) == 196 && shadowtower_angle_delta(100, 4000) == -196);
    T((shadowtower_lerp_angle(4000, 100, .5f) & SHADOWTOWER_ANGLE_MASK) == 4098 % 4096);

    /* The cycle charge fits a stock frame's work into one unlocked frame. */
    T(shadowtower_cycle_scale(20) == 256 && shadowtower_cycle_scale(60) == 85 && shadowtower_cycle_scale(144) == 35);
    T(shadowtower_cycle_scale(10) == 256 && shadowtower_cycle_scale(10000) == 1);
    T(shadowtower_frame_cycles(60) == SHADOWTOWER_VBLANK_CYCLES);
    return 0;
}
