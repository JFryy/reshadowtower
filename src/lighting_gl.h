#pragma once

#include <math.h>
#include <string.h>

#include "renderer_options.h"
#include "triangle_extra.h"

/* Feeds src/gte_lighting.glsl: per-vertex lighting attributes and the
 * per-batch table of lighting contexts they index. */
#define LIGHT_ATTRIBUTES 8 /* L*n, context, normal, IR0 */
#define LIGHT_TEXELS 6
#define LIGHT_CONTEXTS 2730 /* one per triangle of a full textured batch */
#define SHADOWTOWER_GL_RGBA32F 0x8814

static int s_light_loaded, s_pixel_lighting, s_smooth_fog;
static GLuint s_light_tex, s_light_program;
static GLint u_light_context = -1, u_pixel_lighting = -1, u_smooth_fog = -1;
static float s_light_rows[LIGHT_CONTEXTS * LIGHT_TEXELS * 4];
static ShadowtowerLightContext s_light_last;
static int s_light_n;

static void lighting_load_options(void) {
    if (s_light_loaded) return;
    s_light_loaded = 1;
    s_pixel_lighting = shadowtower_env_switch("SHADOWTOWER_PIXEL_LIGHTING");
    s_smooth_fog = shadowtower_env_switch("SHADOWTOWER_SMOOTH_FOG");
}

static int lighting_context_index(const ShadowtowerLightContext *c) {
    if (s_light_n > 0 && memcmp(c, &s_light_last, sizeof(*c)) == 0) return s_light_n - 1;
    if (s_light_n == LIGHT_CONTEXTS) return -1;
    float *t = &s_light_rows[s_light_n * LIGHT_TEXELS * 4];
    for (int i = 0; i < 3; i++) {
        t[i * 4 + 0] = c->matrix[i * 3 + 0];
        t[i * 4 + 1] = c->matrix[i * 3 + 1];
        t[i * 4 + 2] = c->matrix[i * 3 + 2];
        t[i * 4 + 3] = c->back[i];
        t[12 + i] = c->scale[i];
        t[16 + i] = c->far_colour[i];
    }
    t[15] = (float)c->mode;
    t[19] = 0.0f;
    t[20] = c->fog_near;
    t[21] = c->fog_far;
    t[22] = t[23] = 0.0f;
    s_light_last = *c;
    return s_light_n++;
}

/* Fill out[] for the triangle being built. The context slot is -1 (keep the
 * packet colour) unless all three colours came from one GTE lighting context
 * and a lighting switch is on. */
static void triangle_lighting(int polygon, float out[3][LIGHT_ATTRIBUTES]) {
    const ShadowtowerTriangleExtra *extra = &g_shadowtower_triangle_extra;
    lighting_load_options();
    memset(out, 0, sizeof(float) * 3 * LIGHT_ATTRIBUTES);
    int context = -1;
    if (polygon && extra->valid && (s_pixel_lighting || s_smooth_fog) && extra->light[0] &&
        extra->light[1] && extra->light[2] &&
        memcmp(&extra->light[0]->context, &extra->light[1]->context, sizeof(ShadowtowerLightContext)) == 0 &&
        memcmp(&extra->light[0]->context, &extra->light[2]->context, sizeof(ShadowtowerLightContext)) == 0)
        context = lighting_context_index(&extra->light[0]->context);
    for (int i = 0; i < 3; i++) {
        out[i][3] = (float)context;
        if (context < 0) continue;
        const ShadowtowerLightVertex *v = extra->light[i];
        const float length = sqrtf(v->normal[0] * v->normal[0] + v->normal[1] * v->normal[1] +
                                   v->normal[2] * v->normal[2]);
        for (int k = 0; k < 3; k++) {
            out[i][k] = v->light[k];
            out[i][4 + k] = length > 0.0f ? v->normal[k] / length : 0.0f;
        }
        out[i][7] = v->ir0;
    }
}

/* A new GL context recreates every program and texture. */
static void lighting_reset_context(void) {
    s_light_tex = 0;
    s_light_program = 0;
    s_light_n = 0;
}

/* Upload the batch's contexts on texture unit 2 and set the switches. Call
 * with the textured program current; unit 0 stays active afterwards. */
static void lighting_upload(GLuint program) {
    lighting_load_options();
    if (program != s_light_program) {
        s_light_program = program;
        u_light_context = p_glGetUniformLocation(program, "u_light_context");
        u_pixel_lighting = p_glGetUniformLocation(program, "u_pixel_lighting");
        u_smooth_fog = p_glGetUniformLocation(program, "u_smooth_fog");
    }
    p_glActiveTexture(PSXGL_TEXTURE0 + 2);
    if (!s_light_tex) {
        glGenTextures(1, &s_light_tex);
        glBindTexture(GL_TEXTURE_2D, s_light_tex);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexImage2D(GL_TEXTURE_2D, 0, SHADOWTOWER_GL_RGBA32F, LIGHT_TEXELS, LIGHT_CONTEXTS, 0, GL_RGBA,
                     GL_FLOAT, NULL);
    }
    glBindTexture(GL_TEXTURE_2D, s_light_tex);
    if (s_light_n > 0)
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, LIGHT_TEXELS, s_light_n, GL_RGBA, GL_FLOAT, s_light_rows);
    s_light_n = 0;
    p_glActiveTexture(PSXGL_TEXTURE0);
    p_glUniform1i(u_light_context, 2);
    p_glUniform1i(u_pixel_lighting, s_pixel_lighting);
    p_glUniform1i(u_smooth_fog, s_smooth_fog);
}
