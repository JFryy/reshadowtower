# Crash-safe memory card writes: temp file + rename, a .bak per session, logged
# failures.
set(SHADOWTOWER_MEMCARD_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/saves/memcard.c")
shadowtower_prepare("${SHADOWTOWER_MEMCARD_SOURCE}"
                    "${PSXRECOMP_ROOT}/runtime/src/memcard.c" runtime-memcard)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES
     "${PSXRECOMP_ROOT}/runtime/src/memcard.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_MEMCARD_SOURCE}")
