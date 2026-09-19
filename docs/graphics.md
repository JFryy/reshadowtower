# Selective texture filtering and seam correction

## Selected defaults

The user visually approved **selective filtering plus seam correction** after
comparing three runs of the same gameplay save: selective filtering with the new
correction limit, nearest sampling with the new limit, and nearest sampling with
the previous limit. This was gameplay validation, not a main-menu comparison.

The selected `[video]` settings in `game.toml` are:

```toml
renderer = "opengl"
supersampling = 3
window_width = 1280
aspect_ratio = "4:3"
texture_filtering = "bilinear"
antialiasing = false
geometry_correction = true
perspective_texturing = true
pgxp_tolerance = 1.0
```

No CRT shader, scanlines, texture replacements, temporal filtering, frame-rate
unlock, simulation changes, or pacing changes accompany this work. The existing
original-speed gameplay remains unchanged.

## Texture filtering

`src/world_texture_filter.glsl` supplies spatial texture sampling for this title's
OpenGL rasterizer, not a full-screen post-process:

- During magnification, smoothing is confined to roughly one internal raster
  pixel around texel boundaries, leaving broad texel interiors flat.
- During minification, four directional samples cover a footprint capped at four
  source texels along the larger screen-axis UV derivative. Each sample performs
  up to four decoded texel reads; this is not full anisotropic mipmapping.
- Samples retain the framework's palette decoding, texture-window handling, UV
  limits, and page wrapping. Transparent or different-STP neighbours do not
  contribute to the average. The original centre texel still decides cutout
  coverage and the STP bit used by blending and mask handling.
- Eligibility is per triangle: no rectangle sampling limits, an active validated
  subpixel-position override, modulated texturing, and no semi-transparent draw
  command. The eligibility attribute travels with each primitive through batching.
  Rectangle sprites, raw textures, unqualified polygons, and semi-transparent
  draws use nearest sampling. Movies and presentation shaders are unchanged.

This qualification is conservative, not a complete semantic world/HUD classifier.
It depends on available geometry precision; unqualified world polygons remain
unfiltered. Disabling geometry correction disables this filter's eligibility too.
The bounded footprint reduces aliasing but cannot eliminate all distant shimmer.
Original texture resolution and artwork are unchanged.

`texture_filtering = "bilinear"` enables this title-specific behavior on OpenGL;
`"nearest"` disables it. Software and Vulkan source code is unchanged and still
interprets `"bilinear"` as the framework's ordinary filtering. Vulkan is disabled
in the documented Linux build. Other games using the framework are unaffected.

## Floor seams

The investigation used disposable copies of local gameplay state slot 5 and
captured the composed OpenGL window with `present_shot`, polling completion.

- Floor cracks persisted with geometry correction disabled, with perspective
  texturing disabled, at 1× resolution, and with ordinary bilinear filtering.
- A temporary solid-color diagnostic, with texture cutout disabled, retained the
  cracks. This identifies raster coverage gaps rather than transparent texture
  borders. The diagnostic was not retained in the selected renderer.
- Allowing the full validated subpixel offset removed the prominent cracks in the
  stationary saved view. The previous `0.5` tolerance rejected most available
  position corrections; `1.0` admitted those corrections. This changes the host
  renderer's vertex placement, not game RAM or polygon expansion.
- Enabling PGXP CPU arithmetic tracking added no benefit in that comparison, so
  it was not enabled. Perspective correction qualified zero triangles in this
  room because depth provenance was missing; its existing setting remains on
  for geometry that can qualify elsewhere.

This is a visually validated mitigation, not a claim that all geometry cracks
throughout the game are solved. Sparse or ambiguous precision data can still
leave mixed corrected and uncorrected geometry. Full-game coverage is unproven.

## Build integration and checks

`cmake/graphics.cmake` runs `tools/prepare_graphics.py` to generate
`build-release/graphics/gpu_gl_renderer.c` from the pinned framework source and
the project-owned GLSL helper. The generated source replaces only this game's
OpenGL translation unit. The `psxrecomp` checkout and submodule revision are
unchanged. Integration anchors are checked; a preparation failure after a
framework update requires reviewing the adaptation, not editing generated C.

The preparation tool's responsibility is to generate the title-local renderer;
the GLSL helper's responsibility is selective spatial texture sampling. Shader
changes rebuild through CMake dependencies. Rebuild once when installing this
version; subsequent video setting changes require a restart only.

The Linux runtime build passed. Saved-game captures included the HUD, stationary
repeat frames, turning views, and a dark corridor; the user selected and approved
the filtered version. Local evidence and captures remain ignored under
`analysis/graphics-selective/`, `analysis/graphics-nearest-fullprecision/`, and
`analysis/graphics-original-comparison/`. No retail assets or savestates are
included in source control.

The focused synthetic OpenGL tests compile the actual generated shaders and
exercise disabled/ineligible filtering, transparent centres, STP separation,
4/8/15-bit texture addressing, UV bounds/windows, flat magnified interiors, and
minified checkerboard smoothing:

```bash
python3 -m unittest discover -s tests -p 'test_world_texture_filter.py' -v
```

These tests require SDL3, PyOpenGL, and an available OpenGL 3.3 display/context.
They report a skip when dependencies or a context are unavailable; a skip is not
a rendering pass. They do not establish full-game correctness, all blend/mask
combinations, or a measured performance guarantee.

## Disable or compare

Edit the existing `[video]` keys in `game.toml`, then restart:

- **Nearest with seam correction:** `texture_filtering = "nearest"`, retaining
  `pgxp_tolerance = 1.0`.
- **Previous defaults:** also restore `pgxp_tolerance = 0.5`. The earlier floor
  cracks may return.
- **Native integer vertex placement:** set `geometry_correction = false`. This
  also makes polygons ineligible for the selective filter.

Keep the selected settings unless comparing a specific artifact. Player settings
beside the executable (`build-release/settings.toml`) can override the game
profile, as can runtime diagnostic overrides such as `PSX_GEOMETRY_CORRECTION`.
