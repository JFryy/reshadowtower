# Route recompiled [data_shards] funcs entries and interpreter entries to
# src/function_overrides.c.
set(SHADOWTOWER_SHARDS_SOURCE
    "${CMAKE_CURRENT_BINARY_DIR}/overrides/data_shards.c")
shadowtower_prepare(
  "${SHADOWTOWER_SHARDS_SOURCE}" "${PSXRECOMP_ROOT}/runtime/src/data_shards.c"
  runtime-overrides)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES
     "${PSXRECOMP_ROOT}/runtime/src/data_shards.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_SHARDS_SOURCE}")

set(SHADOWTOWER_INTERP_SOURCE
    "${CMAKE_CURRENT_BINARY_DIR}/overrides/dirty_ram_interp.c")
shadowtower_prepare(
  "${SHADOWTOWER_INTERP_SOURCE}"
  "${PSXRECOMP_ROOT}/runtime/src/dirty_ram_interp.c" runtime-overrides-interp)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES
     "${PSXRECOMP_ROOT}/runtime/src/dirty_ram_interp.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_INTERP_SOURCE}")
