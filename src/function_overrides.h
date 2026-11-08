#pragma once
/* Shadow Tower USA: hand-written C replacements for recompiled guest functions. */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct CPUState;

/* One resident code word; together they identify which overlay owns an address. */
typedef struct ShadowTowerCodeWord {
    uint32_t address;
    uint32_t value;
} ShadowTowerCodeWord;

/* Behaves like the guest function under the MIPS ABI: arguments in a0-a3 and
 * the caller's stack, results in v0/v1, s0-s8, gp and sp preserved. The registry
 * restores $ra and returns to it afterwards. Overrides charge no guest cycles
 * of their own; guest code they call through shadowtower_call_guest does.
 * Write guest memory through the psx_mod_* accessors. */
typedef void (*ShadowTowerOverrideFn)(struct CPUState *cpu);

/* Replace the guest function at address whenever every fingerprint word is
 * resident. The address must also be listed in game.toml under
 * [data_shards] funcs, which makes the recompiler emit the entry check that
 * patches/runtime-overrides.patch routes here. Returns 0 on invalid arguments,
 * a full registry, or a duplicate id. Register from a PSX_MOD_CONSTRUCTOR.
 *
 * With SHADOWTOWER_OVERRIDE_CHECK=1 each call runs the override and then the
 * generated code from the same CPU, RAM and scratchpad state, keeps the
 * generated result, and reports differences in the ABI-preserved and return
 * registers, GTE control registers, RAM and scratchpad, ignoring the callee's
 * dead stack. Only functions whose effects stay there can be checked this way.
 * The generated run repeats the function's other entry hooks, and calls that
 * take an interrupt or leave non-locally are counted as skipped.
 *
 * An overridden entry skips every hook the recompiler emits after it, such as
 * mod function-entry hooks and widescreen sprite tagging, so do not override
 * those functions. Generated code and the interpreter can both re-enter a
 * function at its first instruction, so do not override a function that
 * branches back to it. Data shards (a debug-server feature) cannot replay a
 * capture that contains an override, and check mode compares against shard
 * replays while they are enabled. */
int shadowtower_register_override(const char *id, uint32_t address,
                                  const ShadowTowerCodeWord *fingerprint,
                                  size_t fingerprint_count, ShadowTowerOverrideFn fn);

/* Call guest code at address from inside an override, as a jal from
 * return_address would. Returns 1 when it came back normally; on 0 a non-local
 * unwind is in progress and the override must return at once without touching
 * cpu. */
int shadowtower_call_guest(struct CPUState *cpu, uint32_t address, uint32_t return_address);

/* Called by the patched runtime at function entry. Returns 1 after running
 * the override and setting cpu->pc to the caller's $ra, 0 to run the body. */
int shadowtower_function_override(struct CPUState *cpu, uint32_t address);

#ifdef __cplusplus
}
#endif
