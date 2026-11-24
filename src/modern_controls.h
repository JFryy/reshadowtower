#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "psx_sdl.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Main-thread adapters preserve SDL events and the framework's keyboard mapping. */
bool shadowtower_poll_event(SDL_Event *event);
uint16_t shadowtower_pad_word(const uint8_t *keys, int player);

/* Look input the game camera has not shown yet: the share of the last look
 * update a camera drawn `behind` (0..1) of a tick before it still lacks, plus
 * input waiting for the next update. Yaw and pitch in PS1 angle units, pitch
 * unclamped. Zero on a tick whose simulation did not run the look routine. */
void shadowtower_look_render_offset(float behind, int *yaw, int *pitch);

/* Starts a simulation tick, before the game decides whether to run its look routine. */
void shadowtower_look_begin_tick(void);

#ifdef __cplusplus
}
#endif
