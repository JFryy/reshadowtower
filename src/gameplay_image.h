#pragma once

/* Code words of the gameplay executable (ST.EXE at 0x80011000) that every
 * gameplay override's fingerprint includes, so no override runs against
 * another executable loaded at the same addresses. */
#define SHADOWTOWER_GAMEPLAY_WORDS \
    {0x80014BD4u, 0x0C00592Du}, {0x80014C48u, 0x0C009ABFu}, {0x80026D90u, 0x0C005DA0u}

/* A gameplay fingerprint for the override at `address`: the shared words plus
 * the override's first two instructions. Expands to the array and its length. */
#define SHADOWTOWER_GAMEPLAY_FINGERPRINT(address, first, second)                                \
    (ShadowTowerCodeWord[]){SHADOWTOWER_GAMEPLAY_WORDS, {(address), (first)}, {(address) + 4u, (second)}}, \
        5
