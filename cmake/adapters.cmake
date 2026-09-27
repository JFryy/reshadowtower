find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)

# Prepare one pinned upstream source in the build tree, never in the submodule.
function(shadowtower_prepare output source patch)
    set(shader_args)
    set(shader_output)
    if(ARGN)
        list(APPEND shader_args --shader "${ARGN}")
        get_filename_component(directory "${output}" DIRECTORY)
        get_filename_component(name "${ARGN}" NAME_WE)
        set(shader_output "${directory}/${name}.inc")
    endif()
    add_custom_command(OUTPUT "${output}"
        BYPRODUCTS ${shader_output}
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_source.py"
            --source "${source}" --patch "${CMAKE_CURRENT_SOURCE_DIR}/patches/${patch}.patch"
            --output "${output}" ${shader_args}
        DEPENDS tools/prepare_source.py "${source}" "${CMAKE_CURRENT_SOURCE_DIR}/patches/${patch}.patch" ${ARGN}
        VERBATIM)
endfunction()
