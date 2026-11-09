/* Shadow Tower USA: registry and differential check for hand-written function overrides. */
#include "function_overrides.h"
#include "cpu_state.h"
#include "mod_plugins.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_OVERRIDES 64
#define MAX_FINGERPRINT 8
#define RAM_BYTES (2u * 1024u * 1024u)
#define SCRATCHPAD_BYTES 1024u
#define SCRATCHPAD_BASE 0x1F800000u
/* Frames below the entry $sp are dead after return and hold generated-code spills. */
#define DEAD_STACK_BYTES 0x10000u
#define MAX_REPORTED_DIFFS 8
/* Strips the KSEG0/KSEG1 segment bits, leaving the physical address. */
#define PHYSICAL_ADDRESS_MASK 0x1FFFFFFFu
/* RAM is mirrored across the first 8 MiB of the physical address space. */
#define RAM_MIRROR_END 0x00800000u
/* Argument home slots above $sp that a callee may spill into. */
#define ARG_HOME_BYTES 16u

extern uint8_t *memory_get_ram_ptr(void);
extern uint8_t *memory_get_scratchpad_ptr(void);
extern uint64_t g_irq_deliver_count;
extern int g_psx_dispatch_depth;

typedef struct Override {
    const char *id;
    uint32_t address;
    ShadowTowerCodeWord fingerprint[MAX_FINGERPRINT];
    size_t fingerprint_count;
    ShadowTowerOverrideFn fn;
    uint64_t matched, mismatched, skipped;
} Override;

typedef struct Snapshot {
    CPUState cpu;
    uint8_t ram[RAM_BYTES];
    uint8_t scratchpad[SCRATCHPAD_BYTES];
} Snapshot;

static Override overrides[MAX_OVERRIDES];
static size_t override_count;
static int check_enabled;
static Snapshot *entry_state, *override_state;
/* Overrides reached while a check is live must not start another one. */
enum { CHECK_IDLE, CHECK_OVERRIDE, CHECK_GENERATED };
static int check_phase = CHECK_IDLE;
static int check_depth;
/* The next entry at this address runs its generated body (shadowtower_call_original). */
static uint32_t bypass_address;

static int fingerprint_resident(const Override *item) {
    for (size_t i = 0; i < item->fingerprint_count; ++i)
        if (psx_mod_read_word(item->fingerprint[i].address) != item->fingerprint[i].value)
            return 0;
    return 1;
}

static const Override *resident_override(uint32_t address) {
    for (size_t i = 0; i < override_count; ++i)
        if (((overrides[i].address ^ address) & PHYSICAL_ADDRESS_MASK) == 0 &&
            fingerprint_resident(&overrides[i]))
            return &overrides[i];
    return NULL;
}

static void capture(Snapshot *snapshot, const CPUState *cpu) {
    snapshot->cpu = *cpu;
    memcpy(snapshot->ram, memory_get_ram_ptr(), RAM_BYTES);
    memcpy(snapshot->scratchpad, memory_get_scratchpad_ptr(), SCRATCHPAD_BYTES);
}

static void restore(const Snapshot *snapshot, CPUState *cpu) {
    *cpu = snapshot->cpu;
    memcpy(memory_get_ram_ptr(), snapshot->ram, RAM_BYTES);
    memcpy(memory_get_scratchpad_ptr(), snapshot->scratchpad, SCRATCHPAD_BYTES);
}

/* Offsets of the callee-owned stack, [sp - DEAD_STACK_BYTES, sp + ARG_HOME_BYTES), within one memory.
 * The bytes above sp are the argument home slots. */
static void dead_stack(uint32_t sp, uint32_t base, uint32_t size, uint32_t *low, uint32_t *high) {
    *low = *high = 0;
    const uint32_t physical = sp & PHYSICAL_ADDRESS_MASK;
    uint32_t top;
    if (base == 0 && physical < RAM_MIRROR_END) { /* RAM and its mirrors */
        top = physical & (RAM_BYTES - 1);
        if (!top && physical) top = RAM_BYTES;
    } else if (base != 0 && physical >= base && physical <= base + size) {
        top = physical - base;
    } else {
        return;
    }
    *low = top > DEAD_STACK_BYTES ? top - DEAD_STACK_BYTES : 0;
    *high = top + ARG_HOME_BYTES < size ? top + ARG_HOME_BYTES : size;
}

static int compare_memory(const char *name, uint32_t guest_base,
                          const uint8_t *expected, const uint8_t *actual, uint32_t size,
                          uint32_t skip_low, uint32_t skip_high, int reported, int verbose) {
    for (uint32_t i = 0; i < size; ++i) {
        if (i >= skip_low && i < skip_high) {
            i = skip_high - 1;
            continue;
        }
        if (expected[i] == actual[i]) continue;
        uint32_t end = i + 1;
        while (end < size && expected[end] != actual[end] && !(end >= skip_low && end < skip_high))
            ++end;
        if (verbose && reported < MAX_REPORTED_DIFFS)
            fprintf(stderr, "Shadow Tower:   %s 0x%08X: %u byte(s) differ, generated 0x%02X, override 0x%02X\n",
                    name, guest_base + i, end - i, expected[i], actual[i]);
        ++reported;
        i = end - 1;
    }
    return reported;
}

/* Registers the caller can rely on after a MIPS ABI call returns. */
static const int abi_registers[] = {2, 3, 16, 17, 18, 19, 20, 21, 22, 23, 28, 29, 30};

/* Counts differences; prints the first few only when verbose. */
static int compare_results(const Snapshot *expected, const Snapshot *actual,
                           uint32_t entry_sp, int verbose) {
    int reported = 0;
    for (size_t i = 0; i < sizeof abi_registers / sizeof abi_registers[0]; ++i) {
        const int r = abi_registers[i];
        if (expected->cpu.gpr[r] == actual->cpu.gpr[r]) continue;
        if (reported++ < MAX_REPORTED_DIFFS && verbose)
            fprintf(stderr, "Shadow Tower:   r%d: generated 0x%08X, override 0x%08X\n",
                    r, expected->cpu.gpr[r], actual->cpu.gpr[r]);
    }
    /* GTE control registers hold matrices and vectors that outlive the call. */
    for (int r = 0; r < 32; ++r) {
        if (expected->cpu.gte_ctrl[r] == actual->cpu.gte_ctrl[r]) continue;
        if (reported++ < MAX_REPORTED_DIFFS && verbose)
            fprintf(stderr, "Shadow Tower:   GTE control %d: generated 0x%08X, override 0x%08X\n",
                    r, expected->cpu.gte_ctrl[r], actual->cpu.gte_ctrl[r]);
    }
    uint32_t low, high;
    dead_stack(entry_sp, 0, RAM_BYTES, &low, &high);
    reported = compare_memory("RAM", 0x80000000u, expected->ram, actual->ram,
                              RAM_BYTES, low, high, reported, verbose);
    dead_stack(entry_sp, SCRATCHPAD_BASE, SCRATCHPAD_BYTES, &low, &high);
    return compare_memory("scratchpad", SCRATCHPAD_BASE, expected->scratchpad,
                          actual->scratchpad, SCRATCHPAD_BYTES, low, high, reported, verbose);
}

/* Run override, then generated code from the same state; the generated result stays live. */
static void run_checked(Override *item, CPUState *cpu, uint32_t address) {
    const uint32_t ra = cpu->gpr[31];
    const uint32_t sp = cpu->gpr[29];
    capture(entry_state, cpu);
    check_depth = g_psx_dispatch_depth;
    check_phase = CHECK_OVERRIDE;
    item->fn(cpu);
    /* A guest call inside the override began a bail unwind; compare nothing. */
    const int override_left = g_psx_call_bail;
    g_psx_call_bail = 0;
    cpu->gpr[31] = ra;
    capture(override_state, cpu);
    restore(entry_state, cpu);

    const uint64_t interrupts = g_irq_deliver_count;
    check_phase = CHECK_GENERATED;
    cpu->pc = 0;
    psx_dispatch_call(cpu, address, ra);
    check_phase = CHECK_IDLE;
    if (g_psx_call_bail || cpu->pc != 0) {
        ++item->skipped; /* Control left through a non-local path; leave it to the dispatcher. */
        return;
    }
    cpu->pc = ra;
    if (override_left || g_irq_deliver_count != interrupts) {
        ++item->skipped; /* The override bailed, or an interrupt handler ran inside the generated call. */
        return;
    }
    capture(entry_state, cpu);
    const int differences = compare_results(entry_state, override_state, sp, !item->mismatched);
    if (!differences) {
        ++item->matched;
        return;
    }
    if (!item->mismatched)
        fprintf(stderr, "Shadow Tower: override %s (0x%08X) differs from generated code "
                "(%d difference(s); first call shown).\n", item->id, address, differences);
    ++item->mismatched;
}

int shadowtower_function_override(CPUState *cpu, uint32_t address) {
    if (!override_count) return 0;
    if (bypass_address && ((bypass_address ^ address) & PHYSICAL_ADDRESS_MASK) == 0) {
        bypass_address = 0;
        return 0;
    }
    /* An exception unwind can skip the reset in run_checked; a live check is always shallower. */
    if (check_phase != CHECK_IDLE && g_psx_dispatch_depth <= check_depth) check_phase = CHECK_IDLE;
    /* The reference run must be entirely generated code. */
    if (check_phase == CHECK_GENERATED) return 0;
    Override *item = (Override *)resident_override(address);
    if (!item) return 0;
    if (check_enabled && check_phase == CHECK_IDLE) {
        run_checked(item, cpu, address);
        return 1;
    }
    const uint32_t ra = cpu->gpr[31];
    item->fn(cpu);
    if (g_psx_call_bail) return 1; /* cpu->pc already holds the unwind target. */
    cpu->gpr[31] = ra;
    cpu->pc = ra;
    return 1;
}

int shadowtower_call_guest(CPUState *cpu, uint32_t address, uint32_t return_address) {
    const uint32_t sp = cpu->gpr[29];
    cpu->gpr[31] = return_address;
    cpu->pc = 0;
    psx_dispatch_call(cpu, address, return_address);
    return !psx_call_contract(cpu, return_address, sp);
}

int shadowtower_call_original(CPUState *cpu, uint32_t address) {
    bypass_address = address;
    const int returned = shadowtower_call_guest(cpu, address, cpu->gpr[31]);
    bypass_address = 0; /* Not consumed when the entry has no override check. */
    return returned;
}

static void report_checks(void) {
    for (size_t i = 0; i < override_count; ++i)
        fprintf(stderr, "Shadow Tower: override check %s: %llu matched, %llu differed, %llu skipped\n",
                overrides[i].id, (unsigned long long)overrides[i].matched,
                (unsigned long long)overrides[i].mismatched,
                (unsigned long long)overrides[i].skipped);
}

static void enable_check(void) {
    entry_state = malloc(sizeof *entry_state);
    override_state = malloc(sizeof *override_state);
    if (!entry_state || !override_state) {
        fprintf(stderr, "Shadow Tower: cannot allocate override check snapshots; "
                "running overrides without the check.\n");
        free(entry_state);
        free(override_state);
        entry_state = override_state = NULL;
        return;
    }
    check_enabled = 1;
    if (atexit(report_checks))
        fprintf(stderr, "Shadow Tower: cannot register override check summary.\n");
}

static void configure_check(void) {
    static int configured;
    if (configured) return;
    configured = 1;
    const char *check = getenv("SHADOWTOWER_OVERRIDE_CHECK");
    if (!check || !strcmp(check, "0")) return;
    if (!strcmp(check, "1")) enable_check();
    else fprintf(stderr, "Shadow Tower: invalid SHADOWTOWER_OVERRIDE_CHECK '%s'; use 0 or 1.\n", check);
}

int shadowtower_register_override(const char *id, uint32_t address,
                                  const ShadowTowerCodeWord *fingerprint,
                                  size_t fingerprint_count, ShadowTowerOverrideFn fn) {
    const char *name = id ? id : "(null)";
    if (!id || !*id) {
        fprintf(stderr, "Shadow Tower: cannot register override '%s': missing id.\n", name);
        return 0;
    }
    if (!address) {
        fprintf(stderr, "Shadow Tower: cannot register override '%s': address 0.\n", name);
        return 0;
    }
    if (!fn) {
        fprintf(stderr, "Shadow Tower: cannot register override '%s': missing function.\n", name);
        return 0;
    }
    if (!fingerprint || !fingerprint_count) {
        fprintf(stderr, "Shadow Tower: cannot register override '%s': missing fingerprint.\n", name);
        return 0;
    }
    if (fingerprint_count > MAX_FINGERPRINT) {
        fprintf(stderr, "Shadow Tower: cannot register override '%s': fingerprint has %zu words "
                "(max %d).\n", name, fingerprint_count, MAX_FINGERPRINT);
        return 0;
    }
    if (override_count == MAX_OVERRIDES) {
        fprintf(stderr, "Shadow Tower: cannot register override '%s': registry full "
                "(%d overrides).\n", name, MAX_OVERRIDES);
        return 0;
    }
    for (size_t i = 0; i < override_count; ++i)
        if (!strcmp(overrides[i].id, id)) {
            fprintf(stderr, "Shadow Tower: cannot register override '%s': duplicate id.\n", name);
            return 0;
        }
    configure_check();

    Override *item = &overrides[override_count++];
    *item = (Override){.id = id, .address = address, .fingerprint_count = fingerprint_count, .fn = fn};
    memcpy(item->fingerprint, fingerprint, fingerprint_count * sizeof *fingerprint);
    return 1;
}
