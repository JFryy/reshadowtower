cmake_minimum_required(VERSION 3.20)
project(NativeShadowTower LANGUAGES C CXX)

set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH "PSXRecomp checkout")
if(NOT EXISTS "${PSXRECOMP_ROOT}/runtime/runtime.cmake")
    message(FATAL_ERROR "Missing PSXRecomp. Run: git submodule update --init --recursive")
endif()
if(PSXRECOMP_FORCE_SETUP_HOST)
    set(PSX_RECOMP_UI ON CACHE BOOL "Enable the first-run setup wizard" FORCE)
    # Never consume locally generated BIOS backends when building a distributor.
    set(PSXRECOMP_BIOS_STEMS "SetupHost")
    set(PSXRECOMP_ALLOW_NO_BIOS ON)
else()
    option(PSX_RECOMP_UI "Enable the launcher" OFF)
endif()
include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")
include(cmake/graphics.cmake)
include(cmake/input.cmake)

set(SHADOWTOWER_AOT_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/generated/aot/overlays_static.c")
if(NOT PSXRECOMP_FORCE_SETUP_HOST AND NOT EXISTS "${SHADOWTOWER_AOT_SOURCE}")
    message(FATAL_ERROR "Missing native game modules. Run ./scripts/build.sh to generate them from your disc.")
endif()
if(PSXRECOMP_FORCE_SETUP_HOST)
    set(SHADOWTOWER_AOT_SOURCE "")
endif()

psxrecomp_add_game_runtime(psx-runtime
    PRELOADED_MODS_DIR NONE
    ENABLE_SETUP_WIZARD
    WINDOW_TITLE "Shadow Tower Recompiled"
    DEFAULT_GAME_CONFIG_PATH "game.toml"
    MAX_PLAYERS 1
    GAME_OVERLAY_STATIC_C "${SHADOWTOWER_AOT_SOURCE}"
    GEN_MARKER "generated/SLUS_008.63_dispatch.c"
    GEN_FULL_GLOB "generated/SLUS_008.63_full_*.c"
    CODEGEN_SETUP_SOURCES codegen_setup.c
    LAUNCHER_BOXART "${CMAKE_CURRENT_SOURCE_DIR}/assets/setup/boxart.tga"
)

if(PSX_RECOMP_UI)
    set(_setup_source "${CMAKE_CURRENT_BINARY_DIR}/setup/psxrecomp_codegen_host.c")
    add_custom_command(OUTPUT "${_setup_source}"
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_setup.py"
            --source "${PSXRECOMP_ROOT}/host/psxrecomp_codegen_host.c"
            --output "${_setup_source}"
        DEPENDS tools/prepare_setup.py "${PSXRECOMP_ROOT}/host/psxrecomp_codegen_host.c"
        VERBATIM)
    get_target_property(_setup_sources psx-runtime SOURCES)
    list(REMOVE_ITEM _setup_sources "${PSXRECOMP_ROOT}/host/psxrecomp_codegen_host.c")
    set_property(TARGET psx-runtime PROPERTY SOURCES "${_setup_sources}")
    target_sources(psx-runtime PRIVATE "${_setup_source}")

    set(_setup_ui_original "${RECOMP_UI_ROOT}/src/common/backends/imgui/launcher_imgui.cpp")
    set(_setup_ui_source "${CMAKE_CURRENT_BINARY_DIR}/setup/launcher_imgui.cpp")
    add_custom_command(OUTPUT "${_setup_ui_source}"
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_setup_ui.py"
            --source "${_setup_ui_original}" --output "${_setup_ui_source}"
        DEPENDS tools/prepare_setup_ui.py "${_setup_ui_original}"
        VERBATIM)
    get_target_property(_setup_sources psx-runtime SOURCES)
    list(REMOVE_ITEM _setup_sources "${_setup_ui_original}")
    set_property(TARGET psx-runtime PROPERTY SOURCES "${_setup_sources}")
    target_sources(psx-runtime PRIVATE "${_setup_ui_source}" src/setup_music.cpp)
    target_include_directories(psx-runtime PRIVATE "${RECOMP_UI_ROOT}/src/common/backends/imgui")
    add_custom_command(TARGET psx-runtime POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E make_directory "$<TARGET_FILE_DIR:psx-runtime>/assets/setup"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/assets/setup/music.wav"
            "$<TARGET_FILE_DIR:psx-runtime>/assets/setup/music.wav"
        VERBATIM)
    set_property(TARGET psx-runtime APPEND PROPERTY LINK_DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/assets/setup/music.wav"
        "${CMAKE_CURRENT_SOURCE_DIR}/assets/setup/boxart.tga")
endif()

if(PSXRECOMP_FORCE_SETUP_HOST)
    file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/setup-sources.txt"
        CONTENT "$<JOIN:$<TARGET_PROPERTY:psx-runtime,SOURCES>,\n>\n")
endif()

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
