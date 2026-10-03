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

set(SHADOWTOWER_SW_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/graphics/gpu_sw_renderer.c")
shadowtower_prepare("${SHADOWTOWER_SW_SOURCE}" "${PSXRECOMP_ROOT}/runtime/src/gpu_sw_renderer.c" runtime-software)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES "${PSXRECOMP_ROOT}/runtime/src/gpu_sw_renderer.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_SW_SOURCE}")

set(SHADOWTOWER_SETTINGS_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/graphics/config_loader.cpp")
shadowtower_prepare("${SHADOWTOWER_SETTINGS_SOURCE}" "${PSXRECOMP_ROOT}/recompiler/src/config_loader.cpp" runtime-settings)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES "${PSXRECOMP_ROOT}/recompiler/src/config_loader.cpp")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_SETTINGS_SOURCE}")
