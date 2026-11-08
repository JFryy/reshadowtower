#pragma once

#define SHADOWTOWER_GL_MAX_RENDERBUFFER_SIZE 0x84E8
#define SHADOWTOWER_GL_DEPTH_STENCIL 0x84F9
#define SHADOWTOWER_GL_UNSIGNED_INT_24_8 0x84FA

/* Allocate complete high-resolution targets transactionally, retrying smaller
 * scales without leaving failed textures or framebuffer attachments alive. */
static int shadowtower_allocate_render_targets(int requested) {
    GLint texture_limit = 0, renderbuffer_limit = 0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &texture_limit);
    glGetIntegerv(SHADOWTOWER_GL_MAX_RENDERBUFFER_SIZE, &renderbuffer_limit);
    int scale = shadowtower_scale_for_limits(requested, texture_limit, renderbuffer_limit);
    if (!scale) {
        fprintf(stderr, "Shadow Tower: GPU limits cannot fit native VRAM targets. Check the OpenGL driver.\n");
        return 0;
    }
    for (; scale; scale = shadowtower_lower_scale(scale)) {
        GLuint color = 0, scratch = 0, depth = 0, frame = 0, scratch_frame = 0;
        GLenum error = GL_NO_ERROR;
        int width = VRAM_W * scale, height = VRAM_H * scale;
        color = make_tex(GL_RGBA8, width, height, GL_RGBA, GL_UNSIGNED_BYTE);
        error = glGetError();
        if (!color || error != GL_NO_ERROR) goto failed;
        scratch = make_tex(GL_RGBA8, width, height, GL_RGBA, GL_UNSIGNED_BYTE);
        error = glGetError();
        if (!scratch || error != GL_NO_ERROR) goto failed;
        /* A texture, not a renderbuffer, so ambient occlusion can sample depth. */
        depth = make_tex(PSXGL_DEPTH24_STENCIL8, width, height, SHADOWTOWER_GL_DEPTH_STENCIL,
                         SHADOWTOWER_GL_UNSIGNED_INT_24_8);
        error = glGetError();
        if (!depth || error != GL_NO_ERROR) goto failed;
        if (!make_fbo(&frame, color, 0) || !make_fbo(&scratch_frame, scratch, 0)) goto failed;
        p_glBindFramebuffer(PSXGL_FRAMEBUFFER, frame);
        p_glFramebufferTexture2D(PSXGL_FRAMEBUFFER, PSXGL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, depth, 0);
        GLenum status = p_glCheckFramebufferStatus(PSXGL_FRAMEBUFFER);
        p_glBindFramebuffer(PSXGL_FRAMEBUFFER, 0);
        error = glGetError();
        if (status != PSXGL_FRAMEBUFFER_COMPLETE || error != GL_NO_ERROR) goto failed;
        s_hr_tex = color; s_scratch_tex = scratch; s_hr_depth_tex = depth;
        s_hr_fbo = frame; s_scratch_fbo = scratch_frame;
        s_scale = scale;
        if (scale != requested) {
            char message[160];
            snprintf(message, sizeof(message), "GPU could not use %dx rendering; using %dx. Lower resolution scale if needed.", requested, scale);
            fprintf(stderr, "Shadow Tower: %s\n", message);
            host_osd_push(message, 8000);
        }
        return 1;
    failed:
        fprintf(stderr, "Shadow Tower: %dx GPU targets failed (GL error 0x%X); retrying a lower scale.\n", scale, error);
        p_glBindFramebuffer(PSXGL_FRAMEBUFFER, 0);
        glBindTexture(GL_TEXTURE_2D, 0);
        if (frame) p_glDeleteFramebuffers(1, &frame);
        if (scratch_frame) p_glDeleteFramebuffers(1, &scratch_frame);
        if (depth) glDeleteTextures(1, &depth);
        if (color) glDeleteTextures(1, &color);
        if (scratch) glDeleteTextures(1, &scratch);
        for (int count = 0; count < 8; ++count) {
            error = glGetError();
            if (error == GL_NO_ERROR) break;
            fprintf(stderr, "Shadow Tower: GPU allocation cleanup reported GL error 0x%X.\n", error);
        }
    }
    fprintf(stderr, "Shadow Tower: even 1x GPU targets failed. Falling back to software; check available GPU memory and the driver.\n");
    return 0;
}
