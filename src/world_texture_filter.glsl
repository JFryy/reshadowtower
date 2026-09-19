// Decode through fetch_texel so palette, texture-window and UV bounds still apply.
// Exclude transparent and different-STP neighbours; the centre texel owns coverage.
vec4 world_tap(ivec2 p, int stp) {
    int raw = fetch_texel(p.x, p.y);
    if (raw == 0 || ((raw >> 15) & 1) != stp) return vec4(0.0);
    return vec4(col5(raw), 1.0);
}

// Confine magnification smoothing to about one raster pixel at texel boundaries.
vec4 world_sample(vec2 uv, vec2 width, int stp) {
    ivec2 p = ivec2(floor(uv));
    vec2 offset = fract(uv) - 0.5;
    ivec2 direction = ivec2(sign(offset));
    vec2 weight = max(abs(offset) - 0.5 * (1.0 - width), 0.0) / width;
    return world_tap(p, stp) * (1.0 - weight.x) * (1.0 - weight.y)
         + world_tap(p + ivec2(direction.x, 0), stp) * weight.x * (1.0 - weight.y)
         + world_tap(p + ivec2(0, direction.y), stp) * (1.0 - weight.x) * weight.y
         + world_tap(p + direction, stp) * weight.x * weight.y;
}

// Bounded four-tap directional minification, not mipmaps or temporal filtering.
vec3 world_filter(vec2 uv, vec2 dx, vec2 dy, int raw) {
    int stp = (raw >> 15) & 1;
    vec2 width = clamp(abs(dx) + abs(dy), vec2(0.0001), vec2(1.0));
    vec2 major = dot(dx, dx) > dot(dy, dy) ? dx : dy;
    float span = length(major);
    uv += vec2(u_shift);
    vec4 color = world_sample(uv, width, stp);
    if (span > 1.0) {
        vec2 footprint = major * (min(span, 4.0) / span);
        vec4 distant = vec4(0.0);
        for (int i = 0; i < 4; ++i) {
            float offset = (float(i) + 0.5) / 4.0 - 0.5;
            distant += world_sample(uv + footprint * offset, width, stp);
        }
        color = mix(color, distant * 0.25, smoothstep(1.0, 2.0, span));
    }
    return color.a > 0.0 ? color.rgb / color.a : col5(raw);
}
