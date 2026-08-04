# Simos 8.5 — Audi Q5 3.0 TFSI (8R0907551F)

First and reference ECU pack. The `core/` tooling is built against this target.

- **Vehicle:** Audi Q5 3.0 TFSI (EA837, MLB platform)
- **ECU:** Continental/Siemens SIMOS 8.5, project `S859300C`
- **MCU:** Infineon TC1796 (TriCore 1.3), little-endian
- **Load base:** `0x80000000`
- **Ghidra language:** `tricore:LE:32:tc176x`
- **Software-ID block @ 0x80040000:** `8R0907551F`, `S8500L2000000`, `CTUC`

## Memory map (2 MB OBD image)

| File offset | Vaddr | Content |
|---|---|---|
| 0x00000–0x20000 | 0x80000000 | Bootloader (SBOOT/CBOOT) — **blank in OBD read** |
| 0x20000–0x30000 | 0x80020000 | Init/vector pointers |
| 0x40000–0x80000 | 0x80040000 | **Calibration / maps** (Stage1/2 differ here) — `CAL_LO`/`CAL_HI` in `ecu.conf` |
| 0x90000–0x1F0000 | 0x80090000 | Main ECU-SW code |

## Integrity model (solved — see analysis/RE_findings_checksum.md)

- **No static cal checksum in the image.** Integrity is enforced at flash-write
  time by the resident loader (streamed CRC-16, poly 0xA001, init 0xABCD) + boot
  RSA-1024 (key 0x73). A modified cal flashed via the accepted Pcmflash/OBD path
  is therefore accepted with no in-file checksum word to patch.
- CRC primitives (re-confirmed by `core/checksum/crc_finder.py`):
  - CRC32 zlib table @ `0x8009083c` (runtime integrity, reflected)
  - CRC16/ARC table @ `0x800808ec` (init 0xABCD; UDS download buffers)
  - CRC8/AUTOSAR table @ `0x80080aec` (no callers)

## External read paths (bench SBOOT vs OBD) — see analysis/obd_read_feasibility.md

Why 8.5 is *virtual read* over OBD, not a real dump — three doors, all shut over OBD:
**Door 1** the SBOOT boot-password exploit ([fastboatster/Simos8_SBOOT]) is **bench-only**
(entry is a PWM-on-boot-pins timing gate, not a bus message) but is the only route to the
boot sector `0x0–0x20000`; **Door 2** a Simos18-style patch-and-read OBD unlock needs an
unsigned-code-write primitive (RSA-signature bypass) unbroken on the 8.5 loader; **Door 3**
a CCP/XCP `UPLOAD` (the AL551 vector) would need a measurement slave — and a **static pass
over the reproduced decompiles finds none**: no CCP/XCP anywhere, and the UDS stack has **no
`0x23` ReadMemoryByAddress and no `0x35` upload** — only a session+security-gated write/
reflash path and fixed-DID `0x22` reads (the identify-for-virtual-read surface). Full
reasoning, the door-by-door analysis, and the per-service evidence table in
`analysis/obd_read_feasibility.md`.

[fastboatster/Simos8_SBOOT]: https://github.com/fastboatster/Simos8_SBOOT

## Calibration map engine

- 1D: `kl_interp_u16` @0x800a5f40 · 2D: `kf_interp_u16` @0x800a5fc0 (bilinear)
- Descriptor-table framework: accessor `FUN_800a8ff0` (16-byte descriptors,
  `id*0x10` → data ptr), dispatch `FUN_801d977c`. Dims live in descriptor metadata.

## Assets in this pack

- `firmware/` — Original / Stage1 / Stage2 bins (user-supplied; gitignored)
- `analysis/RE_findings_checksum.md` — full prior findings (checksum/flash/cal engine)
- `maps/` — map catalog (TODO: import the 26 known + 594 candidate objects)

### Recovered-knowledge persistence (source of truth)

The **A2L (`maps/simos85.a2l`) is the single committed source of truth** for
calibration objects — maps, curves, and cal constants. Document every reverse-
engineered object *directly in the A2L*: name it (FR short-name where known),
give it the right address / record layout / axis linkage / `COMPU_METHOD` scale +
unit, and put provenance in the CHARACTERISTIC description string
(verified/confidence/evidence/FR). Everything else is regenerated from it.
Functions are a separate store — the A2L describes calibration data, not code.

| Store | Role | Holds | Provenance |
|---|---|---|---|
| `maps/simos85.a2l` | **canonical (hand-edited)** | ASAP2 model of every cal object; the INCA/CANape/WinOLS-native source | each CHARACTERISTIC's description string |
| `analysis/symbols_merged.csv` | **canonical** | function names (addr,name,type,comment,**source**) | `source` = `verified` or `llm` |
| `maps/a2l_symbols.csv` | generated | cal labels for Ghidra `ApplySymbols` (address,name,type,comment) | from the A2L (`core/maps/a2l_to_symbols.py`) |
| `maps/a2l_catalog.csv` | generated | flat CSV index (name, dims, axes, scaling, unit; `--bin` monotonic check) | from the A2L (`core/maps/a2l_catalog.py`) |

After editing the A2L, re-derive the symbol + catalog projections so nothing drifts:

```bash
python3 core/maps/a2l_to_symbols.py ecus/simos85/maps/simos85.a2l --out ecus/simos85/maps/a2l_symbols.csv
python3 core/maps/a2l_catalog.py    ecus/simos85/maps/simos85.a2l --out ecus/simos85/maps/a2l_catalog.csv \
    [--bin firmware/8R0907551F_Original.bin]   # optional: verify axis breakpoints are monotonic
```

Object names come from the Funktionsrahmen; addresses were located in
`8R0907551F_Original.bin` and each entry carries its own evidence and confidence in
its `<description>`.

Objects not yet pinned to a flash address (e.g. the RAM-mirror functional
`C_VS_MIN_CRU`) can't live in the A2L; they stay in `maps/RESULTS.md` until located.

## Reproduce the labeled project

**No decompiled C is committed** — it is a derived work of the copyrighted firmware.
Everything needed to regenerate the exact analysis state IS committed (addresses, our
names/comments, and the pipeline scripts). One command rebuilds the project + decompiles:

```bash
source .env.sh                       # JAVA_HOME, GHIDRA_HOME (Ghidra 12.1.2 / JDK 21)
# supply firmware/8R0907551F_Original.bin locally (gitignored)
ecus/simos85/reproduce.sh
```

`reproduce.sh` is a two-line wrapper: it sources `ecu.conf` (this ECU's load base, base
registers, cal window, code ranges, A2L, map-trace output) and runs the shared driver
`core/pipeline/reproduce.sh`. The pipeline: import+analyze → **FindBaseRegs/SetBaseRegs**
(a0/a1/a8 — the base-register unlock that folds cal reads to `DAT_8004xxxx`) →
**CreateFunctions** (recreates every entry point incl. the table-dispatched CAN/Com handlers
auto-analysis can't reach) → **ClaimOrphanCode** (claims disassembled-but-function-less code)
→ **ApplySymbols** + A2L cal labels → **MarkCalData** → **DecompileAll** (regenerates
`analysis/decompiles_r/`, gitignored) → disasm fallback → **ResolveCalReads** →
**TraceMapCalls** → **CoverageStat** (byte-level coverage → `analysis/coverage.log`). All
parameters live in `ecu.conf`; to verify the image first, set `EXPECT_SHA` there.

Canonical version-controlled inputs (RE metadata, not firmware code):

| file | holds |
|---|---|
| `ecu.conf` | this ECU's pipeline parameters (load base, base regs, cal window, …) |
| `analysis/function_entries.txt` | every function entry vaddr (one hex addr/line) |
| `analysis/symbols_merged.csv` | our function names + comments (`addr,name,type,comment,source`) |
| `maps/simos85.a2l` | cal maps/curves/constants + provenance (canonical ASAP2) |
| `core/ghidra/*.java`, `core/pipeline/reproduce.sh` | the shared pipeline |
| `maps/RESULTS.md` | findings/addresses not yet pinned to a labeled object |

> **Symbol provenance:** most function names in `symbols_merged.csv` are LLM-proposed
> (`source=llm`) — hypotheses, not verified findings. Only `source` ∈ {`verified`,
> `re-trace`, `fr-trace`} has been confirmed against the code or the Funktionsrahmen.

## TODO / open items

- [x] Ghidra headless reproducible from committed metadata (via the shared driver)
- [x] Seed symbols re-applied; bulk annotation pass complete (see `source` column)
- [ ] Promote high-value `llm` names to `verified` by tracing
- [ ] Import remaining map catalog from the WinOLS `.ols` + Funktionsrahmen into the A2L
- [ ] Obtain a bench/boot read to study SBOOT/CBOOT (RSA, flash loader)
