#pragma once

#include "renderer_options.h"
#include "triangle_extra.h"

/* Depth for the hi-res target. Polygons with PGXP depth carry their GTE SZ per
 * vertex; 2D content (fills, uploads, copies, sprites, HUD) is far. The Z-buffer
 * only rejects 3D behind 3D, so 2D draws keep the PS1's painter order. */
static GLuint s_hr_depth_tex;
static int s_depth_loaded, s_depth_test, s_depth_write, s_ambient_occlusion;

static void depth_load_options(void) {
    if (s_depth_loaded) return;
    s_depth_loaded = 1;
    s_depth_test = shadowtower_env_switch("SHADOWTOWER_DEPTH_BUFFER");
    s_ambient_occlusion = shadowtower_env_switch("SHADOWTOWER_AMBIENT_OCCLUSION");
    s_depth_write = s_depth_test || s_ambient_occlusion;
}

/* 1 - 16/SZ is affine in screen space, so it interpolates exactly without w,
 * and keeps about 16 depth-buffer steps per SZ unit at SZ 4096. */
static float depth_from_sz(uint16_t sz) {
    return 1.0f - 16.0f / (float)(sz < 16 ? 16 : sz);
}

/* Fill out[] for the triangle being built; returns whether it has depth. */
static int triangle_depth(int polygon, float out[3]) {
    const ShadowtowerTriangleExtra *extra = &g_shadowtower_triangle_extra;
    const int known = polygon && extra->valid && extra->has_depth;
    for (int i = 0; i < 3; i++) out[i] = known ? depth_from_sz(extra->sz[i]) : 1.0f;
    return known;
}

/* Call inside hr_begin/hr_end, before drawing a batch. Translucent draws test
 * but never write, so what is behind them keeps its depth. */
static void depth_state(int has_depth, int semi) {
    depth_load_options();
    if (!s_depth_write) {
        glDisable(GL_DEPTH_TEST);
        return;
    }
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(has_depth && s_depth_test ? GL_LEQUAL : GL_ALWAYS);
    glDepthMask(semi < 0 ? GL_TRUE : GL_FALSE);
}

/* Reset the current scissor rectangle of the bound hi-res target to far. */
static void depth_reset_scissored(void) {
    glDepthMask(GL_TRUE);
    glClearDepth(1.0);
    glClear(GL_DEPTH_BUFFER_BIT);
}

/* Bind depth for the present program's ambient occlusion, or switch it off.
 * rect is the displayed frame in texture UVs (u0, v0, u1, v1); samples stay
 * inside it so they never read the PS1's other framebuffer. The present
 * program is current; texture unit 0 stays active afterwards. */
static GLuint s_ao_program;
static GLint u_ao_depth = -1, u_ao_enabled = -1, u_ao_texel = -1, u_ao_scale = -1, u_ao_rect = -1;

/* A new GL context recreates every program and target. */
static void depth_reset_context(void) {
    s_hr_depth_tex = 0;
    s_ao_program = 0;
}

static void ambient_occlusion_upload(GLuint program, int enabled, int tex_w, int tex_h,
                                     const float rect[4]) {
    if (program != s_ao_program) {
        s_ao_program = program;
        u_ao_depth = p_glGetUniformLocation(program, "u_ao_depth");
        u_ao_enabled = p_glGetUniformLocation(program, "u_ao_enabled");
        u_ao_texel = p_glGetUniformLocation(program, "u_ao_texel");
        u_ao_scale = p_glGetUniformLocation(program, "u_ao_scale");
        u_ao_rect = p_glGetUniformLocation(program, "u_ao_rect");
    }
    depth_load_options();
    enabled = enabled && rect && s_ambient_occlusion && s_hr_depth_tex && tex_w > 0 && tex_h > 0;
    p_glUniform1i(u_ao_enabled, enabled);
    if (!enabled) return;
    p_glActiveTexture(PSXGL_TEXTURE0 + 1);
    glBindTexture(GL_TEXTURE_2D, s_hr_depth_tex);
    p_glActiveTexture(PSXGL_TEXTURE0);
    p_glUniform1i(u_ao_depth, 1);
    p_glUniform2f(u_ao_texel, 1.0f / (float)tex_w, 1.0f / (float)tex_h);
    p_glUniform1f(u_ao_scale, (float)s_scale);
    p_glUniform4f(u_ao_rect, rect[0] < rect[2] ? rect[0] : rect[2], rect[1] < rect[3] ? rect[1] : rect[3],
                  rect[0] < rect[2] ? rect[2] : rect[0], rect[1] < rect[3] ? rect[3] : rect[1]);
}
