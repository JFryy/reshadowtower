# Injected into the pinned recompiler via CMAKE_PROJECT_PSXRecomp_INCLUDE: build psxrecomp-game
# from a patched main_psx.cpp so overlay compiles emit the [data_shards] entry check.
find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
set(SHADOWTOWER_TITLE_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")

function(shadowtower_patch_recompiler)
    set(source "${CMAKE_CURRENT_SOURCE_DIR}/src/main_psx.cpp")
    set(output "${CMAKE_CURRENT_BINARY_DIR}/shadowtower/main_psx.cpp")
    set(patch "${SHADOWTOWER_TITLE_ROOT}/patches/recompiler-overrides.patch")
    add_custom_command(OUTPUT "${output}"
        COMMAND "${Python3_EXECUTABLE}" "${SHADOWTOWER_TITLE_ROOT}/tools/prepare_source.py"
            --source "${source}" --patch "${patch}" --output "${output}"
        DEPENDS "${SHADOWTOWER_TITLE_ROOT}/tools/prepare_source.py" "${source}" "${patch}"
        VERBATIM)
    get_target_property(sources psxrecomp-game SOURCES)
    list(FIND sources src/main_psx.cpp index)
    if(index EQUAL -1)
        message(FATAL_ERROR "psxrecomp-game no longer lists src/main_psx.cpp; review patches/recompiler-overrides.patch.")
    endif()
    list(REMOVE_AT sources ${index})
    list(INSERT sources ${index} "${output}")
    set_property(TARGET psxrecomp-game PROPERTY SOURCES ${sources})
    # The moved file still includes its neighbours and must rebuild with the codegen hash.
    target_include_directories(psxrecomp-game PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
    set_source_files_properties("${output}" PROPERTIES OBJECT_DEPENDS "${_baked_hash_hdr}")
endfunction()

cmake_language(DEFER CALL shadowtower_patch_recompiler)
