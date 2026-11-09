/* Shadow Tower USA: frame-rate unlock. The game simulates at its stock 20 Hz
 * while frames between ticks redraw the world with an interpolated camera and
 * interpolated objects, paced in guest time so speed and audio stay stock. */
#include "frame_unlock.h"
#include "frame_clock.h"
#include "function_overrides.h"
#include "gameplay_image.h"
#include "modern_controls.h"
#include "renderer_options.h"
#include "settings_ranges.h"

#include "cpu_state.h"
#include "host_time.h"
#include "interrupts.h"
#include "mod_plugins.h"
#include "psx_cycles.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* CPU cycle charge per 256 executed cycles, defined by patches/runtime-cycles.patch
 * and applied by patches/runtime-cycle-charge.patch. */
extern uint32_t g_shadowtower_cycle_scale;
extern uint32_t g_shadowtower_cycle_carry;

/* Gameplay executable (ST.EXE at 0x80011000): the main loop and its render path. */
#define LOOP_HEAD 0x800164B4u /* first main-loop call: frame-rate statistics */
#define LOOP_HEAD_RETURN 0x80014BDCu
#define RENDER 0x80026AFCu
#define RENDER_RETURN 0x80014C50u
#define TEXTURE_ANIMATION 0x80016A14u /* steps VRAM texture and palette animation */
#define TEXTURE_ANIMATION_RETURN 0x80026B38u
#define FLIP 0x800175A4u /* DrawSync(0), VSync(3), PutDispEnv, PutDrawEnv */
#define FLIP_RETURN 0x80017690u
#define VSYNC 0x80077104u
#define VSYNC_RETURN 0x800175C4u /* the VSync(3) call inside FLIP */
#define VSYNC_COUNT 0x80087BD0u      /* VBlanks counted by the BIOS handler */
#define VSYNC_LAST_COUNT 0x80086AA4u /* VSync's count at its last return; VSync(n) waits from it */
#define VSYNC_LAST_HCOUNT 0x80086AA0u
#define VSYNC_HCOUNT_POINTER 0x80086A9Cu /* points at the root counter VSync reads */
#define FRAME_WAIT 0x8001535Cu /* waits for a root-counter tick after the flip */
#define FRAME_WAIT_RETURN 0x80026DA0u
#define DRAW_MODEL 0x80022678u /* draws one model at (pos, rot) for every entity pool */

#define RENDER_COUNTER 0x8017BD50u /* u8: frames drawn this second */
/* Hit and blind flashes: two channels the simulation accumulates into and RENDER draws once,
 * then clears (0x8002181C, 0x800218D8). */
#define FLASH_STATE 0x8017BD66u
#define FLASH_STATE_BYTES 16u
/* Fourth entity pool: steps a shared counter and each entry's animation frame on every draw. */
#define ANIMATED_POOL 0x800255F0u
#define ANIMATED_POOL_RETURN 0x80026D64u
#define ANIMATED_POOL_COUNTER 0x8015C488u
#define ANIMATED_POOL_FRAMES 0x8018E31Fu /* u8 per entry */
#define ANIMATED_POOL_ENTRIES 128u
#define ANIMATED_POOL_STRIDE 0x18u
/* Full-screen transition: steps once per draw and switches state after 16 steps. */
#define TRANSITION 0x80028784u
#define TRANSITION_RETURN 0x80026D90u
#define TRANSITION_STATE 0x8017BEA6u
#define TRANSITION_STATE_BYTES 4u
#define VBLANK_FLAG 0x8008820Cu    /* set by the root-counter callback, cleared by FRAME_WAIT */
#define LOOP_FLAG 0x80199144u      /* u8 the main loop clears in a delay slot every iteration */
#define AREA_LOADING 0x801B5920u   /* s16: nonzero while an area loads */

#define PLAYER 0x80198F28u
#define PLAYER_POSITION (PLAYER + 0x248u) /* s32 x, y, z */
#define PLAYER_EYE (PLAYER + 0x2CEu)      /* s16 eye offsets at +0x2CE and +0x2D2 */
#define PLAYER_EYE_SECOND (PLAYER + 0x2D2u)
#define PLAYER_ANGLES (PLAYER + 0x268u) /* u16 pitch, yaw, roll the view is built from */
#define PLAYER_BASE_PITCH (PLAYER + 0x278u)
#define EYE_HEIGHT 0x640
#define PITCH_LIMIT 700

#define GATE_COUNT 10
#define ENTITY_SLOT_BITS 11 /* 2048 slots, above the 624 entities the pools hold */
#define ENTITY_SLOTS (1u << ENTITY_SLOT_BITS)
#define FRAME_DRAWS 1024u
#define TEMPORARY_SPAN 0x400u /* caller stack a draw call's temporary position may sit in */
#define SCRATCHPAD 0x1F800000u
#define SCRATCHPAD_END 0x1F800400u
#define CAMERA_TELEPORT 0x800
#define DEFAULT_TELEPORT 0x800
/* The main loop must reach its head again within this many ticks. */
#define WATCHDOG_TICKS 4u
/* Consecutive iterations with a hook missing before the unlock is disabled; a
 * save-state load cuts one iteration short. */
#define WATCHDOG_MISSES 3u
/* Host lag past which the guest and wall clocks are re-anchored (a stall or a save-state load). */
#define REANCHOR_SECONDS 0.25

typedef struct Gate {
    const char *id;
    uint32_t address, return_address;
    uint32_t entry[2];
} Gate;

/* Main-loop simulation calls, run only on ticks. None of them draws a gameplay
 * frame; the states that do present on their own go through FLIP elsewhere. */
static const Gate gates[GATE_COUNT] = {
    {"frame-unlock.input-reset", 0x80016508u, 0x80014BE4u, {0x3C030001u, 0x34638000u}},
    {"frame-unlock.player", 0x80042D74u, 0x80014BECu, {0x27BDFF18u, 0x24040001u}},
    {"frame-unlock.sim-50768", 0x80050768u, 0x80014BF4u, {0x27BDFF60u, 0x3C02801Cu}},
    {"frame-unlock.sim-4e324", 0x8004E324u, 0x80014BFCu, {0x3C02801Au, 0x8C45909Cu}},
    {"frame-unlock.sim-53aa4", 0x80053AA4u, 0x80014C04u, {0x27BDFFA8u, 0x3C02801Du}},
    {"frame-unlock.sim-3bc40", 0x8003BC40u, 0x80014C0Cu, {0x27BDFFD8u, 0x3C028019u}},
    {"frame-unlock.sim-5735c", 0x8005735Cu, 0x80014C14u, {0x3C02801Bu, 0x8C42592Cu}},
    {"frame-unlock.area-load", 0x800456F8u, 0x80014C1Cu, {0x3C02801Bu, 0x84435920u}},
    {"frame-unlock.sim-45ffc", 0x80045FFCu, 0x80014C3Cu, {0x27BDFFD8u, 0x3C028009u}},
    {"frame-unlock.sim-58620", 0x80058620u, 0x80014C44u, {0x27BDFFD8u, 0x3C028009u}},
};
#define LOOP_FLAG_GATE 6 /* sim-5735c: entered after the delay slot cleared LOOP_FLAG */

enum {
    SEEN_RENDER = 1u << GATE_COUNT,
    SEEN_TEXTURE_ANIMATION = SEEN_RENDER << 1,
    SEEN_VSYNC = SEEN_RENDER << 2,
    SEEN_FRAME_WAIT = SEEN_RENDER << 3,
    SEEN_ALL = (SEEN_RENDER << 4) - 1,
};

enum { POOL_A, POOL_B, POOL_C, POOL_D1, POOL_D2, POOL_OTHER, POOL_COUNT };
static const char *const pool_names[POOL_COUNT] = {"A", "B", "C", "D1", "D2", "other"};
static const int32_t pool_teleport[POOL_COUNT] = {
    DEFAULT_TELEPORT, 0x2000, DEFAULT_TELEPORT, DEFAULT_TELEPORT, DEFAULT_TELEPORT, DEFAULT_TELEPORT};

typedef struct Camera {
    int32_t position[3];
    int16_t eye[2];
    uint16_t angle[3];
} Camera;

typedef struct Entity {
    uint32_t key; /* guest address of the entity's position; 0 = free */
    uint32_t tick;
    uint16_t model;
    int32_t previous[3], current[3];
    uint16_t previous_angle[3], current_angle[3];
} Entity;

typedef struct Draw {
    int32_t current[3], drawn[3];
} Draw;

typedef struct Stats {
    uint32_t iterations, ticks, flips, dropped, camera, objects, teleports, temporaries;
    int32_t max_step[POOL_COUNT];
    uint64_t render_ns, present_ns; /* host time in guest rendering and in presenting */
} Stats;

static int enabled, smooth_camera, smooth_objects, probe;
static unsigned target_fps = SHADOWTOWER_TARGET_FPS_DEFAULT;
static uint64_t frame_cycles;
static uint32_t cycle_scale = SHADOWTOWER_STOCK_CYCLE_SCALE;

static int engaged, tick, in_main_render;
static uint32_t seen, missed_iterations;
static ShadowTowerTickClock clock_state;
static float phase;
static uint64_t next_frame, last_loop_head, last_main_flip, last_present;
static uint8_t saved_loop_flag;
static uint8_t flash_state[FLASH_STATE_BYTES];
static int flash_saved;
static uint64_t anchor_wall_ns, anchor_guest;
static uint64_t present_ns; /* this frame's present, excluded from its render time */

static Camera camera_previous, camera_current; /* the last two ticks */
static Camera camera_real, camera_drawn; /* to restore once the frame is drawn */
static int camera_valid, camera_written;
static Entity entities[ENTITY_SLOTS];
static Draw draws[FRAME_DRAWS];
static uint32_t draw_count;

static Stats stats;
static uint64_t last_report_ms;

static uint64_t now_cycles(void) { return psx_get_cycle_count(); }

static void reset_smoothing(void) {
    camera_valid = 0;
    flash_saved = 0;
    memset(entities, 0, sizeof entities);
}

static void disengage(const char *reason) {
    if (!engaged) return;
    engaged = 0;
    tick = 0;
    g_shadowtower_cycle_scale = SHADOWTOWER_STOCK_CYCLE_SCALE;
    g_shadowtower_cycle_carry = 0;
    if (probe) fprintf(stderr, "Shadow Tower: frame unlock paused: %s; stock pacing.\n", reason);
}

static void disable(const char *reason) {
    disengage(reason);
    if (!enabled) return;
    enabled = 0;
    fprintf(stderr, "Shadow Tower: frame unlock disabled: %s. The game runs with stock pacing.\n", reason);
}

static void report(void) {
    const uint64_t now = psx_host_mono_ms();
    if (!last_report_ms) last_report_ms = now;
    if (now - last_report_ms < 1000) return;
    const double seconds = (double)(now - last_report_ms) / 1000.0;
    fprintf(stderr, "Shadow Tower: frame unlock: %.1f ticks/s, %.1f frames/s, %u dropped, %u loop iterations; "
            "camera smoothed %u, objects %u (%u teleports, %u temporaries); cycle scale %u/256; "
            "host ms per frame: render %.2f, present %.2f; max step per tick:",
            stats.ticks / seconds, stats.flips / seconds, stats.dropped, stats.iterations, stats.camera,
            stats.objects, stats.teleports, stats.temporaries, g_shadowtower_cycle_scale,
            stats.flips ? stats.render_ns / 1e6 / stats.flips : 0.0,
            stats.flips ? stats.present_ns / 1e6 / stats.flips : 0.0);
    for (int i = 0; i < POOL_COUNT; ++i) fprintf(stderr, " %s=%d", pool_names[i], stats.max_step[i]);
    fprintf(stderr, "\n");
    memset(&stats, 0, sizeof stats);
    last_report_ms = now;
}

static void engage(uint64_t now) {
    engaged = 1;
    next_frame = now;
    last_present = now;
    last_main_flip = 0;
    anchor_wall_ns = SDL_GetTicksNS();
    anchor_guest = now;
    g_shadowtower_cycle_scale = cycle_scale;
    g_shadowtower_cycle_carry = 0;
    reset_smoothing();
}

/* Every hook must fire in a full iteration, or gating would change game speed.
 * Returns 0 once the unlock is disabled. */
static int hooks_fired(void) {
    if (!engaged || seen == SEEN_ALL) {
        missed_iterations = 0;
        return 1;
    }
    if (++missed_iterations < WATCHDOG_MISSES) return 1;
    char missing[256] = "hooks not firing:";
    for (int i = 0; i < GATE_COUNT; ++i)
        if (!(seen & (1u << i))) {
            strncat(missing, " ", sizeof missing - strlen(missing) - 1);
            strncat(missing, gates[i].id, sizeof missing - strlen(missing) - 1);
        }
    if (!(seen & SEEN_RENDER)) strncat(missing, " render", sizeof missing - strlen(missing) - 1);
    if (!(seen & SEEN_TEXTURE_ANIMATION))
        strncat(missing, " texture-animation", sizeof missing - strlen(missing) - 1);
    if (!(seen & SEEN_VSYNC)) strncat(missing, " vsync", sizeof missing - strlen(missing) - 1);
    if (!(seen & SEEN_FRAME_WAIT)) strncat(missing, " frame-wait", sizeof missing - strlen(missing) - 1);
    disable(missing);
    return 0;
}

/* Decides at the main loop's head whether this iteration simulates. */
static void begin_iteration(void) {
    if (!enabled) return;
    /* Left set only when a save-state load cut the last iteration short. */
    in_main_render = 0;
    camera_written = 0;
    if (!hooks_fired()) return;
    const uint64_t now = now_cycles();
    if (!engaged) engage(now);
    last_loop_head = now;
    seen = 0;
    tick = shadowtower_tick_due(&clock_state, now);
    if (psx_mod_read_half(AREA_LOADING)) reset_smoothing();
    if (!tick) saved_loop_flag = psx_mod_read_byte(LOOP_FLAG);
    ++stats.iterations;
    if (tick) ++stats.ticks;
    if (probe) report();
}

static void loop_head(struct CPUState *cpu) {
    if (cpu->gpr[31] == LOOP_HEAD_RETURN) begin_iteration();
    shadowtower_call_original(cpu, LOOP_HEAD);
}

static void gated_call(struct CPUState *cpu, int index) {
    const Gate *gate = &gates[index];
    if (engaged && cpu->gpr[31] == gate->return_address) {
        seen |= 1u << index;
        if (!tick) {
            if (index == LOOP_FLAG_GATE) psx_mod_write_byte(LOOP_FLAG, saved_loop_flag);
            return;
        }
    }
    shadowtower_call_original(cpu, gate->address);
}

#define GATE_FUNCTION(index) \
    static void gate_##index(struct CPUState *cpu) { gated_call(cpu, index); }
GATE_FUNCTION(0)
GATE_FUNCTION(1)
GATE_FUNCTION(2)
GATE_FUNCTION(3)
GATE_FUNCTION(4)
GATE_FUNCTION(5)
GATE_FUNCTION(6)
GATE_FUNCTION(7)
GATE_FUNCTION(8)
GATE_FUNCTION(9)
static const ShadowTowerOverrideFn gate_functions[GATE_COUNT] = {
    gate_0, gate_1, gate_2, gate_3, gate_4, gate_5, gate_6, gate_7, gate_8, gate_9};

static void read_camera(Camera *camera) {
    for (int i = 0; i < 3; ++i) {
        camera->position[i] = (int32_t)psx_mod_read_word(PLAYER_POSITION + 4u * i);
        camera->angle[i] = psx_mod_read_half(PLAYER_ANGLES + 2u * i);
    }
    camera->eye[0] = (int16_t)psx_mod_read_half(PLAYER_EYE);
    camera->eye[1] = (int16_t)psx_mod_read_half(PLAYER_EYE_SECOND);
}

/* Writes `to` wherever the guest still holds `from`, so a value the guest
 * changed in between is kept. */
static void write_camera(const Camera *to, const Camera *from) {
    for (int i = 0; i < 3; ++i) {
        const uint32_t position = PLAYER_POSITION + 4u * i;
        if ((int32_t)psx_mod_read_word(position) == from->position[i])
            psx_mod_write_word(position, (uint32_t)to->position[i]);
        const uint32_t angle = PLAYER_ANGLES + 2u * i;
        if (psx_mod_read_half(angle) == from->angle[i]) psx_mod_write_half(angle, to->angle[i]);
    }
    const uint32_t eyes[2] = {PLAYER_EYE, PLAYER_EYE_SECOND};
    for (int i = 0; i < 2; ++i)
        if ((int16_t)psx_mod_read_half(eyes[i]) == from->eye[i])
            psx_mod_write_half(eyes[i], (uint16_t)to->eye[i]);
}

static int camera_jumped(const Camera *a, const Camera *b) {
    for (int i = 0; i < 3; ++i)
        if (llabs((long long)a->position[i] - b->position[i]) > CAMERA_TELEPORT) return 1;
    return 0;
}

/* Puts an interpolated camera in the player record and the view arguments,
 * remembering what restore_camera puts back. */
static void camera_begin(struct CPUState *cpu) {
    Camera *real = &camera_real;
    read_camera(real);
    if (tick) {
        camera_previous = camera_valid ? camera_current : *real;
        if (camera_jumped(&camera_previous, real)) camera_previous = *real;
        camera_valid = 1;
    }
    if (!camera_valid) return;
    camera_current = *real;
    Camera view;
    for (int i = 0; i < 3; ++i) {
        view.position[i] = shadowtower_lerp(camera_previous.position[i], real->position[i], phase);
        view.angle[i] = shadowtower_lerp_angle(camera_previous.angle[i], real->angle[i], phase);
    }
    for (int i = 0; i < 2; ++i)
        view.eye[i] = (int16_t)shadowtower_lerp(camera_previous.eye[i], real->eye[i], phase);
    /* Mouse and stick look show at once instead of a tick later. */
    int yaw, pitch;
    shadowtower_look_render_offset(1.f - phase, &yaw, &pitch);
    int base_pitch = psx_mod_read_half(PLAYER_BASE_PITCH) & SHADOWTOWER_ANGLE_MASK;
    if (base_pitch > 2047) base_pitch -= 4096;
    if (base_pitch + pitch > PITCH_LIMIT) pitch = PITCH_LIMIT - base_pitch;
    if (base_pitch + pitch < -PITCH_LIMIT) pitch = -PITCH_LIMIT - base_pitch;
    view.angle[0] = (uint16_t)(view.angle[0] + pitch);
    view.angle[1] = (uint16_t)(view.angle[1] + yaw);

    write_camera(&view, real);
    /* The view arguments the main loop built from the player record. */
    const uint32_t position = cpu->gpr[4], angles = cpu->gpr[5];
    psx_mod_write_word(position, (uint32_t)view.position[0]);
    psx_mod_write_word(position + 4u, (uint32_t)(view.position[1] + view.eye[0] + view.eye[1] - EYE_HEIGHT));
    psx_mod_write_word(position + 8u, (uint32_t)view.position[2]);
    for (int i = 0; i < 3; ++i) psx_mod_write_half(angles + 2u * i, view.angle[i]);
    camera_drawn = view;
    camera_written = 1;
    ++stats.camera;
}

/* Restores the simulated camera before the frame wait, so a save state taken
 * there holds it rather than the interpolated one. */
static void restore_camera(void) {
    if (!camera_written) return;
    write_camera(&camera_real, &camera_drawn);
    camera_written = 0;
}

/* Seconds the host runs behind guest time; re-anchors after a stall. */
static double host_lag(uint64_t now) {
    const uint64_t wall_ns = SDL_GetTicksNS();
    const double lag = (double)(wall_ns - anchor_wall_ns) / 1e9 - (double)(now - anchor_guest) / SHADOWTOWER_CPU_HZ;
    if (lag > REANCHOR_SECONDS || lag < -REANCHOR_SECONDS) {
        anchor_wall_ns = wall_ns;
        anchor_guest = now;
        return 0;
    }
    return lag;
}

static int wait_for_frame(struct CPUState *cpu, uint32_t resume);

static void read_bytes(uint32_t address, uint8_t *bytes, uint32_t count) {
    for (uint32_t i = 0; i < count; ++i) bytes[i] = psx_mod_read_byte(address + i);
}

static void write_bytes(uint32_t address, const uint8_t *bytes, uint32_t count) {
    for (uint32_t i = 0; i < count; ++i) psx_mod_write_byte(address + i, bytes[i]);
}

/* A tick's flash shows on every frame of the tick, as it stays on screen for the
 * whole tick at stock pacing. */
static void replay_flash(void) {
    if (tick) {
        read_bytes(FLASH_STATE, flash_state, FLASH_STATE_BYTES);
        flash_saved = 1;
    } else if (flash_saved) {
        write_bytes(FLASH_STATE, flash_state, FLASH_STATE_BYTES);
    }
}

static void render(struct CPUState *cpu) {
    if (!engaged || cpu->gpr[31] != RENDER_RETURN) {
        shadowtower_call_original(cpu, RENDER);
        return;
    }
    seen |= SEEN_RENDER;
    const uint64_t now = now_cycles();
    /* A host slower than the target drops in-between frames instead of slowing the game. */
    if (!tick && host_lag(now) * SHADOWTOWER_CPU_HZ > (double)frame_cycles) {
        seen |= SEEN_TEXTURE_ANIMATION | SEEN_VSYNC | SEEN_FRAME_WAIT;
        ++stats.dropped;
        last_main_flip = now;
        wait_for_frame(cpu, RENDER_RETURN);
        return;
    }
    phase = shadowtower_tick_phase(&clock_state, now);
    if (smooth_camera) camera_begin(cpu);
    replay_flash();
    const uint8_t counter = psx_mod_read_byte(RENDER_COUNTER);
    draw_count = 0;
    in_main_render = 1;
    const uint64_t started = SDL_GetTicksNS();
    const int returned = shadowtower_call_original(cpu, RENDER);
    stats.render_ns += SDL_GetTicksNS() - started - present_ns;
    present_ns = 0;
    in_main_render = 0;
    if (!returned) return; /* A non-local exit (such as a save-state load) owns guest state now. */
    restore_camera();
    if (!tick) psx_mod_write_byte(RENDER_COUNTER, counter);
}

/* Frames between ticks draw the pool without stepping its animation. */
static void animated_pool(struct CPUState *cpu) {
    if (!in_main_render || tick || cpu->gpr[31] != ANIMATED_POOL_RETURN) {
        shadowtower_call_original(cpu, ANIMATED_POOL);
        return;
    }
    const uint32_t counter = psx_mod_read_word(ANIMATED_POOL_COUNTER);
    uint8_t frames[ANIMATED_POOL_ENTRIES];
    for (uint32_t i = 0; i < ANIMATED_POOL_ENTRIES; ++i)
        frames[i] = psx_mod_read_byte(ANIMATED_POOL_FRAMES + i * ANIMATED_POOL_STRIDE);
    if (!shadowtower_call_original(cpu, ANIMATED_POOL)) return;
    psx_mod_write_word(ANIMATED_POOL_COUNTER, counter);
    for (uint32_t i = 0; i < ANIMATED_POOL_ENTRIES; ++i)
        psx_mod_write_byte(ANIMATED_POOL_FRAMES + i * ANIMATED_POOL_STRIDE, frames[i]);
}

/* Frames between ticks draw the transition without stepping it. */
static void transition(struct CPUState *cpu) {
    if (!in_main_render || tick || cpu->gpr[31] != TRANSITION_RETURN) {
        shadowtower_call_original(cpu, TRANSITION);
        return;
    }
    uint8_t state[TRANSITION_STATE_BYTES];
    read_bytes(TRANSITION_STATE, state, TRANSITION_STATE_BYTES);
    if (!shadowtower_call_original(cpu, TRANSITION)) return;
    write_bytes(TRANSITION_STATE, state, TRANSITION_STATE_BYTES);
}

static void texture_animation(struct CPUState *cpu) {
    if (in_main_render && cpu->gpr[31] == TEXTURE_ANIMATION_RETURN) {
        seen |= SEEN_TEXTURE_ANIMATION;
        if (!tick) return;
    }
    shadowtower_call_original(cpu, TEXTURE_ANIMATION);
}

/* Advances guest time to the next frame slot, delivering each interrupt as it
 * comes due. Returns 0 when a non-local exit began. */
static int wait_for_frame(struct CPUState *cpu, uint32_t resume) {
    psx_cyc_batch_flush();
    uint64_t now = now_cycles();
    uint64_t target = next_frame;
    /* A late frame starts the next slot now; a slot far ahead follows a save-state load. */
    if (target <= now || target - now > frame_cycles) target = now;
    next_frame = target + frame_cycles;
    while ((now = now_cycles()) < target) {
        uint64_t step = target - now;
        const uint32_t event = psx_idle_cycles_to_next_observable_event();
        if (event && event < step) step = event;
        psx_advance_cycles((uint32_t)step);
        psx_check_interrupts_at(cpu, resume);
        if (g_psx_call_bail) return 0;
    }
    return 1;
}

/* Another loop (menu, fade, load screen) presents with stock pacing. */
static void flip(struct CPUState *cpu) {
    if (engaged && (!in_main_render || cpu->gpr[31] != FLIP_RETURN)) disengage("another loop presented a frame");
    shadowtower_call_original(cpu, FLIP);
}

/* The main frame's VSync(3) waits only for its frame slot. FLIP ignores the
 * return value. */
static void vsync(struct CPUState *cpu) {
    if (!engaged || !in_main_render || cpu->gpr[31] != VSYNC_RETURN) {
        shadowtower_call_original(cpu, VSYNC);
        return;
    }
    seen |= SEEN_VSYNC;
    restore_camera();
    if (!wait_for_frame(cpu, VSYNC_RETURN)) return;
    /* What stock VSync records on return, so the next stock VSync(n) waits its full n VBlanks. */
    psx_mod_write_word(VSYNC_LAST_COUNT, psx_mod_read_word(VSYNC_COUNT));
    psx_mod_write_word(VSYNC_LAST_HCOUNT, psx_mod_read_word(psx_mod_read_word(VSYNC_HCOUNT_POINTER)));
}

static void frame_wait(struct CPUState *cpu) {
    if (!engaged || !in_main_render || cpu->gpr[31] != FRAME_WAIT_RETURN) {
        shadowtower_call_original(cpu, FRAME_WAIT);
        return;
    }
    seen |= SEEN_FRAME_WAIT;
    psx_mod_write_word(VBLANK_FLAG, 0);
    last_main_flip = now_cycles();
    ++stats.flips;
    const uint64_t started = SDL_GetTicksNS();
    shadowtower_present_flip();
    present_ns = SDL_GetTicksNS() - started;
    stats.present_ns += present_ns;
}

static int pool_for(uint32_t ra) {
    switch (ra) {
    case 0x80024440u: case 0x80024544u: case 0x80024614u: return POOL_A;
    case 0x80025014u: case 0x80025158u: return POOL_B;
    case 0x80025418u: case 0x8002557Cu: return POOL_C;
    case 0x80025870u: return POOL_D1;
    case 0x800259ACu: case 0x80025B50u: return POOL_D2;
    default: return POOL_OTHER;
    }
}

static Entity *entity_for(uint32_t key) {
    const uint32_t slot = (key * 2654435761u) >> (32 - ENTITY_SLOT_BITS);
    for (uint32_t probe_count = 0; probe_count < ENTITY_SLOTS; ++probe_count) {
        Entity *entity = &entities[(slot + probe_count) & (ENTITY_SLOTS - 1)];
        if (entity->key == key || !entity->key) return entity;
    }
    return NULL;
}

static int max_step(const int32_t *a, const int32_t *b) {
    long long step = 0;
    for (int i = 0; i < 3; ++i) {
        const long long d = llabs((long long)a[i] - b[i]);
        if (d > step) step = d;
    }
    return step > INT32_MAX ? INT32_MAX : (int)step;
}

/* Interpolated position and angles for one persistent entity draw. */
static void smooth_entity(uint32_t key, uint16_t model, int pool, const int32_t *position,
                          const uint16_t *angle, int32_t *drawn, uint16_t *drawn_angle) {
    Entity *entity = entity_for(key);
    if (!entity) { /* Table full: draw as simulated. */
        memcpy(drawn, position, 3 * sizeof *drawn);
        memcpy(drawn_angle, angle, 3 * sizeof *drawn_angle);
        return;
    }
    const uint32_t now_tick = clock_state.count;
    if (entity->key != key || entity->model != model || entity->tick + 1 < now_tick) {
        /* New, reused or long-unseen slot: no history to blend from. */
        *entity = (Entity){.key = key, .tick = now_tick, .model = model};
        memcpy(entity->previous, position, sizeof entity->previous);
        memcpy(entity->previous_angle, angle, sizeof entity->previous_angle);
    } else if (entity->tick != now_tick) {
        memcpy(entity->previous, entity->current, sizeof entity->previous);
        memcpy(entity->previous_angle, entity->current_angle, sizeof entity->previous_angle);
        entity->tick = now_tick;
        const int step = max_step(entity->previous, position);
        if (step > stats.max_step[pool]) stats.max_step[pool] = step;
        if (step > pool_teleport[pool]) {
            memcpy(entity->previous, position, sizeof entity->previous);
            memcpy(entity->previous_angle, angle, sizeof entity->previous_angle);
            ++stats.teleports;
        }
    }
    memcpy(entity->current, position, sizeof entity->current);
    memcpy(entity->current_angle, angle, sizeof entity->current_angle);
    for (int i = 0; i < 3; ++i) {
        drawn[i] = shadowtower_lerp(entity->previous[i], position[i], phase);
        drawn_angle[i] = shadowtower_lerp_angle(entity->previous_angle[i], angle[i], phase);
    }
}

static int is_temporary(uint32_t address, uint32_t sp) {
    const uint32_t physical = address & 0x1FFFFFFFu;
    if (physical >= SCRATCHPAD && physical < SCRATCHPAD_END) return 1;
    return address - sp < TEMPORARY_SPAN;
}

static void draw_model(struct CPUState *cpu) {
    if (!in_main_render || !smooth_objects) {
        shadowtower_call_original(cpu, DRAW_MODEL);
        return;
    }
    const uint32_t position_address = cpu->gpr[6], angle_address = cpu->gpr[7];
    int32_t position[3], drawn[3];
    uint16_t angle[3] = {0, 0, 0}, drawn_angle[3] = {0, 0, 0};
    for (int i = 0; i < 3; ++i) {
        position[i] = (int32_t)psx_mod_read_word(position_address + 4u * i);
        if (angle_address) angle[i] = psx_mod_read_half(angle_address + 2u * i);
    }
    int smoothed = 0;
    if (is_temporary(position_address, cpu->gpr[29])) {
        /* A copy of an entity drawn this frame (such as its shadow) follows that entity. */
        memcpy(drawn_angle, angle, sizeof drawn_angle);
        for (uint32_t i = 0; i < draw_count && !smoothed; ++i)
            if (!memcmp(draws[i].current, position, sizeof position)) {
                memcpy(drawn, draws[i].drawn, sizeof drawn);
                smoothed = 1;
                ++stats.temporaries;
            }
    } else {
        smooth_entity(position_address, (uint16_t)cpu->gpr[5], pool_for(cpu->gpr[31]), position, angle,
                      drawn, drawn_angle);
        smoothed = 1;
        ++stats.objects;
        if (draw_count < FRAME_DRAWS) {
            memcpy(draws[draw_count].current, position, sizeof position);
            memcpy(draws[draw_count].drawn, drawn, sizeof drawn);
            ++draw_count;
        }
    }
    if (!smoothed) {
        shadowtower_call_original(cpu, DRAW_MODEL);
        return;
    }
    for (int i = 0; i < 3; ++i) {
        psx_mod_write_word(position_address + 4u * i, (uint32_t)drawn[i]);
        if (angle_address) psx_mod_write_half(angle_address + 2u * i, drawn_angle[i]);
    }
    if (!shadowtower_call_original(cpu, DRAW_MODEL)) return;
    for (int i = 0; i < 3; ++i) {
        const uint32_t word = position_address + 4u * i;
        if ((int32_t)psx_mod_read_word(word) == drawn[i]) psx_mod_write_word(word, (uint32_t)position[i]);
        const uint32_t half = angle_address + 2u * i;
        if (angle_address && psx_mod_read_half(half) == drawn_angle[i]) psx_mod_write_half(half, angle[i]);
    }
}

int shadowtower_flip_owns_present(void) {
    if (!engaged) return 0;
    const uint64_t now = now_cycles();
    if (now - last_loop_head > WATCHDOG_TICKS * (uint64_t)SHADOWTOWER_TICK_CYCLES) {
        disengage("the main loop stopped reaching its head");
        return 0;
    }
    const uint64_t window = 2 * (frame_cycles > SHADOWTOWER_VBLANK_CYCLES ? frame_cycles : SHADOWTOWER_VBLANK_CYCLES);
    return last_main_flip && now - last_main_flip <= window;
}

double shadowtower_flip_period_ms(void) {
    const uint64_t now = now_cycles();
    const uint64_t elapsed = now - last_present;
    last_present = now;
    if (!shadowtower_flip_owns_present()) return 0;
    const double ms = (double)elapsed * 1000.0 / SHADOWTOWER_CPU_HZ;
    if (ms > 250.0) return 250.0;
    return ms > 0.001 ? ms : 0.001;
}

/* Unset means off; any value other than 0 or 1 keeps it off and says why. */
static int read_enabled(void) {
    const char *text = getenv("SHADOWTOWER_FRAME_UNLOCK");
    if (!text || !strcmp(text, "0")) return 0;
    if (!strcmp(text, "1")) return 1;
    fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_FRAME_UNLOCK=\"%s\"; use 0 or 1. Keeping it off.\n", text);
    return 0;
}

static void read_target_fps(void) {
    const char *text = getenv("SHADOWTOWER_TARGET_FPS");
    if (!text) return;
    char *end;
    errno = 0;
    const long value = strtol(text, &end, 10);
    if (errno || end == text || *end || value < SHADOWTOWER_TARGET_FPS_MIN || value > SHADOWTOWER_TARGET_FPS_MAX) {
        fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_TARGET_FPS \"%s\"; use a whole number from %d to %d. "
                "Using %u.\n", text, SHADOWTOWER_TARGET_FPS_MIN, SHADOWTOWER_TARGET_FPS_MAX, target_fps);
        return;
    }
    target_fps = (unsigned)value;
}

static int register_all(void) {
#define FINGERPRINT SHADOWTOWER_GAMEPLAY_FINGERPRINT
    int ok = shadowtower_register_override("frame-unlock.loop-head", LOOP_HEAD,
                                           FINGERPRINT(LOOP_HEAD, 0x3C028009u, 0x24458200u), loop_head);
    ok &= shadowtower_register_override("frame-unlock.render", RENDER,
                                        FINGERPRINT(RENDER, 0x27BDFFC8u, 0xAFB00020u), render);
    ok &= shadowtower_register_override("frame-unlock.texture-animation", TEXTURE_ANIMATION,
                                        FINGERPRINT(TEXTURE_ANIMATION, 0x27BDFFB8u, 0x3C028018u), texture_animation);
    ok &= shadowtower_register_override("frame-unlock.flip", FLIP,
                                        FINGERPRINT(FLIP, 0x27BDFFE0u, 0x00002021u), flip);
    ok &= shadowtower_register_override("frame-unlock.vsync", VSYNC,
                                        FINGERPRINT(VSYNC, 0x3C028008u, 0x8C426A98u), vsync);
    ok &= shadowtower_register_override("frame-unlock.frame-wait", FRAME_WAIT,
                                        FINGERPRINT(FRAME_WAIT, 0x27BDFFE8u, 0x3C028009u), frame_wait);
    ok &= shadowtower_register_override("frame-unlock.animated-pool", ANIMATED_POOL,
                                        FINGERPRINT(ANIMATED_POOL, 0x27BDFF98u, 0xAFB10044u), animated_pool);
    ok &= shadowtower_register_override("frame-unlock.transition", TRANSITION,
                                        FINGERPRINT(TRANSITION, 0x27BDFFA8u, 0x3C028008u), transition);
    ok &= shadowtower_register_override("frame-unlock.draw-model", DRAW_MODEL,
                                        FINGERPRINT(DRAW_MODEL, 0x27BDFF30u, 0xAFB100ACu), draw_model);
    for (int i = 0; i < GATE_COUNT; ++i)
        ok &= shadowtower_register_override(gates[i].id, gates[i].address,
                                            FINGERPRINT(gates[i].address, gates[i].entry[0], gates[i].entry[1]),
                                            gate_functions[i]);
#undef FINGERPRINT
    return ok;
}

PSX_MOD_CONSTRUCTOR(register_frame_unlock) {
    enabled = read_enabled();
    if (!enabled) return;
    read_target_fps();
    smooth_camera = shadowtower_env_switch("SHADOWTOWER_SMOOTH_CAMERA");
    smooth_objects = shadowtower_env_switch("SHADOWTOWER_SMOOTH_OBJECTS");
    const char *probe_text = getenv("SHADOWTOWER_FRAME_PROBE");
    probe = probe_text && !strcmp(probe_text, "1");
    frame_cycles = shadowtower_frame_cycles(target_fps);
    cycle_scale = shadowtower_cycle_scale(target_fps);
    const char *check = getenv("SHADOWTOWER_OVERRIDE_CHECK");
    if (check && !strcmp(check, "1")) {
        disable("SHADOWTOWER_OVERRIDE_CHECK=1 runs every original, so the simulation could not be gated");
        return;
    }
    if (!register_all()) disable("an override could not be registered");
}
