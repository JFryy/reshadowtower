uniform int u_postfx_enabled;
uniform vec4 u_postfx_color;   // exposure, contrast, saturation, bloom
uniform vec2 u_postfx_texture; // grain, dithering
uniform vec4 u_postfx_crt;     // curvature, scanlines, mask, scanline scale gate
uniform float u_postfx_pitch;
uniform float u_postfx_time;

// Keep every sample inside the displayed band, never adjacent VRAM content.
vec2 postfx_clamp(vec2 uv) {
    return clamp(uv, min(u_uv_rect.xy, u_uv_rect.zw), max(u_uv_rect.xy, u_uv_rect.zw));
}

vec2 postfx_uv(vec2 uv) {
    if (u_postfx_enabled == 0 || u_postfx_crt.x == 0.0) return uv;
    vec2 center = (u_uv_rect.xy + u_uv_rect.zw) * 0.5;
    vec2 half_size = max(abs(u_uv_rect.zw - u_uv_rect.xy) * 0.5, vec2(0.000001));
    vec2 p = (uv - center) / half_size;
    p *= 1.0 + u_postfx_crt.x * dot(p, p);
    return center + p * half_size;
}

bool postfx_outside(vec2 uv) {
    return u_postfx_enabled != 0 && u_postfx_crt.x > 0.0 &&
        (any(lessThan(uv, min(u_uv_rect.xy, u_uv_rect.zw))) ||
         any(greaterThan(uv, max(u_uv_rect.xy, u_uv_rect.zw))));
}

vec3 postfx_bright(vec2 uv) {
    return max(postfx_sample(postfx_clamp(uv)).rgb - vec3(0.7), vec3(0.0));
}

vec4 postfx_apply(vec4 color, vec2 uv) {
    if (u_postfx_enabled == 0) return color;
    vec3 rgb = color.rgb;
    if (u_postfx_color.w > 0.0) {
        vec2 size = vec2(postfx_size());
        vec2 step_uv = (size.y / max(u_postfx_pitch, 1.0)) / size;
        vec3 glow = postfx_bright(uv) * 4.0;
        glow += (postfx_bright(uv + vec2(step_uv.x, 0.0)) +
                 postfx_bright(uv - vec2(step_uv.x, 0.0)) +
                 postfx_bright(uv + vec2(0.0, step_uv.y)) +
                 postfx_bright(uv - vec2(0.0, step_uv.y))) * 2.0;
        glow += postfx_bright(uv + step_uv) + postfx_bright(uv - step_uv) +
                postfx_bright(uv + vec2(step_uv.x, -step_uv.y)) +
                postfx_bright(uv + vec2(-step_uv.x, step_uv.y));
        rgb += glow * (u_postfx_color.w / 16.0);
    }
    if (u_postfx_color.x != 0.0) rgb *= exp2(u_postfx_color.x);
    if (u_postfx_color.y != 1.0) rgb = (rgb - 0.5) * u_postfx_color.y + 0.5;
    if (u_postfx_color.z != 1.0)
        rgb = mix(vec3(dot(rgb, vec3(0.2126, 0.7152, 0.0722))), rgb, u_postfx_color.z);
    rgb = clamp(rgb, 0.0, 1.0);
    if (u_postfx_texture.y > 0.0) {
        const int bayer[16] = int[16](0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5);
        ivec2 p = ivec2(gl_FragCoord.xy) % 4;
        float threshold = (float(bayer[p.y * 4 + p.x]) + 0.5) / 16.0;
        vec3 quantized = floor(rgb * 31.0 + threshold) / 31.0;
        rgb = mix(rgb, quantized, u_postfx_texture.y);
    }
    if (u_postfx_texture.x > 0.0) {
        float noise = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233)) + u_postfx_time) * 43758.5453);
        rgb += (noise - 0.5) * u_postfx_texture.x;
    }
    if (u_postfx_crt.y > 0.0) {
        float beam = sin(3.14159265 * fract(uv.y * u_postfx_pitch));
        rgb *= 1.0 - u_postfx_crt.y * u_postfx_crt.w * (1.0 - beam);
    }
    if (u_postfx_crt.z > 0.0) {
        int channel = int(gl_FragCoord.x) % 3;
        vec3 mask = vec3(1.0 - u_postfx_crt.z);
        mask[channel] = 1.0;
        rgb *= mask;
    }
    return vec4(clamp(rgb, 0.0, 1.0), color.a);
}
