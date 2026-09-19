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

#ifdef __cplusplus
}
#endif
