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

// Anisotropic minification without mipmaps: VRAM pages and CLUTs change between
// frames, so the footprint is integrated from decoded texels. Probes are spaced
// about one minor-axis width apart along the major axis; the minor axis is
// widened only when it minifies too. At most 8 probes (32 taps) per pixel.
const int WORLD_MAX_PROBES = 8;
const float WORLD_MAX_SPAN = 8.0;

vec3 world_filter(vec2 uv, vec2 dx, vec2 dy, int raw) {
    int stp = (raw >> 15) & 1;
    vec2 width = clamp(abs(dx) + abs(dy), vec2(0.0001), vec2(1.0));
    bool x_major = dot(dx, dx) > dot(dy, dy);
    vec2 major = x_major ? dx : dy;
    vec2 minor = x_major ? dy : dx;
    float span = length(major);
    uv += vec2(u_shift);
    vec4 color = world_sample(uv, width, stp);
    if (span > 1.0) {
        float minor_span = length(minor);
        bool widen = minor_span > 1.0;
        int budget = widen ? WORLD_MAX_PROBES / 2 : WORLD_MAX_PROBES;
        float covered = min(span, WORLD_MAX_SPAN);
        int probes = int(clamp(ceil(covered / max(minor_span, 1.0)), 2.0, float(budget)));
        vec2 along = major * (covered / span);
        vec2 across = widen ? minor * (min(minor_span, 2.0) / minor_span) * 0.25 : vec2(0.0);
        vec4 distant = vec4(0.0);
        for (int i = 0; i < WORLD_MAX_PROBES; ++i) {
            if (i >= probes) break;
            vec2 probe = uv + along * ((float(i) + 0.5) / float(probes) - 0.5);
            distant += widen
                ? 0.5 * (world_sample(probe - across, width, stp) + world_sample(probe + across, width, stp))
                : world_sample(probe, width, stp);
        }
        color = mix(color, distant / float(probes), smoothstep(1.0, 2.0, span));
    }
    return color.a > 0.0 ? color.rgb / color.a : col5(raw);
}
