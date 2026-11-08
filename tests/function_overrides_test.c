#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Stubbed runtime: cpu_state.h and mod_plugins.h are empty in the test include path. */
typedef struct CPUState { uint32_t gpr[32]; uint32_t pc, hi, lo; uint32_t gte_ctrl[32]; } CPUState;
uint8_t ram[2 * 1024 * 1024], scratch[1024];
uint8_t *memory_get_ram_ptr(void) { return ram; }
uint8_t *memory_get_scratchpad_ptr(void) { return scratch; }
uint64_t g_irq_deliver_count;
int g_psx_dispatch_depth, g_psx_call_bail;
uint32_t psx_mod_read_word(uint32_t a) { uint32_t v; memcpy(&v, ram + (a & 0x1FFFFF), 4); return v; }
int shadowtower_function_override(CPUState *cpu, uint32_t address);
#define hook shadowtower_function_override
/* Generated-code stand-in: v0 = a0 + a1, store it, spill to the stack, clobber t0. */
int generated_calls, nested_result = -1, inner_result = -1, raise_irq, bail, guest_calls, callee_bail;
uint32_t inner_address;
#define GUEST_DOUBLE 0x80006000u
/* Mirrors the runtime's post-call check: a bail in progress, or a callee that did not return here. */
static int psx_call_contract(CPUState *cpu, uint32_t site_ra, uint32_t site_sp) {
    if (g_psx_call_bail) return 1;
    if (cpu->gpr[29] != site_sp || ((cpu->gpr[31] ^ site_ra) & 0x1FFFFFFFu)) {
        g_psx_call_bail = 1;
        cpu->pc = cpu->gpr[31];
        return 1;
    }
    return 0;
}
void psx_dispatch_call(CPUState *cpu, uint32_t addr, uint32_t ra) {
    (void)ra;
    if (addr == GUEST_DOUBLE) { /* Guest leaf an override calls: v0 = a0 * 2. */
        ++guest_calls;
        cpu->gpr[2] = cpu->gpr[4] * 2;
        if (callee_bail) { g_psx_call_bail = 1; cpu->pc = 0x80009999; }
        return;
    }
    ++generated_calls;
    ++g_psx_dispatch_depth;
    nested_result = hook(cpu, addr);
    /* A generated body may call another overridden function. */
    if (inner_address) inner_result = hook(cpu, inner_address);
    cpu->gpr[2] = cpu->gpr[4] + cpu->gpr[5];
    memcpy(ram + 0x100, &cpu->gpr[2], 4);
    memset(ram + (cpu->gpr[29] & 0x1FFFFF) - 8, 0xAB, 8);
    cpu->gpr[8] = 0xDEAD;
    if (raise_irq) ++g_irq_deliver_count;
    if (bail) { g_psx_call_bail = 1; cpu->pc = 0x80001234; }
    --g_psx_dispatch_depth;
}
#include "function_overrides.c"
#define T(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s\n", #x); return 1; } } while (0)

static void add(CPUState *cpu) {
    cpu->gpr[2] = cpu->gpr[4] + cpu->gpr[5];
    memcpy(ram + 0x100, &cpu->gpr[2], 4);
}
static void wrong(CPUState *cpu) { cpu->gpr[2] = 7; }
static void gte(CPUState *cpu) { add(cpu); cpu->gte_ctrl[0] = 1; }
static uint32_t call(CPUState *cpu, uint32_t address, int *handled) {
    cpu->gpr[4] = 2; cpu->gpr[5] = 3; cpu->gpr[29] = 0x801FFF00; cpu->gpr[31] = 0x80010040;
    cpu->gpr[2] = 0; cpu->gpr[8] = 0; cpu->pc = 0;
    memset(ram + 0x100, 0, 4);
    *handled = hook(cpu, address);
    return cpu->gpr[2];
}

/* Non-leaf override: 2 * a0 through guest code, plus one; equals a0 + a1 for (2, 3). */
static void via_guest(CPUState *cpu) {
    if (!shadowtower_call_guest(cpu, GUEST_DOUBLE, 0x80007008)) return;
    cpu->gpr[2] += 1;
    memcpy(ram + 0x100, &cpu->gpr[2], 4);
}

static Override *find(const char *id) {
    for (size_t i = 0; i < override_count; ++i)
        if (!strcmp(overrides[i].id, id)) return &overrides[i];
    return NULL;
}

/* Overrides that call guest code restore $ra and leave a guest bail unwind alone. */
static int guest_call_tests(int checking) {
    CPUState cpu = {0};
    int handled;
    T(shadowtower_register_override("guest", 0x80007000, (ShadowTowerCodeWord[]){{0x80001000, 0x27BDFFE8}}, 1, via_guest));
    T(call(&cpu, 0x80007000, &handled) == 5 && handled && guest_calls == 1);
    T(cpu.pc == 0x80010040 && cpu.gpr[31] == 0x80010040 && !g_psx_call_bail);
    callee_bail = 1;
    call(&cpu, 0x80007000, &handled);
    callee_bail = 0;
    if (checking) {
        /* The bail is cleared, the generated run supplies the result, and the call is skipped. */
        T(handled && !g_psx_call_bail && cpu.pc == 0x80010040 && cpu.gpr[2] == 5);
        T(find("guest")->matched == 1 && find("guest")->skipped == 1);
    } else {
        T(handled && g_psx_call_bail && cpu.pc == 0x80009999);
        g_psx_call_bail = 0;
    }
    return 0;
}

int main(void) {
    const char *check = getenv("SHADOWTOWER_OVERRIDE_CHECK");
    const int checking = check && strcmp(check, "1") == 0;
    const uint32_t code = 0x27BDFFE8;
    memcpy(ram + 0x1000, &code, 4);
    const ShadowTowerCodeWord resident[] = {{0x80001000, 0x27BDFFE8}};
    const ShadowTowerCodeWord other[] = {{0x80001000, 0x12345678}};

    /* Registration validates input; nothing is handled before an override exists. */
    CPUState empty = {0};
    T(!hook(&empty, 0x80001000));
    T(!shadowtower_register_override(NULL, 0x80001000, resident, 1, add));
    T(!shadowtower_register_override("a", 0, resident, 1, add));
    T(!shadowtower_register_override("a", 0x80001000, resident, 0, add));
    T(!shadowtower_register_override("a", 0x80001000, resident, 1, NULL));
    T(shadowtower_register_override("other-overlay", 0x80001000, other, 1, wrong));
    T(shadowtower_register_override("add", 0x80001000, resident, 1, add));
    T(!shadowtower_register_override("add", 0x80002000, resident, 1, add));
    T(!hook(&empty, 0x80003000));
    T(check_enabled == checking);

    /* The resident fingerprint picks the overlay's override; others fall through. */
    CPUState cpu = {0};
    int handled;
    T(call(&cpu, 0x80003000, &handled) == 0 && !handled);
    T(call(&cpu, 0x80001000, &handled) == 5 && handled && cpu.pc == 0x80010040);
    T(cpu.gpr[8] == (checking ? 0xDEAD : 0)); /* Checked calls keep the generated state. */
    uint32_t stored;
    memcpy(&stored, ram + 0x100, 4);
    T(stored == 5);
    memcpy(ram + 0x1000, &(uint32_t){0}, 4);
    T(call(&cpu, 0x80001000, &handled) == 0 && !handled);
    memcpy(ram + 0x1000, &code, 4);
    if (!checking) {
        /* KUSEG and KSEG1 aliases reach the same override. */
        cpu.pc = 0;
        T(hook(&cpu, 0xA0001000) && cpu.gpr[2] == 5 && cpu.pc == 0x80010040);
        T(hook(&cpu, 0x00001000) && cpu.pc == 0x80010040);
        T(guest_call_tests(checking) == 0);
        return generated_calls == 0 ? 0 : 1;
    }

    /* The check keeps the generated result and ignores dead stack and temporaries. */
    T(generated_calls == 1 && nested_result == 0);
    T(overrides[1].matched == 1 && overrides[1].mismatched == 0);
    T(check_phase == CHECK_IDLE);

    T(shadowtower_register_override("wrong", 0x80004000, resident, 1, wrong));
    T(call(&cpu, 0x80004000, &handled) == 5 && handled);
    T(overrides[2].mismatched == 1 && overrides[2].matched == 0);

    /* Interrupts or non-local exits inside the generated call make the result incomparable. */
    raise_irq = 1;
    call(&cpu, 0x80004000, &handled);
    T(handled && overrides[2].skipped == 1 && cpu.pc == 0x80010040);
    raise_irq = 0;
    bail = 1;
    call(&cpu, 0x80004000, &handled);
    T(handled && overrides[2].skipped == 2 && cpu.pc == 0x80001234);
    bail = g_psx_call_bail = 0;

    /* A guard left behind by an exception unwind clears once its frame is gone. */
    check_phase = CHECK_GENERATED;
    check_depth = 0;
    T(call(&cpu, 0x80001000, &handled) == 5 && handled && check_phase == CHECK_IDLE);

    /* An override inside a checked generated run stays generated and starts no check. */
    inner_address = 0x80001000;
    const uint64_t add_matched = overrides[1].matched;
    call(&cpu, 0x80004000, &handled);
    T(handled && inner_result == 0 && overrides[1].matched == add_matched);
    T(overrides[2].mismatched == 2);
    inner_address = 0;

    /* GTE control state is compared, and a stack at the top of RAM keeps its spills ignored. */
    T(shadowtower_register_override("gte", 0x80005000, resident, 1, gte));
    call(&cpu, 0x80005000, &handled);
    T(overrides[3].mismatched == 1);
    cpu.gpr[4] = 2; cpu.gpr[5] = 3; cpu.gpr[29] = 0x80200000; cpu.gpr[31] = 0x80010040;
    T(hook(&cpu, 0x80001000) && overrides[1].mismatched == 0);
    return guest_call_tests(checking);
}
