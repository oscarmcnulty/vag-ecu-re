# The `a9` base register — `0xa0103464`, the cal-object table

`a9` is the base register the ACC/TSK code and the EGAS-L2 monitors use to reach their calibration.
`FindBaseRegs` recovers `a0`, `a1` and `a8` because those are `movh.a`+`lea` constants; `a9` is not,
so every `*(a9+off)` stayed symbolic until it was resolved by boot emulation.

**Answer: `a9 = 0xa0103464`** — the uncached-flash alias of **`0x80103464`**, which is the
**cal-object table** (971 sorted pointers, `0x80103464..0x80104390`, `RESULTS.md` §1). So
`*(a9 + off)` is **the calibration object at table index `off/4`**. What the decompiles show as ACC
"structs" are calibration objects, not RAM buffers.

It is in `ecu.conf` `BASEREGS` in its cached form (`a9=0x80103464`) so that folded references land
inside the `0x80000000` image, and `reproduce.sh` has already applied it — the corpus contains no
unresolved `a9 +` in the ACC path.

## What `a9` is

`a9` is the **currently-dispatched task's data-section base**, reloaded at every context switch:

```c
// FUN_8009624e(param_1) @0x8009624e — the a9 setter, called at task dispatch
iVar2 = DAT_d0014cb4;                            // = &OS control block
uVar3 = *(uint *)(iVar2 + 0x1c + param_1 * 4);   // per-context base from the OS table
a9    = (uVar3 >> 0x1c == 8) ? uVar3 + 0x20000000   // flash -> uncached alias 0xA…
                             : uVar3;                // RAM (0xD…) unchanged
```

`DAT_d0014cb4` is set in the scheduler init `FUN_800966ea` to `&DAT_d0014c60`, so

> `a9 = *(0xd0014c60 + 0x1c + param_1*4)  =  *(0xd0014c7c + param_1*4)`

a fixed-address RAM table populated during OS-Application init. Both core contexts (0 and 1) get
`0x80103464`, which is why a single global value is safe here even though the mechanism is per-task.

## How it was recovered

`research/emulation/EmulA9.java` — Ghidra pcode emulation with a peripheral model. Four things had to
be right:

1. **Enter after crt0.** This is an OBD-style read with a blank boot sector
   (`0x80000000–0x80004000` = 0), so the real reset vector is not in the image. Boot starts at the
   top-level C startup `0x8006fa8e`.
2. **Replicate crt0's PSPR relocation by hand.** Descriptor `@0x8001c6f8`: flash `0x8001d7a0` →
   `0xC0000000`, length `0x26b0`. Without it, the first `calla 0xc000079c` lands in empty scratchpad.
3. **Bypass the flash→PSPR calls** (return `d2 = 0`) so the module inits run to completion instead of
   spinning in crt0's memory-integrity scan.
4. **Chain into the OS inits** (`FUN_800960fe(0)`, `FUN_800960fe(1)`, then `FUN_800966ea`) and
   write-watch the core-base table.

The watch caught it:

```
>>> DAT_d0014cb4 0->d0014c60 @step90368 pc=8009666e      (OS block pointer set)
>>> core-base[0] 0xd0014c7c 0->80103464 @step90432 pc=800966d0
   A9-WRITE: param_1=0x0  src=0x80103464 -> a9=0xa0103464
```

Run it with:

```bash
analyzeHeadless <proj> MED1711 -process 8R0907115N_0006.bin -noanalysis \
  -scriptPath research/emulation -postScript EmulA9.java 8006fa8e <budget>
```

**Decisive corroboration:** every ACC `*(a9+off)` resolves to a valid, in-range entry of
`maps/cal_objects.csv`, and `a9 + max-used-offset (0xf04)` = `0x80104368`, still inside the table
(`< 0x80104390`). A wrong base would not do that 20 times in a row.

## The resolved accesses

| access | cal object | address | size | role |
|---|---|---|---|---|
| `*(a9+0x250)` / `+0x2b4` / `+0x2cc` / `+0x304` / `+0x33c…+0x35c` | various | `0x80384xxx…0x8038axxx` | | **EGAS-L2 monitor** cal block (`l2_monitors.md`) |
| `*(a9+0x340)` | **#208** | **`0x803896ec`** | 380 | EGAS-L2 cruise/ACC speed monitor — the 15/7 permit pair |
| `*(a9+0x370)` | #220 | `0x8038b430` | 1656 | per-slot parameter block walked by `FUN_80099600` — a **calibration object**, not a hardware pointer |
| `*(a9+0x3c8)` | #242 | `0x803b3f5c` | 4 | |
| **`*(a9+0x3dc)`** | **#247** | **`0x803b4834`** | **1768** | **ACC decel-shaping maps** read by `FUN_801418ea` (fields to `+0x6e4` — an exact fit to the object) |
| `*(a9+0x3d8)` | — | `PTR_DAT_8010383c` | | anfahren / drive-off torque profile |
| `*(a9+0x3e4)` | #249 | `0x803b4f5c` | 300 | decel-path maps in `FUN_801434de` |
| `*(a9+0x3ec)` | #251 | `0x803b5230` | 96 | ACC thresholds read by `FUN_801455ae` (`[0x21]`, `[0x24]`, `+0x12`, `+0x14`, `+0x30`, `+0x34`, `+0x5e`) |
| `*(a9+0x410)` | #260 | `0x803b59a6` | 150 | GRA/cruise/limiter object |
| **`*(a9+0x434)`** | **#269** | **`0x803b5bfc`** | **5268** | big ACC map block (Kennlinien) |
| `*(a9+0xc28)` / `+0xc30` | #778 / #780 | `0x803dba6a` / `0x803dba70` | 4 / 28 | ACC coding constants |

## Consequences

1. **The ACC calibration is addressable.** Decel shaping lives in #247 and #269, with object
   boundaries from `cal_objects.csv`; the EGAS-L2 monitor cells in #208. Read
   `kennlinie_interpolators.md` for how to decode the map layouts before editing fields.
2. **A `*(a9+0x370)` access is a calibration read, not a hardware pointer.** It resolves to cal object
   #220, so `FUN_80099600` — which walks it over 20 slots (`DAT_800296aa` = 0x14) — is not a CAN
   message-RAM loop. The CAN controller is driven from an entirely different place
   (`can_signal_map.md`); what `FUN_80099600` itself supervises is **[G]**, and it has no in-corpus
   callers (function-pointer dispatch).
3. **The mechanism is per-task even though the value is not.** If a future variant gives different
   contexts different bases, `SetBaseRegs` will need a per-address-range override rather than a global
   constant — noted for the pipeline.
