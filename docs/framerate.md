# Shadow Tower USA frame-rate investigation

## Status

**No frame-rate unlock is enabled.** The first limiter experiment increased
update frequency but also increased game speed. Frame blending and whole-machine
VBlank-rate changes are not substitutes for a speed-correct unlock.

Evidence comes from `SLUS-00863` gameplay RAM and a short isolated headless run.
Scratch data and the diagnostic script are under ignored `analysis/`; no disc
files or normal saves were modified.

## Confirmed loop and wait

- `0x80014A30`: initialization followed by the main gameplay loop.
- `0x80014BD4`: loop head.
- `0x80014BE4`: call to player update at `0x80042D74`.
- `0x80014BEC..0x80014C40`: additional game-state/animation/streaming calls.
- `0x80014C20`: camera/output data written into stack buffers.
- `0x80014C48`: call to the rendering path at `0x80026AFC`.
- `0x80014C58`: loop back to `0x80014BD4` while the exit flag is clear.
- `0x80026D90`: render path calls `0x80017680`.
- `0x80017688`: calls buffer synchronization at `0x800175A4`.
- `0x800175BC`: calls the SDK VSync routine at `0x80077104`.
- `0x800175C0`: delay-slot instruction `0x24040003`, loading argument **3**.
- `0x80026D98`: an additional synchronization call at `0x8001535C` checks a
  counter maintained by callback `0x800153B4`.

The player look routine is `0x80041D4C`, writing persistent yaw at `0x801991A2`.
The displayed camera angles at player offsets `0x268/0x26A` are **not timing
variables**. Camera math must not be mistaken for a limiter.

## Isolated comparison

The experiment changed only the low byte of `0x800175C0` from 3 to 0 in the test
process, changing `VSync(3)` to `VSync(0)`. It was restored afterward and the
process stopped. No permanent patch or generated-code change was installed.

Holding the original digital turn-right input and tracing yaw writes yielded:

| Mode | Observed VBlanks | Yaw updates | Update spacing | Yaw units / VBlank |
| --- | ---: | ---: | --- | ---: |
| Original VSync(3) | 81 | 27 | 3 VBlanks | 12.10 |
| Experimental VSync(0) | 60 | 32 | 1–2 VBlanks | 19.67 |

These are **guest-cadence measurements**, not host-present FPS. The headless
runtime can execute faster than wall clock. Normalized to roughly 60 guest
VBlanks/second, these samples correspond to about 20 versus 32 player updates
per second. The changed turn rate is about 63% higher. Acceleration transients
and short sample duration mean this is not a precise steady-state benchmark;
it is sufficient to reject the uncorrected limiter patch as speed-neutral.

The limiter is not the only constraint: removing its three-VBlank target still
produced some two-VBlank update gaps. Guest rendering cost or another wait needs
measurement before promising 60 actual scene updates per second.

## Required next step for a real unlock

Separate the original approximately 20 Hz simulation from additional render
opportunities, rather than running the entire loop more often:

1. Classify all calls in `0x80014BD4..0x80014C58` as simulation, presentation, or
   mixed. Keep combat, enemy AI, movement, animation, and timers on their original
   cadence.
2. Audit `0x80026AFC` before treating it as render-only. For example, its call to
   `0x80016A14` advances counters, so blindly repeating it also changes behavior.
3. Decouple camera sampling and transform construction from simulation while
   retaining the existing mouse hook's menu/focus protections.
4. Only then alter the render wait and compare movement distance, weapon-cycle
   duration, and scene update cadence over the same number of guest VBlanks.

Do not ship the one-byte limiter experiment as a 30/60 FPS mod. Reducing the GPU
resolution or reporting the runtime's 60 Hz VBlank count does not remove this
20 Hz game-loop limit.
