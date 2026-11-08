// Screen-space ambient occlusion from depth alone; the PS1 has no normals.
// Depth holds 1 - 16/SZ (see src/depth_gl.h), so SZ is recovered exactly.
// The ring radius is a fixed world distance projected through the GTE focal
// length, and only neighbours nearer by less than the range occlude, so
// silhouettes against distant walls do not grow dark halos.
uniform sampler2D u_ao_depth;
uniform int u_ao_enabled;
uniform vec2 u_ao_texel;   // 1 / depth texture size
uniform float u_ao_scale;  // hi-res pixels per PS1 pixel
uniform vec4 u_ao_rect;    // displayed frame: min uv, max uv

const float AO_FOCAL = 300.0;      // GTE H set by the game's view setup
const float AO_RADIUS = 48.0;      // world units
const float AO_RANGE = 160.0;      // world units
const float AO_STRENGTH = 0.55;

float ao_sz(float depth) {
    return 16.0 / max(1.0 - depth, 1.0 / 65536.0);
}

float ambient_occlusion(vec2 uv) {
    if (u_ao_enabled == 0) return 1.0;
    float depth = texture(u_ao_depth, uv).r;
    if (depth >= 1.0) return 1.0;
    float sz = ao_sz(depth);
    float radius = clamp(AO_RADIUS * AO_FOCAL / sz * u_ao_scale, 1.0, 32.0 * u_ao_scale);
    float occlusion = 0.0;
    for (int i = 0; i < 12; ++i) {
        float angle = float(i) * 2.39996323;  // golden angle spreads the taps
        float reach = radius * (0.35 + 0.65 * fract(float(i) * 0.618034));
        vec2 offset = vec2(cos(angle), sin(angle)) * reach * u_ao_texel;
        float neighbour = texture(u_ao_depth, clamp(uv + offset, u_ao_rect.xy, u_ao_rect.zw)).r;
        if (neighbour >= 1.0) continue;
        float closer = sz - ao_sz(neighbour);
        occlusion += smoothstep(2.0, 24.0, closer) * (1.0 - smoothstep(AO_RANGE * 0.5, AO_RANGE, closer));
    }
    return 1.0 - AO_STRENGTH * occlusion / 12.0;
}
