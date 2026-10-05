# Prepare the framework's source fingerprint before offline AOT generation.
if(NOT PSXRECOMP_ROOT)
    message(FATAL_ERROR "PSXRECOMP_ROOT is required to generate the codegen hash.")
endif()
set(PSXRECOMP_CODEGEN_HASH_ROOT "${PSXRECOMP_ROOT}")
include("${PSXRECOMP_ROOT}/runtime/codegen_hash_sources.cmake")
set(OUT "${PSXRECOMP_ROOT}/runtime/include/overlay_codegen_hash.h")
set(SRCS "${PSXRECOMP_CODEGEN_HASH_SRCS}")
include("${PSXRECOMP_ROOT}/runtime/hash_codegen.cmake")
