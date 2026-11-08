// Per-pixel GTE lighting and fog for colours the GTE produced (see
// src/gte_lighting.h). Each context is six texels of u_light_context:
// rows of the light colour matrix with the background colour in w, then
// RGBC scale with the mode in w, the far colour, and the fog SZ range.
uniform sampler2D u_light_context;
uniform int u_pixel_lighting;
uniform int u_smooth_fog;

const int LIGHT_LIT = 1;
const int LIGHT_FOG = 2;
const int LIGHT_LIMIT = 4;

// Enhancement strength: per-pixel lit surfaces take LIGHT_DIFFUSE times the
// directional light over LIGHT_AMBIENT times the background colour.
const float LIGHT_DIFFUSE = 1.5;
const float LIGHT_AMBIENT = 0.6;

vec4 light_texel(int context, int k) {
    return texelFetch(u_light_context, ivec2(k, context), 0);
}

int light_mode(int context) {
    return int(light_texel(context, 3).w + 0.5);
}

// Colour before depth cueing, in GTE units (1.0 = 4096), from L*n, with the
// directional and background terms weighted by diffuse and ambient.
vec3 light_weighted(int context, vec3 light, float diffuse, float ambient) {
    if ((light_mode(context) & LIGHT_LIT) == 0) return light;
    float low = (light_mode(context) & LIGHT_LIMIT) != 0 ? 0.0 : -8.0;
    vec3 x = clamp(light, low, 8.0);
    vec4 r0 = light_texel(context, 0);
    vec4 r1 = light_texel(context, 1);
    vec4 r2 = light_texel(context, 2);
    vec3 y = ambient * vec3(r0.w, r1.w, r2.w) + diffuse * vec3(dot(r0.xyz, x), dot(r1.xyz, x), dot(r2.xyz, x));
    return clamp(y, low, 8.0);
}

// The GTE's own colour, used per vertex.
vec3 light_colour(int context, vec3 light) {
    return light_weighted(context, light, 1.0, 1.0);
}

// Colour before depth cueing for this pixel. Lit records relight from the
// interpolated L*n, renormalised against the unit vertex normals so faces
// bend light like the mesh does; others keep the interpolated vertex colour.
vec3 light_surface(int context, vec3 light, vec3 normal, vec3 vertex_colour) {
    if (u_pixel_lighting == 0 || (light_mode(context) & LIGHT_LIT) == 0) return vertex_colour;
    return light_weighted(context, light / max(length(normal), 1.0 / 4096.0), LIGHT_DIFFUSE, LIGHT_AMBIENT);
}

// The game's depth-cue amount for this pixel: per pixel from depth (1 - 16/SZ;
// 1 = none) when smooth fog is on, else the vertex IR0; 0 without fog.
float light_fog(int context, float ir0, float depth) {
    if ((light_mode(context) & LIGHT_FOG) == 0) return 0.0;
    vec4 range = light_texel(context, 5);
    if (u_smooth_fog == 0 || depth >= 1.0 || range.y <= range.x) return ir0;
    float sz = 16.0 / max(1.0 - depth, 1.0 / 65536.0);
    return clamp((sz - range.x) * 4096.0 / (range.y - range.x), 0.0, 4065.0) / 4096.0;
}

// Final 0..1 vertex colour, depth cued towards the far colour by t.
vec3 light_finish(int context, vec3 colour, float t) {
    colour += (light_texel(context, 4).rgb - colour) * t;
    return clamp(light_texel(context, 3).rgb * colour, 0.0, 255.0) / 255.0;
}
