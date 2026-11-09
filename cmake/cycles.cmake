# Scale guest CPU cycle charges while the frame-rate unlock draws extra frames.
# Generated code inlines the charge from the framework headers, and those
# headers include each other by quoted name, so the title builds against a full
# copy of them with psx_cyc.h patched. The build-time codegen hash header stays
# in the framework tree and is still found through the include path.
set(SHADOWTOWER_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/include")
file(GLOB SHADOWTOWER_FRAMEWORK_HEADERS CONFIGURE_DEPENDS
     "${PSXRECOMP_ROOT}/runtime/include/*")
list(FILTER SHADOWTOWER_FRAMEWORK_HEADERS EXCLUDE REGEX
     "/(psx_cyc\\.h|overlay_codegen_hash\\.h)$")
file(COPY ${SHADOWTOWER_FRAMEWORK_HEADERS}
     DESTINATION "${SHADOWTOWER_INCLUDE_DIR}")
# Copied at configure time, so an edited framework header reconfigures.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
             ${SHADOWTOWER_FRAMEWORK_HEADERS})
shadowtower_prepare(
  "${SHADOWTOWER_INCLUDE_DIR}/psx_cyc.h"
  "${PSXRECOMP_ROOT}/runtime/include/psx_cyc.h" runtime-cycle-charge)

set(SHADOWTOWER_CYCLES_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/cycles/psx_cycles.c")
shadowtower_prepare("${SHADOWTOWER_CYCLES_SOURCE}"
                    "${PSXRECOMP_ROOT}/runtime/src/psx_cycles.c" runtime-cycles)
list(REMOVE_ITEM PSXRECOMP_RUNTIME_SOURCES
     "${PSXRECOMP_ROOT}/runtime/src/psx_cycles.c")
list(APPEND PSXRECOMP_RUNTIME_SOURCES "${SHADOWTOWER_CYCLES_SOURCE}")
