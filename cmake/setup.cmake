# Title-owned setup adapters and media; the pinned framework stays unchanged.
set(_setup_host_original "${PSXRECOMP_ROOT}/host/psxrecomp_codegen_host.c")
set(_setup_host_source "${CMAKE_CURRENT_BINARY_DIR}/setup/psxrecomp_codegen_host.c")
add_custom_command(OUTPUT "${_setup_host_source}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_setup.py"
        --source "${_setup_host_original}" --output "${_setup_host_source}"
    DEPENDS tools/prepare_setup.py "${_setup_host_original}"
    VERBATIM)

set(_setup_ui_original "${RECOMP_UI_ROOT}/src/common/backends/imgui/launcher_imgui.cpp")
set(_setup_ui_source "${CMAKE_CURRENT_BINARY_DIR}/setup/launcher_imgui.cpp")
add_custom_command(OUTPUT "${_setup_ui_source}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_setup_ui.py"
        --source "${_setup_ui_original}" --output "${_setup_ui_source}"
    DEPENDS tools/prepare_setup_ui.py "${_setup_ui_original}"
    VERBATIM)

get_target_property(_setup_sources psx-runtime SOURCES)
list(REMOVE_ITEM _setup_sources "${_setup_host_original}" "${_setup_ui_original}")
set_property(TARGET psx-runtime PROPERTY SOURCES "${_setup_sources}")
target_sources(psx-runtime PRIVATE
    "${_setup_host_source}" "${_setup_ui_source}"
    src/setup_music.cpp src/setup_music_ui.cpp)
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
