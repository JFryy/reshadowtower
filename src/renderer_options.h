#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Read a 0/1 renderer switch set by the launcher. Unset means on, so runs
 * without the launcher get the defaults; any other value keeps it on and says
 * why. */
static inline int shadowtower_env_switch(const char *name) {
    const char *text = getenv(name);
    if (!text || strcmp(text, "1") == 0) return 1;
    if (strcmp(text, "0") == 0) return 0;
    fprintf(stderr, "Shadow Tower: invalid %s=\"%s\"; use 0 or 1. Keeping it on.\n", name, text);
    return 1;
}
