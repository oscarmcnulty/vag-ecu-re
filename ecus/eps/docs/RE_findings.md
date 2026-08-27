# 8R0909144F (EPS rack, RCEPS) — RE findings

## Container
`FL_8R0909144F_0507_BP.frf` → (VW_Flash `frf.decryptfrf`) → ODX → (`odx_extract.py`) → 6
logical blocks. The ODX carries only logical block IDs (0x30/0x50/0x60/0x70/0x80/0x91), not
memory addresses. **DB_2 (id 0x50, 536 KB)** is the ASW+CAL and the only block with code.

## Arch = Renesas V850, LE, base 0x0
Tested every candidate on decode self-consistency **and call-target concentration** (the
discriminator that survives cal-heavy data, since dense ISAs "validate" data):

| lang | invalid | call-target reuse | verdict |
|---|---|---|---|
| TriCore LE @0x80000000 | 0 functions recovered | — | reject (0x80.. ptrs were the 0x8007e007 fill) |
| ARM LE/BE | ~2–6% | **0** reused targets | reject (decodes data, no real calls) |
| PowerPC VLE | ~56% | — | reject |
| **V850 LE @0x0** | **0%** | **maxhits=79, 52 reused** | **accept** |

## Decompile
1898 functions (1883 clean). Limitation: V850 `gp` unresolved → `gp`-relative RAM vars and
absolute `movhi/movea` cal reads are not folded (`unaff_gp`, `*(gp+off)`). Fixing that is the
next unlock, analogous to the TriCore `FindBaseRegs`/`gp` step the shared pipeline runs.

## Software architecture (73 EPS_CORE/EPS_AUDI modules, from the embedded C manifest)
Includes **`lkf_container` / `lkf_datapool`** (Lane-Keeping Function), `uef_container`, and a
`y*_step`/`y*_acg` autocode-generated control layer (ea*, eb*, es*, et*, e*). The `lkf_*`
modules are where an external lane-keep torque request is processed and limited.

## HCA torque limit — not yet pinned
No cal-label strings in flash (they live in `EV_RCEPSAU48X_008.rod` / the A2L). The limit
(saturation + rate + max-hold cutout) is in `lkf_container`, gated by CAN reception, but the
constants are gp/absolute cal reads not resolved in this pass. Resolve `gp` + pointer
propagation, or apply the .rod/A2L, to name them.

## V850 base-register resolution (gp/tp) — DONE
crt0 at `0x259ca` (reset `jr` from vector 0) sets: **gp = 0xFFFF0000** (small-data/RAM base;
this chip's RAM is at 0xFFFF0000, not 0x03FF0000), **tp = 0x0001A238** (flash rodata base),
stack top 0xFFFFEFFC. `ghidra_scripts/SetV850Bases.java` sets these as program-wide register
values + defines the reset entry; re-running `DecompileAll` then yields a corpus with **zero
`unaff_gp`** — every cal/RAM read folds to an absolute address (e.g. `tp-0x7e1c -> 0x1241c`
rodata, `gp-0x4b8c -> 0xfffeb474` RAM). This is the unlock for reading calibration constants.

## Lane-keep (lkf) torque limit — in progress on the resolved corpus
The limit is a *calibration* value (saturates against a rodata read, not a literal), so it only
became legible after the gp/tp fold. Candidate CAN/signal-processing functions with saturation
+ CAN-ID tables located (e.g. FUN_0002ed50 handles a 0x3xx ID block with `< 0x8e4` clamps).
Still to pin: the specific lkf function that clamps the external steering-torque request and
its exact cap/rate/cutout constants.

## Const-data load offset (+0x12000) — IMPORTANT for reading tables
The image is loaded at `LOADBASE=0x0`, and **code** addresses are 1:1 with file offsets (the
V850 linear sweep at 0x0 is clean, and PC-relative branches resolve regardless of base). But the
firmware's **const-data absolute references are 0x12000 higher than their file offset**:
`file_offset = ghidra_data_address − 0x12000`.

Verified two independent ways:
- The E2E **CRC8H2F table** the checksum reads at address `0x12474` physically sits at file
  `0x474` (and validates live-bus LH_EPS frames 40/40 — see `can_tx.md`).
- The AFCAN config tables the TX code references at `0x125bc`/`0x12604`/`0x1281c`/`0x125c0` decode
  to clean, coherent data only at file `0x5bc`/`0x604`/`0x81c`/`0x5c0` (LH_EPS/HCA_01/ESP IDs,
  consecutive frame buffers) — reading them at the literal address yields garbage.

Interpretation: DB_2 (ASW+CAL) is flashed at ECU base ~0x12000 (a lower block occupies 0x0…0x12000),
so the firmware's baked-in absolute data pointers are 0x12000-based while we load the extracted
block at 0x0. **LOADBASE was left at 0x0** to keep the established code/symbol addresses (and all of
`symbols_merged.csv`) stable; re-basing to 0x12000 would resolve data refs automatically but shift
every symbol. **When reading any const table's bytes, subtract 0x12000 from the decompile address.**

## Reproducible labeling infrastructure (DONE)
- `BASEREGS=(gp=0xFFFF0000 tp=0x0001A238)` in `ecu.conf` → pipeline step 3 sets them + re-analyzes
  (generalized `core/ghidra/SetBaseRegs.java` to accept non-TriCore reg names). Fresh
  `reproduce.sh` now resolves the whole corpus (0 `unaff_gp`).
- `analysis/symbols_merged.csv` — 22 verified CAN-stack labels; applied by step 5, confirmed
  (e.g. `com_process_rx_pdus` → `com_rx_msg_g80()`…). Growable as more functions are traced.

## Torque-path RE — status (HONEST)
CAN *reception* is fully mapped (see can_rx.md) and the CAN stack is labeled. The **CAN-ID↔mailbox
map is now recovered** from the AFCAN mailbox ID table (`0x125c0`/file `0x5c0`): HCA_01 `0x126` =
mailbox 59, PLA_01 `0x130` = mailbox 58, plus ESP/Motor/Kombi/Gateway (`can_tx.md`). The earlier
"can't find the acceptance IDs" blocker was the const-data load offset (reading the table at the
literal address instead of `addr − 0x12000`) — resolved. The HCA status/mode path is traced
end-to-end (`hca_vs_pla.md`); the **TX side is fully solved and bus-validated** (`can_tx.md`).

Still open: the exact torque/angle *limit constants* on the HCA_01/PLA_01 propagation (the
saturation/rate/cutout cals). The remaining friction:
- The COM router also registers PDUs by **E2E Data ID** (0x113,0x118,0x169…), a second internal
  stage layered on the hardware mailboxes — do not confuse it with the CAN-ID map above.
- The receive ISRs `jr` into one large tangled dispatch (`FUN_000252f4`) that needs splitting.
Reliable next step: follow mailbox 58/59 → COM unpack → protected signal RAM, match the DBC bit
layouts (HCA_01_LM_Offset 9b@16 cNm, HCA_01_Status_HCA 4b@32; PLA_LW_Soll 13b@16 0.1°) to the
extraction, and read the limit cals at the corrected (−0x12000) offset.
