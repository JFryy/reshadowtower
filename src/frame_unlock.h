#pragma once
/* Shadow Tower USA: present hooks between the frame-rate unlock and the runtime. */

#ifdef __cplusplus
extern "C" {
#endif

/* Whether the unlock presents at the game's buffer flip, so a VBlank must not. */
int shadowtower_flip_owns_present(void);

/* Pacing period for this present: guest milliseconds since the previous one
 * while the flip owns presentation, or 0 for the runtime's own period. */
double shadowtower_flip_period_ms(void);

/* Runtime present body, called by the unlock at the game's buffer flip. */
void shadowtower_present_flip(void);

#ifdef __cplusplus
}
#endif
