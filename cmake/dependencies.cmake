include_guard(GLOBAL)
include(FetchContent)
if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()

if(NOT PSXRECOMP_ROOT AND DEFINED ENV{PSXRECOMP_ROOT})
    set(PSXRECOMP_ROOT "$ENV{PSXRECOMP_ROOT}")
endif()
if(PSXRECOMP_ROOT)
    get_filename_component(PSXRECOMP_ROOT "${PSXRECOMP_ROOT}" ABSOLUTE)
else()
    file(READ "${CMAKE_CURRENT_LIST_DIR}/dependencies.json" dependencies)
    string(JSON count LENGTH "${dependencies}")
    math(EXPR last "${count} - 1")
    foreach(index RANGE ${last})
        foreach(field name repository revision sha256 path)
            string(JSON ${field} GET "${dependencies}" ${index} ${field})
        endforeach()
        set(source_options)
        if(path)
            # Updating the parent archive removes child sources, so their download stamps must change too.
            set(source_options SOURCE_DIR "${PSXRECOMP_ROOT}/${path}"
                SUBBUILD_DIR "${CMAKE_BINARY_DIR}/_deps/${name}-${framework_revision}-subbuild")
        else()
            set(framework_revision "${revision}")
        endif()
        FetchContent_Declare(${name}
            URL "https://codeload.github.com/${repository}/tar.gz/${revision}"
            URL_HASH "SHA256=${sha256}"
            DOWNLOAD_DIR "${CMAKE_BINARY_DIR}/dependency-archives/${name}"
            DOWNLOAD_NAME "${revision}.tar.gz"
            ${source_options}
            SOURCE_SUBDIR .shadowtower-fetch-only)
        FetchContent_MakeAvailable(${name})
        if(NOT path)
            set(PSXRECOMP_ROOT "${psxrecomp_SOURCE_DIR}")
        endif()
    endforeach()
endif()
foreach(required runtime/runtime.cmake lib/recomp-net/CMakeLists.txt lib/retcomm-rbengine/CMakeLists.txt)
    if(NOT EXISTS "${PSXRECOMP_ROOT}/${required}")
        message(FATAL_ERROR "Framework sources are missing ${required}: ${PSXRECOMP_ROOT}. Supply a complete PSXRECOMP_ROOT for offline builds, or unset the override and allow fetching the pinned dependencies.")
    endif()
endforeach()
file(WRITE "${CMAKE_BINARY_DIR}/psxrecomp-source-dir.txt" "${PSXRECOMP_ROOT}\n")
