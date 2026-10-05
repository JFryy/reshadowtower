#pragma once
#include "post_processing.h"

/* Per-program locations prevent shared OSD/bezel draws inheriting game effects. */
typedef struct ShadowtowerPostFxUniforms {
    GLuint program;
    GLint enabled, color, texture, crt, pitch, time, detail;
} ShadowtowerPostFxUniforms;
static ShadowtowerPostFxUniforms s_postfx_uniforms[2];
static ShadowtowerPostFx s_postfx;
static int s_postfx_loaded;
static float s_postfx_fxaa, s_postfx_sharpen;

static void shadowtower_postfx_reset(void) {
    memset(s_postfx_uniforms, 0, sizeof(s_postfx_uniforms));
    s_postfx_loaded = 0;
    s_postfx_fxaa = s_postfx_sharpen = 0.f;
}

/* Called for every presentation draw, including explicit non-game bypasses. */
static void shadowtower_postfx_upload(int slot, GLuint program, int pitch, int lines, int out_h) {
    if (!s_postfx_loaded) {
        s_postfx_loaded = 1;
        if (!shadowtower_postfx_parse(getenv("SHADOWTOWER_POSTFX"), &s_postfx))
            fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_POSTFX; post-processing disabled. "
                            "Reset post-processing in the launcher and relaunch.\n");
        if (!shadowtower_postfx_strength(getenv("SHADOWTOWER_FXAA"), &s_postfx_fxaa) ||
            (s_postfx_fxaa != 0.f && s_postfx_fxaa != 1.f)) {
            s_postfx_fxaa = 0.f;
            fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_FXAA; use 0 or 1. FXAA disabled.\n");
        }
        if (!shadowtower_postfx_strength(getenv("SHADOWTOWER_SHARPEN"), &s_postfx_sharpen))
            fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_SHARPEN; use 0..1. Sharpening disabled.\n");
        if (s_postfx.enabled)
            fprintf(stdout, "Shadow Tower: post-processing enabled "
                            "(exposure %.3f, contrast %.3f, saturation %.3f, grain %.3f, "
                            "dither %.3f, bloom %.3f, scanlines %.3f, mask %.3f, curvature %.3f)\n",
                    s_postfx.exposure, s_postfx.contrast, s_postfx.saturation,
                    s_postfx.grain, s_postfx.dither, s_postfx.bloom,
                    s_postfx.scanlines, s_postfx.mask, s_postfx.curvature);
    }
    ShadowtowerPostFxUniforms *u = &s_postfx_uniforms[slot];
    if (u->program != program) {
        u->program = program;
        u->enabled = p_glGetUniformLocation(program, "u_postfx_enabled");
        u->color = p_glGetUniformLocation(program, "u_postfx_color");
        u->texture = p_glGetUniformLocation(program, "u_postfx_texture");
        u->crt = p_glGetUniformLocation(program, "u_postfx_crt");
        u->pitch = p_glGetUniformLocation(program, "u_postfx_pitch");
        u->time = p_glGetUniformLocation(program, "u_postfx_time");
        u->detail = p_glGetUniformLocation(program, "u_postfx_detail");
    }
    const int enabled = s_postfx.enabled && pitch > 0 && lines > 0 && out_h > 0;
    p_glUniform1i(u->enabled, enabled);
    if (!enabled) return;
    float gate = (float)out_h / (float)lines - 1.f;
    if (gate < 0.f) gate = 0.f;
    if (gate > 1.f) gate = 1.f;
    p_glUniform4f(u->color, s_postfx.exposure, s_postfx.contrast, s_postfx.saturation, s_postfx.bloom);
    p_glUniform2f(u->texture, s_postfx.grain, s_postfx.dither);
    p_glUniform4f(u->crt, s_postfx.curvature, s_postfx.scanlines, s_postfx.mask, gate);
    p_glUniform2f(u->detail, s_postfx_fxaa, s_postfx_sharpen);
    p_glUniform1f(u->pitch, (float)pitch);
    p_glUniform1f(u->time, (float)(SDL_GetTicks() % 100000));
}
