# AL551 — Audi Q5/SQ5 ZF 8HP TCU (8R0927158AM, SW1003)

Transmission control unit: **ZF 8HP45/8HP55** torque-converter automatic, Bosch/Renesas
**SH72519 (SH-2A, big-endian)**. Ghidra language `SuperH:BE:32:SH-2A`. This pack reverse-
engineers the flashing container, the CAN interface, the calibration-map framework, and the
performance-relevant control loops (shift points, input-torque limit, drive-program/CHARISMA).

## Where things are
### `maps/` — the tuning description
- `al551.a2l` — ASAP2 1.71 A2L: MOD_PAR memory map, CAN RX/TX buffer + traced control-loop
  RAM `MEASUREMENT`s, and `CHARACTERISTIC`s for the **input-torque-limit Kennfelder** and the
  **shift-curve output columns** (the two headline tuning levers). Regenerate with
  `python3 maps/gen_al551_a2l.py` (metadata-only; reads the `analysis/*.csv`).

### `analysis/` — method + machine-readable state
- `symbols_merged.csv` — confirmed Ghidra labels (CAN layer, control-loop functions, map
  regions, RAM descriptor table). Applied by the pipeline (`ApplySymbols.java`).
- `can_map.csv` / `can_descriptors.csv` / `can_rx_buffers.csv` / `can_tx_buffers.csv` —
  CAN interface: 55 IDs (9 TX / 40 RX), the 44-record descriptor table, RX databufs, TX frames.
- `torque_maps.csv` — 38 input-torque-limit Kennfelder (`0x1b0cc0+`, 204 B, engine-torque axis
  0–600 Nm), gear×mode selected.
- `shift_curves.csv` — 318 shift curves (shared rpm input axis; **output column** is the lever).
- `cal_axes.csv` / `cal_ptr_tables.csv` / `cal_structure.md` — calibration framework structure.
- `ram_bases.csv` — RAM descriptor pointer table, resolved by **emulation** (see below).
- `dispatch_resolved.csv` — 12,930 flash function-pointer dispatch sites → 6,613 targets.
- `coverage.log` — byte-level coverage; `decompiles_r/` is the (gitignored) decompiled corpus.
- Docs: `docs/control_loops.md` (shift / torque / CHARISMA traces), `docs/ram_indirection.md`.

## Control loops (see `docs/control_loops.md`)
- **Shift points**: scheduler `0x141700`; gear-ratio monitor `FUN_0012fe7e`. Each shift record
  is `0x1C` B (7-pt input rpm axis `[1340..7500]` + 7-pt **output column** = the tunable). The
  high-throttle shift-RPM lever is the ~7250-rpm output cells.
- **Max torque**: input-torque-limit Kennfelder `0x1b0cc0+` (0–600 Nm axis), selected by
  gear×mode (`FUN_000b69d4` / `FUN_0010ca26` / `FUN_000deb16`) → result RAM `0xfff8c814` →
  `GE_MMom_Soll` (CAN 0x082).
- **CHARISMA**: `CAN 0x385` → `0xfff89454` → latch `0xfff95175` → `Getriebe_04`. On this SW the
  drive-program is **received/latched/echoed only — NOT a shift/torque map selector**; map
  selection is condition-indexed (gear×throttle×temp).

## RAM-pointer indirection (see `docs/ram_indirection.md`)
The RTE reaches descriptors through a boot-installed RAM pointer table. `core/ghidra/InitEmu.java`
runs the init stubs under Ghidra's SH-2A emulator and reads the resulting RAM — authoritative
(it corrected 72/154 slots the static deref got wrong). `analysis/gen_ram_bases.sh` regenerates
`ram_bases.csv`; the pipeline applies it (`ApplyRamDataImage.java`, step 6c) so RAM-base
indirection resolves while mutable scalars stay symbolic.

## Flashing container
The FRF/ODX use `ENCRYPT-COMPRESS-METHOD "22"` (XOR + bit-flag LZSS) — fully reversed in the
repo-root `al551_codec.py` (byte-exact, CRC32-validated). `tcu_8R_plaintext/` holds the decoded
plaintext blocks; `firmware/8R_full_flash.bin` is them reassembled at flash bases.

## Reproduce the labeled project
```
source .env.sh          # Ghidra 12.1.2 + JDK 21 on PATH
ecus/al551/reproduce.sh # needs firmware/8R_full_flash.bin locally (gitignored)
```
Ends `done.` with `analysis/coverage.log`: **10,408 functions, 99.9% of live bytes accounted,
~100% of code in functions, 99.0% clean decompile.**

## Open items
- Exact per-cell atlas: which shift/torque Kennfeld cell = which gear+program coordinate
  (deep in the generated descriptor-dispatch RTE; regions/structure are pinned).
- A handful of decompiler niceties (pass-by-reference `&slot` accessors fold only via xref).
