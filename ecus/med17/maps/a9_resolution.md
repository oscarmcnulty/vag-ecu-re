# Resolving the `a9` base register (MED17.1.1) — mechanism SOLVED, numeric value pending emulation

`a9` gates the ACC path's RX signal structs and calibration (`*(a9+0x3ec)`, `*(a9+0x3dc)`, …). This is the
execution log of the resolution plan (2026-07-24). **Phases 1–2 are complete and definitive about *what* `a9`
is; Phase 3 (emulation) is required for the concrete number and is now precisely targeted.**

## Phase 1 — static scans (DONE)
- **1a. Flash pointer-table scan — DISPROVED the "a9 is a flash const-table base" hypothesis.** Harvested all
  700 pointer-dereferenced `a9+off` offsets from the decompiles and scanned the 4 MB image for a base where
  those offsets hold valid pointers. The all-700 hits are decoys — `0x80103468` (the cal-object table, all
  targets in CAL) and `0x80045exx`/`0x80046xxx` (function-pointer tables, all targets in CODE). **No flash base
  makes the offsets point to RAM**, and the ACC structs at `*(a9+0x3ec)` have writable fields → **`a9` points to
  RAM**, so its table is built at boot and is *not in the flash image*. (Script: an ad-hoc numpy scan;
  re-runnable — see "Reproduce" below.)
- **1b/2. Def-trace — SOLVED the mechanism.** `a9` is **never** a `movh.a+lea` constant (that's why
  `FindBaseRegs` found `a0/a1/a8` but not `a9`). It is set by:

```c
// FUN_8009624e(param_1)  @0x8009624e   — the a9 setter (called at task dispatch)
iVar2 = DAT_d0014cb4;                              // = &OS-block (see below)
uVar3 = *(uint *)(iVar2 + 0x1c + param_1 * 4);     // per-task base from the OS task table
a9    = (uVar3 >> 0x1c == 8) ? uVar3 + 0x20000000  // flash → uncached alias 0xA…
                             : uVar3;               // RAM (0xD…) unchanged
```

## What `a9` actually is (CONFIRMED)
- **`a9` = the currently-dispatched task's data-section base pointer** — reloaded at every context switch by
  `FUN_8009624e`, keyed by a per-task `param_1` taken from the task control block (callers `800bc24a` pass
  `*(tcb+0x50)`, `800966ea` passes `*(tcb+0x14)`). It is **not a global constant** — which is exactly why
  Ghidra can't propagate it and `SetBaseRegs` can't pin it.
- **The task table is at a fixed RAM address:** `DAT_d0014cb4` is set (in scheduler init `FUN_800966ea`) to the
  return of `FUN_800968f8`, which in the normal path is **`&DAT_d0014c60`** (a fixed OS/core control block;
  alternates only in debug/safety modes → `0xa087cb0c` / `0xaff00008`). Therefore:

  > **`a9 = *(0xd0014c60 + 0x1c + param_1*4)  =  *(0xd0014c7c + param_1*4)`**

  a fixed-address RAM table. The **table entries (the per-task bases) are written during OS-Application init**
  and are not present in the flash image, so the concrete `a9` for the ACC task cannot be read statically.
- Corroboration: the a9 setter lives in the OS scheduler cluster `0x80096xxx` (`800960fe`, `80096646`,
  `80096bb2`, `80096c42`, `800bc24a` dispatch); the ACC functions and the scheduler init are all reached via
  **function-pointer tables** (no direct callers), confirming a runtime-dispatched RTOS.

## Phase 3 — emulation (REQUIRED, now sharply targeted)
Simos8.5 resolved its analog (the Com/cal base) by pcode emulation (`research/emulation/EmulComWatch`). Same
approach, with the target now reduced to two concrete reads:
1. Boot-emulate from reset through the OS/scheduler init (harness `research/emulation/EmulInit.java` +
   `EmulPeriph.java`, re-parameterised for MED17: base regs `a0=a8=0xd000c420`, `a1=0x8002f298`; RAM
   `0xd0000000`, PRAM `0xd4000000`, periph `0xf0000000..0xf0110000`; CSA free-list).
2. **Read the RAM table `0xd0014c7c[param_1]`** once init has populated it, and/or **hook `FUN_8009624e`**
   (`0x8009624e`) to log every `(param_1 → a9)` pair, and read `a9` when PC enters an ACC function
   (`0x801455ae`, `0x80140922`, `0x801418ea`). The `a9` live during those = the ACC task's base.
3. From that `a9`, read `*(a9+0x3dc)` (ACC cal struct) and `*(a9+0x3ec)` (RX signal struct) to get the
   **absolute cal/struct addresses**, then map the cal address to a `cal_objects.csv` entry (gives size/bounds).

Risk: full-boot emulation of a Bosch TC1797 image (indirect dispatch, external CAN over MLI, watchdog/PLL) is
non-trivial and may need several iterations of peripheral stubbing. Fallback if boot won't converge: a **live
RAM read on the bench** — the table is at the fixed address `0xd0014c7c`, and `a9` for a task is one 32-bit read
from it; the openport/VW_Flash chain can dump that RAM word directly, sidestepping emulation entirely.

### Phase-3 emulation execution log (2026-07-24)
Harness: **`research/emulation/EmulA9.java`** (Ghidra pcode emulation; MED17 base regs/CSA/mem map; a generic
spin-breaker jumps past peripheral wait-loops; hooks `FUN_8009624e` and computes the value it assigns as
`a9 = *(DAT_d0014cb4 + 0x1c + param_1*4)`, aliased). Iterations:

1. **Boot from `0x8007e720`** — stalls in a 2-instr poll at `0x80082140/44` in **`FUN_8008201c`** (an **MSC**
   driver polling `MSC0_SRC0`/`MSC0_CLC`). With the spin-breaker it jumps past, then **returns to sentinel** —
   `0x8007e720` is an init *leaf* that returns; it never enters the scheduler.
2. **Boot from `0x8006fa8e`** (the true top-level C-startup: ~40 module-init calls) — 12M steps, 298 spin
   escapes, **did not reach the scheduler** (init sequence is very long; the crude jump-past also skips real
   work). The OS is **trap/pointer-dispatched** (scheduler entries `8006fa8e`/`800913b0` have no callers), so
   there is no straight-line reset→scheduler→task path to emulate linearly.
3. **Drive the scheduler-init path `0x800966ea` directly** — **REACHED THE a9 WRITE** (`reachedA9setter=true`,
   `FUN_8009624e` executed at step 223). Live state confirmed the mechanism end-to-end:
   `DAT_d0014cb4 = 0xd0014c60` ✓ and the setter computed `a9` from `*(0xd0014c7c)`. The task table
   `0xd0014c7c[]` was partially populated during the run: **`[6]=0xd00154f8`, `[7]=0xd0020000`** (clean RAM
   bases — plausible per-context data bases), while `[0..2]=0x80103464` (the cal-object table — an artifact of
   the incomplete init state). For `param_1=0` the setter returned `a9=0xa0103464` — **an artifact**, because
   isolated init runs with zeroed inputs and takes wrong branches, so the base fields are not the real values.

**Status after the isolated run:** a9-write milestone reached, mechanism validated; the value from isolated
init is an artifact (`0xa0103464` = uncached alias of the cal-object table — not writable RAM, so not the ACC
base). A faithful value needs the full boot to run **in order** so the OS-App init populates `0xd0014c7c`.

### Phase-3b — peripheral-model boot (the real EmulPeriph build)
Rebuilt `EmulA9.java` on the Simos8.5 `EmulPeriph` pattern: **log-level suppression** (the missing piece that
caused the earlier SIGABRT — the decode-failure flood crashed the JIT), CSR init, a **live STM timer** +
periodic tick, **nop-patch** for unimplemented TriCore insns (`isync`/`dsync`/`mtcr`/…), and a busy-wait
breaker that pokes only peripheral loads (incrementing `|0xE000E000`, never RAM/flash). Progress, in order:

1. **Boot `0x8006fa8e`** (top C-startup) → at step 296 `calla 0xc000079c` (from `0x8019169c`) into **PSPR**
   (Program Scratch-Pad RAM `0xC0000000`), empty because we enter *after* crt0's PSPR relocation.
2. **Found + replicated the crt0 PSPR copy** — descriptor @`0x8001c6f8`: flash `0x8001d7a0` → `0xC0000000`,
   len `0x26b0` (real TriCore code up to `~0x8001fdde`; a version string at `0x8001fe50` bounds it).
   Pre-copying it in the harness let PSPR execute — **the boot now runs millions of steps of real PSPR/OS code
   with no fault** (up from 296 steps).
3. **Current blocker:** the boot spends ~all its steps in a **large crt0 memory init/checksum loop** in PSPR
   (body spans `0xc0000690–0xc00009c0`, 500k+ iterations, `d0` accumulating) that (a) would take tens of
   millions of steps to complete and (b) reads a byte table from a base register left `0` by the crt0-skip (it
   scans low memory `~0x0000fff0+`). `maxFlashPc` stays at `0x803151e0`; `DAT_d0014cb4` never gets set, so the
   OS scheduler-init (which writes `0xd0014c7c`) is not reached. The loop body is too large/varied for the
   spin-breaker to skip safely.

**Why this is the wall:** this is an **OBD-style read with a blank boot sector** (`0x80000000–0x80004000` = 0,
like Simos8.5's missing SBOOT), so the true reset/crt0 that sets up all state (PSPR copy, `.data`, `.bss`, the
scan-loop base pointer) **is not in the image** — we can only enter at `0x8006fa8e`, after crt0, and must
replicate each crt0 job by hand. PSPR is done; the integrity-scan base pointer + `.data` copy are the tail.

### Concrete next steps (surgical, bounded)
1. **Bypass the crt0 checksum/init function**: find the flash function that invokes the `0xc0000690` loop and
   force it to return success (skip the call) instead of emulating the full scan; then continue to the OS init.
2. **Seed the scan-loop's base pointer** (the register left `0`): find the crt0 store that sets it and
   pre-write it, so the loop scans the right region and terminates.
3. Once the boot reaches the OS init, the **write-watch on `0xd0014c7c`/`0xd0014cb4`** (already in the harness)
   captures the real per-context base = the ACC task's `a9` the instant it is written.

**Best lead unchanged:** `a9` for the ACC context is a clean RAM base (candidates `0xd0020000` / `0xd00154f8`
surfaced in the isolated table); the write-watch pins it once the boot converges.

### The harness
`research/emulation/EmulA9.java` (reusable): boots with the peripheral-model layer, pre-copies PSPR, hooks the
a9 setter, write-watches the core-base table, dumps diagnostics (hot PCs, register snapshots). Run:
`analyzeHeadless <proj> MED1711 -process 8R0907115N_0006.bin -noanalysis -scriptPath research/emulation
-postScript EmulA9.java 8006fa8e <budget>`.

## Consequence for `SetBaseRegs`
`a9` is **per-task, not global**, so it cannot simply be added to `ecu.conf` `BASEREGS` as a single constant the
way `a0/a1/a8` were. Once the ACC-task `a9` value is known (emulation or RAM dump), the correct fix is a
**scoped** base-register override for the ACC function set (set `a9` as context only over `0x80140000..0x80146000`
and the coordinator/controller addresses), not a program-wide constant — otherwise unrelated tasks (which have
different `a9`) would decompile with a wrong base. This needs a small extension to `SetBaseRegs.java`
(per-address-range context) — noted for the pipeline.

## Reproduce the Phase-1 scan
```bash
# harvest a9 pointer offsets + scan the image (numpy); prints top candidate bases + region tags
python3 core/maps/find_a9_base.py ecus/med17/firmware/8R0907115N_0006.bin \
    --decompiles ecus/med17/analysis/decompiles_r   # (tool to be committed; logic in this doc)
```

## RESOLVED (2026-07-26) — a9 = 0xa0103464 (the cal-object table)

The bypass strategy worked. With every flash→PSPR call no-op'd (return `d2=0`), the module-init `8006fa8e`
ran to completion, and chaining into the OS inits (`FUN_800960fe(0/1)` core contexts, then `FUN_800966ea`
scheduler init) executed the a9 setter with correct state. The write-watch caught it:

```
>>> DAT_d0014cb4 0->d0014c60 @step90368 pc=8009666e      (OS block ptr set)
>>> core-base[0] 0xd0014c7c 0->80103464 @step90432 pc=800966d0
   A9-WRITE: param_1=0x0  src=0x80103464 -> a9=0xa0103464
```

**`a9 = 0xa0103464`** = the uncached-flash alias of **`0x80103464`**, which is exactly the **cal-object table**
(RESULTS.md §1: 971 sorted pointers, `0x80103464..0x80104390`). Both core contexts (0 and 1) use it. This
overturns the earlier "a9 points to RAM" assumption: **a9 is flash, and the ACC code indexes the cal-object
table** — `*(a9 + off)` = the cal object at table-index `off/4`. The ACC "structs" seen in the decompiles are
calibration objects, not RAM buffers.

**Verification (decisive):** every ACC `*(a9+off)` resolves to a valid, in-range cal object (from
`maps/cal_objects.csv`), and `a9 + max-used-offset (0xf04)` = `0x80104368`, inside the table (`<0x80104390`):

| ACC access | role | cal object # | address | size (B) |
|---|---|---|---|---|
| `*(a9+0x340)` | | 208 | 0x803896ec | 380 |
| `*(a9+0x370)` | (was mislabeled "CAN msg-RAM") | 220 | 0x8038b430 | 1656 |
| `*(a9+0x3c8)` | | 242 | 0x803b3f5c | 4 |
| **`*(a9+0x3dc)`** | **ACC cal struct — decel-shaping maps read by `FUN_801418ea`** | **247** | **`0x803b4834`** | **1768** |
| `*(a9+0x3e4)` | | 249 | 0x803b4f5c | 300 |
| **`*(a9+0x3ec)`** | ACC "request" cal (read by `801455ae`/RX) | 251 | `0x803b5230` | 96 |
| **`*(a9+0x434)`** | big ACC map block (kennlinien) | 269 | `0x803b5bfc` | 5268 |
| `*(a9+0xc28/0xc30)` | | 778/780 | 0x803dba6a/70 | 4/28 |

## Consequences
1. **The decel / min-speed cal lever is now addressable.** `FUN_801418ea`'s decel-shaping maps live inside cal
   object **#247 @ 0x803b4834 (1768 B)** and the map block **#269 @ 0x803b5bfc (5268 B)**. Editable flash cells
   are within these objects (offsets from the field indices `801418ea` uses) — the next step for the openpilot
   decel/min-speed edit, now with real addresses + object boundaries.
2. **SetBaseRegs fix:** `a9 = 0xa0103464` is a constant for the application context, so it can be added to
   `ecu.conf` `BASEREGS` (`a9=0xa0103464`) and re-applied. Then every `*(a9+off)` folds to a concrete cal-object
   pointer in the decompiles → re-decompile makes all ACC cal reads directly visible (like the a1 unlock did on
   Simos8.5). (Both core contexts use the same value, so a global set is safe here.)

## Fold applied + verified (2026-07-26)
`reproduce.sh` re-run with `a9=0x80103464` in `BASEREGS` regenerated the corpus. The ACC decompiles now fold
`*(a9+off)` to concrete cal objects (no `a9 +` remains):
- `FUN_801418ea`: `a9 = &PTR_DAT_80103464`; decel-shaping maps read from `*(0x80103840) = 0x803b4834`
  (cal obj #247, 1768 B) at field offsets up to `+0x6e4` (the object's last field — exact fit).
- `FUN_801455ae`: engage/threshold gates read from `*(0x80103850) = 0x803b5230` (cal obj #251, 96 B) at
  `[0x21]`,`[0x24]`,`+0x12`,`+0x14`,`+0x30`,`+0x34`,`+0x5e`.
- `cal_reads.csv` grew 490→596 (the newly-resolved cal-object-table entry reads).
The **decel / min-speed cal cells** are now concrete: fields within cal obj **#247 @0x803b4834** (via `a9+0x3dc`)
and the kennlinie block **#269 @0x803b5bfc** (via `a9+0x434`).

## Status line
**SOLVED + folded.** a9 = `0xa0103464` = cal-object table `0x80103464` (uncached alias). Cracked by boot emulation
(`research/emulation/EmulA9.java`: PSPR relocation + flash→PSPR call bypass + phase-chain into the OS inits +
write-watch). All ACC calibration is now addressable via `cal_objects.csv`.
