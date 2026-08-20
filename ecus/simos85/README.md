# Simos 8.5 — Audi Q5 3.0 TFSI (8R0907551F)

First and reference ECU pack. The `core/` tooling is built against this target.

- **Vehicle:** Audi Q5 3.0 TFSI (EA837, MLB platform)
- **ECU:** Continental/Siemens SIMOS 8.5, project `S859300C`
- **MCU:** Infineon TC1796 (TriCore 1.3), little-endian
- **Load base:** `0x80000000` · `0xa00xxxxx` = uncached mirror of `0x800xxxxx` · file offset = `addr & 0x1FFFFFFF`
- **Ghidra language:** `tricore:LE:32:tc176x`
- **Software-ID block @ 0x80040000:** `8R0907551F`, `S8500L2000000`, `CTUC`

The driving goal is openpilot longitudinal + standstill on this car (memory
`openpilot-integration-goal`), so the ACC/cruise longitudinal path is the deepest-covered subsystem
here; the performance/tuning calibration is covered second.

## Where things are

### `maps/` — the findings

| file | topic |
|---|---|
| `acc_flow.md` | **the ACC longitudinal path end to end**: CAN ingress → request formation → CRUC state machine (`STATE_CRU_CTL`) → TSK_02/TSK_04 egress, the `TSK_Anhalten` hold relay, and the two stop-and-go architectures |
| `low_speed_floors.md` | **the two independent sub-15 km/h mechanisms** — the internal `C_VS_MIN_CRU_MON` latching L2 monitor and the ESP's external ECD permission — plus the 3 km/h thresholds and the cross-ECU comparison with MED17 |
| `decel_limit_flow.md` | **the −3.0 m/s² decel limit**: functional clamp, L2 plausibility monitor, engine-torque limit, on-car evidence, and how to move it |
| `edit_targets.md` | **every pinned cal address in one table**, with the direction of each edit |
| `can_signal_map.md` | CAN acceptance table, the 13 dedicated handlers, the MLB E2E seed rule, and the AUTOSAR-Com buffer architecture |
| `dispatch_tables.md` | recovered function-pointer dispatch tables (the reason much of the CAN/ACC subsystem is unlinked by static call-graph analysis) |
| `fr_alignment.md` | Funktionsrahmen ↔ binary label alignment |
| `performance_maps.md` | the named + addressed performance/tuning maps |
| `tune_diff_analysis.md` | 3-way Original/Stage1/Stage2 diff: every changed cal block, attributed |
| `simos85.a2l` + `a2l_catalog.csv`, `a2l_symbols.csv` | the canonical calibration store and its generated projections |
| `map_calls.csv`, `cal_xref.csv`, `cal_ghidra_xref.csv`, `map_consumers.csv`, `perf_*.csv`, `diff_block_addrs.txt` | generated data behind the above |
| `coding_cells.csv` + `gen_coding_labels.py` | the 49 long-coding cells (bit layout, factory value, per-cell rule, allowed values, destination flags) and the generator that rebuilds them from the image |

### `labels/` — coding tools

`8R0-907-551.LBL` — a VCDS-style label file for the **10-byte long coding**, generated from the
image by `maps/gen_coding_labels.py`. Layout/rules/allowed values are firmware-derived; the
English names are graded `CONFIRMED` / `PROBABLE` / `UNKNOWN`. See `analysis/coding_storage.md`.

### `analysis/` — method and machine-readable state

`symbols_merged.csv` (function/data names), `function_entries.txt` (every entry vaddr),
`RE_findings_checksum.md` (integrity model), `obd_read_feasibility.md` (why 8.5 is virtual-read only),
`uds_dispatch.md` + `uds_dispatch_recovery.md`, `mode09_calid_cvn.md`,
`CHECKSUM_COUNTER_VALIDATION.md`, `cal_read_method.md`, `symbol_name_audit.md`, `coverage.log`,
`coding_storage.md` (**where the long coding lives and what every coding bit reaches**),
`uds_did_table.csv` (all 766 DID records, corrected layout).
Decompiles (`decompiles_r/` and friends) are **generated, gitignored** — regenerate with `reproduce.sh`.

## Memory map (2 MB OBD image)

| File offset | Vaddr | Content |
|---|---|---|
| 0x00000–0x20000 | 0x80000000 | Bootloader (SBOOT/CBOOT) — **blank in OBD read** |
| 0x20000–0x30000 | 0x80020000 | Init/vector pointers |
| 0x40000–0x80000 | 0x80040000 | **Calibration / maps** (Stage1/2 differ here) — `CAL_LO`/`CAL_HI` in `ecu.conf` |
| 0x90000–0x1F0000 | 0x80090000 | Main ECU-SW code |

## Integrity model (see `analysis/RE_findings_checksum.md`)

- **No static cal checksum in the image.** Integrity is enforced at flash-write time by the resident
  loader (streamed CRC-16, poly 0xA001, init 0xABCD) plus boot RSA-1024 (key ID 0x73). A modified cal
  flashed via the accepted Pcmflash/OBD path is therefore accepted with no in-file checksum word to
  patch — but recompute the cal-block checksum (`core/checksum`) before reflash anyway.
- CRC primitives (re-confirmed by `core/checksum/crc_finder.py`):
  - CRC32 zlib table @ `0x8009083c`, `crc32_reflected 0x801dc544` (runtime integrity, reflected)
  - CRC16/ARC table @ `0x800808ec`, `crc16_table 0x800a59f0` (init 0xABCD; UDS transfer blocks)
  - CRC8/AUTOSAR table @ `0x80080aec`, `checksum8_table 0x800a5a18` (**no callers**)
- Repro-status bits: #15 = cal CRC, #11 = ECU-SW CRC, #31 = all.

## External read paths (bench SBOOT vs OBD) — see `analysis/obd_read_feasibility.md`

Why 8.5 is a *virtual read* over OBD, not a real dump — three doors, all shut over OBD:
**Door 1** the SBOOT boot-password exploit ([fastboatster/Simos8_SBOOT]) is **bench-only** (entry is a
PWM-on-boot-pins timing gate, not a bus message) but is the only route to the boot sector
`0x0–0x20000`; **Door 2** a Simos18-style patch-and-read OBD unlock needs an unsigned-code-write
primitive (RSA-signature bypass), unbroken on the 8.5 loader; **Door 3** a CCP/XCP `UPLOAD` would need a
measurement slave — and a static pass over the reproduced decompiles finds none: no CCP/XCP anywhere,
and the UDS stack has **no `0x23` ReadMemoryByAddress and no `0x35` upload**, only a session+security
gated write/reflash path and fixed-DID `0x22` reads.

[fastboatster/Simos8_SBOOT]: https://github.com/fastboatster/Simos8_SBOOT

## Calibration map engine

- **Base registers** (the unlock that makes cal RE possible at all; recovered by
  `core/ghidra/FindBaseRegs.java`, applied by `SetBaseRegs.java`, init at `0x80030cca`):
  `a0 = 0xd0008000` (RAM small-data base), `a1 = 0xa0048000 → 0x80048000` (**calibration base**),
  `a8 = 0x80088800`. Master pointer/descriptor table @ `0x8008615c` (`a8 - 0x26a8`).
  Cal data is accessed base-register-relative (`[a1+off]`), so before this step Ghidra resolved ~23
  references into the cal region; after it, hundreds.
- **Readers:** 1-D Kennlinie `kl_interp_u16 @0x800a5f40` (+ `lookup_kennlinie_800a2cd0`); 2-D Kennfeld
  `kf_interp_u16 @0x800a5fc0` (bilinear, + `lookup_kennfeld_map_800a2e0c`). Maps are also reached
  through a **descriptor-table framework**: accessor `FUN_800a8ff0` (16-byte descriptors, `id*0x10` →
  data pointer), dispatch `FUN_801d977c`. Dimensions live in the descriptor metadata, not at the data
  pointer.
- The cal region is data-typed by `MarkCalData.java`, so "undefined bytes" in coverage reflect only real
  code.
- **`a0`/`a1`-relative gotcha:** `FindRefsTo`'s absolute reference database misses `a0`-relative RAM
  writes, but the decompiler resolves them (`DAT_d000xxxx`). For `d000xxxx` dataflow use decompile-grep,
  or the SymbolicPropogator `--range` pass in `FindRefsTo`.

## Recovered-knowledge persistence (source of truth)

The **A2L (`maps/simos85.a2l`) is the single committed source of truth** for calibration objects — maps,
curves and cal constants. Document every reverse-engineered object *directly in the A2L*: name it (FR
short-name where known), give it the right address, record layout, axis linkage and `COMPU_METHOD` scale
+ unit, and put provenance in the CHARACTERISTIC description string. Functions are a separate store —
the A2L describes calibration data, not code.

| Store | Role | Holds | Provenance |
|---|---|---|---|
| `maps/simos85.a2l` | **canonical (hand-edited)** | ASAP2 model of every cal object; INCA/CANape/WinOLS-native | each CHARACTERISTIC's description string |
| `analysis/symbols_merged.csv` | **canonical** | **confirmed** function/data names (`addr,name,type,comment,source`) | `source` ∈ {`verified`, `re-trace`, `fr-trace`} |
| `maps/a2l_symbols.csv` | generated | cal labels for Ghidra `ApplySymbols` | from the A2L (`core/maps/a2l_to_symbols.py`) |
| `maps/a2l_catalog.csv` | generated | flat CSV index (name, dims, axes, scaling, unit) | from the A2L (`core/maps/a2l_catalog.py`) |

After editing the A2L, re-derive the projections so nothing drifts:

```bash
python3 core/maps/a2l_to_symbols.py ecus/simos85/maps/simos85.a2l --out ecus/simos85/maps/a2l_symbols.csv
python3 core/maps/a2l_catalog.py    ecus/simos85/maps/simos85.a2l --out ecus/simos85/maps/a2l_catalog.csv \
    [--bin firmware/8R0907551F_Original.bin]   # optional: verify axis breakpoints are monotonic
```

Objects that are not pinned to a flash address (a RAM mirror, or a cal reached only through a runtime
pointer) cannot live in the A2L; they are documented in `maps/edit_targets.md` and the flow docs instead.

## Reproduce the labeled project

**No decompiled C is committed** — it is a derived work of the copyrighted firmware. Everything needed to
regenerate the exact analysis state IS committed (addresses, names, comments, pipeline scripts). One
command rebuilds the project and the decompiles:

```bash
source .env.sh                       # JAVA_HOME, GHIDRA_HOME (Ghidra 12.1.2 / JDK 21)
# supply firmware/8R0907551F_Original.bin locally (gitignored)
ecus/simos85/reproduce.sh
```

`reproduce.sh` is a two-line wrapper: it sources `ecu.conf` (load base, base registers, cal window, code
ranges, A2L, map-trace output) and runs the shared driver `core/pipeline/reproduce.sh`. The pipeline:
import+analyze → **FindBaseRegs/SetBaseRegs** → **CreateFunctions** (recreates every entry point
including the table-dispatched CAN/Com handlers auto-analysis cannot reach) → **ClaimOrphanCode** →
**ApplySymbols** + A2L cal labels → **MarkCalData** → **DecompileAll** (regenerates
`analysis/decompiles_r/`, gitignored) → disasm fallback → **ResolveCalReads** → **TraceMapCalls** →
**CoverageStat** (byte-level coverage → `analysis/coverage.log`). To verify the image first, set
`EXPECT_SHA` in `ecu.conf`.

Code coverage is effectively complete: nothing in the image linear-decodes as function-calling code
outside a defined function, and the residual undefined bytes are genuine cal data plus inter-bank
padding.

Canonical version-controlled inputs (RE metadata, not firmware code):

| file | holds |
|---|---|
| `ecu.conf` | this ECU's pipeline parameters (load base, base regs, cal window, …) |
| `analysis/function_entries.txt` | every function entry vaddr (one hex addr per line) |
| `analysis/symbols_merged.csv` | function/data names + comments (`addr,name,type,comment,source`) |
| `maps/simos85.a2l` | cal maps/curves/constants + provenance (canonical ASAP2) |
| `core/ghidra/*.java`, `core/pipeline/reproduce.sh` | the shared pipeline |
| `maps/edit_targets.md` | findings/addresses not represented as A2L objects |

> **Symbol provenance:** `symbols_merged.csv` contains only names confirmed against the code or the
> Funktionsrahmen (`source` ∈ {`verified`, `re-trace`, `fr-trace`}). Machine-proposed `llm` names were
> audited (20% actively wrong) and removed — see `analysis/symbol_name_audit.md`. Don't reintroduce
> unverified guesses.

## Open items

- Which of the 13 ACC diagnoses latches below 15 km/h, and whether a signal-only escape exists
  (`low_speed_floors.md` §6).
- Naming the relayed CAN diagnosis bits — needs the ACC/brake DBC, external to this image.
- `d0007baa`'s absolute m/s² scale (runtime gain `b0d4`) versus the FR's 0.005.
- Full semantic naming of the `d8ce` engage-inhibit word and the `d890` ACC-state byte.
- Import the remaining map catalog from the WinOLS `.ols` + Funktionsrahmen into the A2L.
- Obtain a bench/boot read to study SBOOT/CBOOT (RSA, flash loader).
- Name the remaining long-coding cells: 33 of the 49 are still `UNKNOWN`, and the cell-3 /
  cell-24 hypotheses are unproven (`analysis/coding_storage.md` §5–6).
- Resolve why the SID row at `0x80085f00` reads as `$22` while `0x801229b4` implements the DID
  *write* semantics (`coding_storage.md` §1b).
- Trace the NV record layer that backs the coding to the DFLASH banks call-by-call
  (`coding_storage.md` §2 marks the DFLASH binding as inference).
