# Build a title-local renderer adaptation; never edit the pinned submodule.
find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
set(SHADOWTOWER_GL_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/graphics/gpu_gl_renderer.c")
add_custom_command(
    OUTPUT "${SHADOWTOWER_GL_SOURCE}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_graphics.py"
        --source "${PSXRECOMP_ROOT}/runtime/src/gpu_gl_renderer.c"
        --shader "${CMAKE_CURRENT_SOURCE_DIR}/src/world_texture_filter.glsl"
        --output "${SHADOWTOWER_GL_SOURCE}"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_graphics.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/world_texture_filter.glsl"
        "${PSXRECOMP_ROOT}/runtime/src/gpu_gl_renderer.c"
    COMMENT "Preparing Shadow Tower world-texture filtering"
    VERBATIM
)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES "${PSXRECOMP_ROOT}/runtime/src/gpu_gl_renderer.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_GL_SOURCE}")
