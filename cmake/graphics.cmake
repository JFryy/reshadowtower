set(SHADOWTOWER_GL_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/graphics/gpu_gl_renderer.c")
shadowtower_prepare("${SHADOWTOWER_GL_SOURCE}" "${PSXRECOMP_ROOT}/runtime/src/gpu_gl_renderer.c"
    runtime-graphics "${CMAKE_CURRENT_SOURCE_DIR}/src/world_texture_filter.glsl"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/post_processing.glsl")
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES "${PSXRECOMP_ROOT}/runtime/src/gpu_gl_renderer.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_GL_SOURCE}")

set(SHADOWTOWER_GPU_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/graphics/gpu.c")
shadowtower_prepare("${SHADOWTOWER_GPU_SOURCE}" "${PSXRECOMP_ROOT}/runtime/src/gpu.c" runtime-widescreen)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES "${PSXRECOMP_ROOT}/runtime/src/gpu.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_GPU_SOURCE}")
