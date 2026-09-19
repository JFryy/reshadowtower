# Explicit title-owned adapters work with both ELF and Windows DLL imports.
set(SHADOWTOWER_MAIN_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/input/main.cpp")
add_custom_command(
    OUTPUT "${SHADOWTOWER_MAIN_SOURCE}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_input.py"
        --source "${PSXRECOMP_ROOT}/runtime/src/main.cpp"
        --output "${SHADOWTOWER_MAIN_SOURCE}"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_input.py"
        "${PSXRECOMP_ROOT}/runtime/src/main.cpp"
    COMMENT "Preparing portable Shadow Tower input adapters"
    VERBATIM
)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES "${PSXRECOMP_ROOT}/runtime/src/main.cpp")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_MAIN_SOURCE}")
