cmake_minimum_required(VERSION 3.20)
project(NativeShadowTower LANGUAGES C CXX)

set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH "PSXRecomp checkout")
if(NOT EXISTS "${PSXRECOMP_ROOT}/runtime/runtime.cmake")
    message(FATAL_ERROR "Missing PSXRecomp. Run: git submodule update --init --recursive")
endif()
set(PSX_RECOMP_UI OFF CACHE BOOL "Build without the optional launcher" FORCE)
include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")
include(cmake/graphics.cmake)
include(cmake/input.cmake)

set(SHADOWTOWER_AOT_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/generated/aot/overlays_static.c")
if(NOT EXISTS "${SHADOWTOWER_AOT_SOURCE}")
    message(FATAL_ERROR "Missing native game modules. Run ./scripts/build.sh to generate them from your disc.")
endif()

psxrecomp_add_game_runtime(psx-runtime
    PRELOADED_MODS_DIR NONE
    WINDOW_TITLE "Shadow Tower Recompiled"
    DEFAULT_GAME_CONFIG_PATH "game.toml"
    MAX_PLAYERS 1
    GAME_OVERLAY_STATIC_C "${SHADOWTOWER_AOT_SOURCE}"
    GEN_MARKER "generated/SLUS_008.63_dispatch.c"
    GEN_FULL_GLOB "generated/SLUS_008.63_full_*.c"
)

if(NOT CMAKE_SYSTEM_NAME MATCHES "^(Linux|Windows)$")
    message(FATAL_ERROR "ReShadowTower currently supports Linux and Windows builds.")
endif()
if(NOT PSX_SDL3)
    message(FATAL_ERROR "Modern controls require SDL3. Configure with -DPSX_SDL_BACKEND=SDL3.")
endif()
configure_file(config.ini "${CMAKE_CURRENT_BINARY_DIR}/config.ini" COPYONLY)
target_sources(psx-runtime PRIVATE src/modern_controls.c)
if(WIN32 AND CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    # toml11 uses std::terminate without <exception>; libc++ no longer includes it indirectly.
    set_property(SOURCE
        "${PSXRECOMP_ROOT}/runtime/src/text_xlate.cpp"
        "${PSXRECOMP_ROOT}/runtime/src/mod_packages.cpp"
        APPEND PROPERTY COMPILE_OPTIONS -include exception)
endif()
# Generated title-local sources retain the framework's private helper includes.
target_include_directories(psx-runtime PRIVATE
    "${PSXRECOMP_ROOT}/runtime/src"
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
