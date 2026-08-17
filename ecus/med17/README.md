# MED17 — Bosch MED17.1.1, Audi Q5 2.0 TFSI (8R0907115N)

Second ECU pack. Where `simos85/` is Continental, this is the **Bosch** side of the
`core/` tooling — and the first real test that the pipeline generalises beyond the
ECU it was built against.

- **Vehicle:** 2013 Audi Q5 2.0 TFSI (B8/8R, MLB), engine code `CHJA`
- **ECU:** Bosch MED17.1.1, part `8R0907115N` rev `0006` (supersedes `8R0907115G`)
- **Bosch SW numbers:** `1037520874` (program), `1037550165` (data/cal blocks)
- **MCU:** Infineon **TC1797** (TriCore 1.3.1), little-endian, 4 MB PFLASH
- **Load base:** `0x80000000` (flat 4 MB image)
- **Ghidra language:** `tricore:LE:32:tc176x`
- **Internal ID strings:** `MED17 CB.06.01.04 C40.00`, `zEGMED17.1 CTPROT_V02.05.0105 TC1797`,
  `52/1/MED17/5/MED17.1.1//D1711A08C000_NY12K50/Dst00//`

> ⚠️ **This image is not a virgin OEM read.** The source filename is
> `WinOLS5 (Vw (ACC_ENABLE) Bosch MED17.1.1 8R0907115N_0006 550165 - csnone).bin`:
> a WinOLS export tagged **ACC_ENABLE** with **checksum correction off** (`csnone`).
> Treat the calibration area as *possibly already modified* — in particular any
> ACC/cruise-related bytes, which is exactly what we are hunting. Getting a stock
> `8R0907115N_0006` read to diff against would immediately show what ACC_ENABLE
> touches, and that diff is arguably the single highest-value next input.

## Memory map (4 MB image)

Erased Infineon TriCore flash reads **`0x00`**, not `0xFF` — that is why the unused
sectors below are zero-filled. Verified by pointer-target clustering: 32-bit words
pointing into `0x80000000..0x803FFFFF` land in the populated sectors at ~10× the
rate they land in the erased ones, and RAM pointers cluster at `0xD0000000`.

| Vaddr | Content |
|---|---|
| `0x80000000–0x800FFFFF` | Program code (+ vector/init tables around `0x80020000`) |
| `0x80100000–0x8013FFFF` | Sparse / mostly erased |
| `0x80140000–0x8019FFFF` | Program code |
| `0x80200000–0x8021FFFF` | Program code |
| `0x802C0000–0x8031FFFF` | Program code |
| `0x80380000–0x803DFFFF` | **Calibration / maps** |
| `0x803E0000–0x803FFFFF` | Software-ID + config block (part-number strings @`0x803DEFA0`) |

Sectors carry a Bosch header at their start (the SW number at `+0x1A`), e.g. at
`0x4000`, `0x10000`, `0x14000`, `0x18000`, `0x20000`, then `0x140000`, `0x200000`,
`0x2C0000`, `0x380000`.

The calibration span was located mechanically, not guessed —
`core/maps/find_cal_region.py` scores each 64 KB block by **axis-array density**
(strictly monotonic u8/u16 runs, the fingerprint of map breakpoint axes). The cal
blocks score 735–2282 against a median of 115 for code, a 6–20× separation:

```
0x80380000  735 CAL      0x803b0000 1055 CAL
0x80390000  368 CAL      0x803c0000 1792 CAL
                         0x803d0000 2282 CAL
```

Corroborated independently: the `8R0907115N … CHJA` software-ID strings sit at
`0x803DEFA0`, inside that span.

## How this differs from Simos 8.5 (the load-bearing finding)

**MED17 does not use a calibration base register.** On Simos 8.5, `a1 = 0x80048000`
*is* the cal base, and unlocking it took resolved cal references from 23 → 840.
Here `FindBaseRegs.java` recovers, from the startup init at `0x800829D2`:

| Reg | Value | What it actually points at |
|---|---|---|
| `a0` | `0xD000C420` | RAM small-data |
| `a1` | `0x8002F298` | **ROM constant pool, inside the code region — *not* the cal area** |
| `a8` | `0xD000C420` | same as `a0` |

Each occurs exactly **twice** in the whole image (the two copies of the init
routine) and is never reloaded — which is precisely what makes them base registers.
Bosch addresses calibration **absolutely** (`movh.a` + `lea`) instead, so cal reads
resolve without any base-register unlock. Consequence: the simos85 playbook step
"unlock a1 to see the maps" does not transfer, and `ResolveCalReads.java` must be
pointed at the cal window explicitly (`--cal=0x80380000:0x80400000`).

## The non-cached alias, and why functions get canonicalized

TriCore maps the same physical flash twice: cached at `0x80000000`, non-cached at
`0xA0000000`. This firmware genuinely dispatches through alias pointers, and with
only the cached block loaded those flows died as *"Could not follow disassembly flow
into non-existing memory at a00602d8"*, truncating the decompiled bodies.
`MapMemory.java` therefore byte-maps the alias (a view, not a copy).

That fixes the flow but makes auto-analysis create **twin functions** at `0xA0…`.
`CanonicalizeAlias.java` collapses them back, distinguishing two cases that must not
be conflated: 1234 were pure duplicates of an existing cached function (delete), and
**126 were orphans** — code reachable *only* through an alias pointer, which a blind
delete would have silently lost, so the cached twin is created first.

## Coverage (what fraction of the bin is actually recovered)

Measured by `core/ghidra/CoverageStat.java` (pipeline step 10, written to
`analysis/coverage.log`). Per-function "% decompiled cleanly" is **not** the metric
that matters — it only counts functions Ghidra already found, so bytes that never
became a function are invisible to it. This measures bytes.

Of the whole 4 MB image:

| Class | Bytes | % of image |
|---|---:|---:|
| Erased (`0x00` fill — no content) | 1,850,489 | 44.1% |
| **Decompiled code** (in a function) | 1,419,416 | 33.8% |
| **Calibration / maps** (typed data) | 523,941 | 12.5% |
| Unaccounted (undefined, non-zero) | 361,764 | 8.6% |
| Other defined data | 37,112 | 0.9% |
| Disassembled but in no function | 1,434 | 0.03% |

Excluding erased flash, the image is 2,343,815 bytes of live content: **60.6%
decompiled code, 22.4% calibration, 15.4% unaccounted, 1.6% other data.**

Within the executable-code region (live, non-cal — 1,819,578 bytes):
**78.0% is in a decompiled function, 0.1% is orphan disassembly, 19.9% is
unaccounted.**

### Is the 19.9% missing code?

No — the evidence says it is data:

1. **Nothing references it.** `RecoverReferencedCode.java` searched the entire code
   region for undefined bytes that are the target of a call or jump: **zero**. Every
   reachable code target is already inside a function.
2. **It is shaped like padding, not code.** 361,764 bytes spread over **37,411
   separate runs** — a mean of 9.7 bytes. Functions do not come in 10-byte fragments
   interleaved 37,000 times; inter-function padding, literal pools and jump tables do.
3. **Sampling confirms it**: `0x80017470` is `c3c3c3c3…` fill; `0x800427b9` is a
   repeating 2-byte table; `0x80043046` is a monotonic u16 axis array. 36% of it sits
   in `0x80000000–0x8003FFFF`, the boot/vector/init table area.

So the code side is effectively complete; what remains is **untyped data**, and
typing it is a labelling job, not a decompilation one.

### What it took to get there

The first pass looked fine by the per-function metric (99.9% clean) while **621 KB —
more than half of all disassembled bytes** in the `0x80140000–0x80310000` program
blocks — sat in no function at all, producing no C and appearing in no manifest.
`ClaimOrphanCode.java` claims that code; it runs to a fixpoint because each created
function exposes more orphan code in the holes of its non-contiguous body.

> **Do not use `RecoverGapWalk.java` on this image** (it now lives in `research/discovery/`
> as a cautionary exhibit, not in `core/`). It disassembles *undefined* bytes blind, and
> since erased TriCore flash reads `0x00` (which decodes to valid-looking instructions), it
> converted **1.1 MB of erased fill into ~33k junk functions**. Measured, then reverted.
> `core/ghidra/RecoverReferencedCode.java` is the safe counterpart: it only seeds where a
> call/jump reference already proves code exists, refuses all-zero targets, and rolls back
> implausibly small bodies.

## Pipeline

```bash
./ecus/med17/reproduce.sh          # cold-start capable; see analysis/_logs/
```

It is **cold-start capable**, unlike `simos85/reproduce.sh`: with no
`function_entries.txt` / `symbols_merged.csv` yet, it *seeds* them from
auto-analysis instead of failing, and skips (loudly, never silently faking) the
steps whose inputs are not yet pinned. Steps: import + `MapMemory` → `FindBaseRegs`
→ `SetBaseRegs` → `CanonicalizeAlias` → function set → symbols → `MarkCalData` →
`DecompileAll` (+ manifest) → disasm fallback for anything without usable C →
`ResolveCalReads`.

## Goal: ACC longitudinal control below the factory floor

Same target as simos85: let openpilot hold longitudinal control below the speed at
which the car withdraws ACC authority. The B8 Q5 shipped a single-radar ACC with a
~30 km/h floor and no stop&go (see the `b8-acc-radar-hardware` note).

### The headline result: the floor is not in this ECU

**The MED17 has no internal 15 km/h ACC threshold.** It relays `ESP_05` (CAN `0x106`)
frame bit 33 `ECD_nicht_verfuegbar` — the ESP/ABS declaring that externally-commanded
deceleration is unavailable — and withdraws ACC authority in response. The full
propagation chain is proved at instruction level and confirmed on-car across 8.11 h and
1.46 M frames on two Q5s. **No MED17 calibration edit lifts the floor by itself.**

Read **`maps/ecd_relay.md`** first — it is the authoritative account, including what
was ruled out and where the lever actually is.

Two ECU-side items remain real and must not be confused with it:

- **EGAS-L2 cal #208** (`0x80389809` = 15, `0x8038980e` = 7) is a *separate* Level-2
  monitor gate running on the independent monitor speed. It is a fault contributor, not
  the ACC permit, but it can impose its own 15/7 boundary regardless of the ESP — so
  sub-15 operation likely needs it edited *as well*. See `maps/l2_monitors.md` and the
  ready-to-flash cal set `maps/med17_openpilot_lowspeed.a2l`.
- **A real but inert low-speed engage lock** hangs off `ESP_05` bit 36
  (`ESP_HDC_Standby`), constant 0 on these cars. See `maps/ecd_relay.md` and
  `maps/engage_state.md`.

### What is mapped

| area | file |
|---|---|
| The ACC floor: what it is, where it comes from, what was ruled out | **`maps/ecd_relay.md`** |
| ACC_01 → TSK_01/02/04 longitudinal path, decel authority, hold relay | `maps/acc_flow.md` |
| CAN layer: MultiCAN controller, message table, descriptors, E2E | `maps/can_signal_map.md` |
| Per-message directory: id → direction → descriptors | `maps/com_group_direction.md` |
| EGAS Level-2 monitors, cal #208 | `maps/l2_monitors.md` |
| Vehicle-speed variables + functional low-speed cal cells | `maps/min_speed_l2.md` |
| Mode arbitration + engage state machine | `maps/engage_state.md` |
| `a9` = the cal-object table | `maps/a9_resolution.md` |
| Kennlinie/Kennfeld interpolators and how to sweep them | `maps/kennlinie_interpolators.md` |
| Simos 8.5 vs MED17 hold-bit comparison | `maps/anhalten_compare.md` |
| Cal findings and pack status | `maps/RESULTS.md` |

The base register **`a9`** — which the ACC path and the L2 monitors use to reach their
calibration — is `0xa0103464`, the uncached alias of the **cal-object table
`0x80103464`**, so `*(a9+off)` is cal object `off/4`. It is in `ecu.conf` `BASEREGS`, so
`reproduce.sh` folds every ACC cal read to a concrete address; the decel-shaping maps are
cal object #247 `@0x803b4834` and #269 `@0x803b5bfc`.

Still worth having: a **stock `8R0907115N_0006` read to diff against.** This image is a
WinOLS export tagged `ACC_ENABLE` with checksums off, so someone already modified its
ACC calibration — the diff would show exactly what. That is an input problem, not an RE
problem, and it is the highest-value remaining input.
