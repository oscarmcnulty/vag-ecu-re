# Handoff: name the ACC deceleration/speed plausibility diagnoses and pin their −3.0 / 15 km/h cal limits

You are continuing a reverse-engineering effort on a **Continental Simos 8.5** engine ECU (Audi Q5 3.0
TFSI, `8R0907551F`; Infineon **TC1796**, TriCore 1.3, little-endian, load base `0x80000000`). Image:
`ecus/simos85/firmware/8R0907551F_Original.bin` (2 MB OBD read; gitignored symlink, present locally).
Env: `source `.env.sh` (`GHIDRA_HOME`=Ghidra 12.1.2, `JAVA_HOME`=JDK 21). Ghidra project
`ecus/simos85/ghidra_proj/Simos85`, program `8R0907551F_Original.bin`. Decompiles in
`analysis/decompiles_r/<addr>.c` — **code coverage is now complete** (7478 fns; `MarkCalData` + `RecoverGapWalk`
recovered every function-calling code region; a final image-wide scan found 0 remaining code candidates —
see RESULTS UPDATES 48–51). So **if logic exists, it is decompiled.** Regenerate via `reproduce.sh` (now 7
steps incl. the cal data-typing step).

## The goal (openpilot longitudinal on the Q5)
On-car, when openpilot commands **< −3.0 m/s²** the engine **truncates TSK_Verzoeg_Anf (TSK_02/0x10c) to
−3.0** and latches **`TSK_Status_GRA_ACC_02 = 3`** ("GRA/ACC nicht möglich", clears only on key cycle). A
similar latch happens below a **~15 km/h** ACC-engagement floor. We want to name + raise both limits.

## READ FIRST (established this session — do not re-derive)
`maps/RESULTS.md` **UPDATES 52–53** (FR-confirmed mechanism + fault architecture), `maps/fr_alignment.md`
(FR↔binary decel table), `maps/can_signal_map.md` (CAN/Com), `maps/decel_limit_flow.md` (on-car evidence).
The **Funktionsrahmen** is indexed: `analysis/fr/{fr_full.txt, fr_pages.jsonl, fr_labels.tsv}`, search with
`core/pdf/fr_search.py analysis/fr --grep-labels '<regex>'` / `--label <NAME>` / `--term "<text>"`.

## State of knowledge (high-confidence, this session)
The −3.0 clamp + latching status-3 fault = the FR **AC_MIN_CRU / AC_DCRU_PLAUS** cruise-diagnosis mechanism
(VHSC ch.70; diagnosis ch.70.6). **Key encoding gotcha:** the cruise accel setpoint uses resolution
**850e-6 m/s²** (NOT 0.005) → −3.0 = raw **−3529** (0xF227); +2.0 = raw **+2353**. A separate L2 monitor
(`800c553c`) works in **0.001** scale (−3.0 = −3000, +2.0 = +2000). Prior −600(0.005) hunts were doomed.

### The fault-latch architecture (mapped, labelled in `symbols_merged.csv`)
- **`acc_status_error_aggregator` (0x80102f60)** — runs 13 cruise diagnoses, builds:
  `Ramd000d8e0` = OR of `(symptom==3)<<bit` = the **ERROR word (SYM_3)**; `d8d0`=(==1) warnings; `d8da`=(==2).
  Each diagnosis is enabled by a bit of `cal(iVar17+0x16e)` where `iVar17 = *(0x80090f80) = 0x800793a0`.
  `d8e0 & cal(iVar17+0x178)` (fatal-error mask) → ACC deactivation (`d000d746`/`d000d894`). A near-duplicate
  aggregation lives in `801dfe06` (the recovered giant; EGAS functional/monitor pair).
- **`acc_diag_debounce_evaluator` (0x801e3d78)** — `byte eval(byte *desc, uint cond, uint timing)`:
  `desc[0]`=last cond, `desc[1]`=confirmed symptom, `desc[2]`=counter; confirms `cond` after `timing`
  stable counts (FR `T_ERR_*` debounce) → **the latch** (why faults stick to key-cycle).
- **`ac_min_cru_plausibility_monitor` (0x800c553c)** — faults (`goto LAB_800c564e`) when integrated setpoint
  `sRamc0001732` exits `[cal 0x80043514=−3000=−3.0, cal 0x80043512=+2000=+2.0]` (0.001 scale) or a rate
  (`cal 0x80043510=32 *0x40`). **`0x80043514` = editable −3.0 monitor limit.** (Its output feeds a condition
  byte; exact wiring TBD.)

### The 13 diagnoses — descriptor / condition byte / enable+error bit (GROUND TRUTH from 80102f60)
`eval(&desc, cond, timing)`; each gated by `cal(0x16e)>>bit & 1`; `symptom==3` sets `d8e0` at the SAME bit.
Descriptor order is NOT the bit order — use this table:

| desc (d000d7xx) | cond byte | enable/d8e0 bit | (decompiler var) |
|---|---|---|---|
| d714 | d000d5b5 | **6** | iVar55 |
| d718 | d000d5bb | **0** | iVar36 |
| — (special) | d000d62b | **1** | cVar18 |
| d71c | d000d5d8 | **2** | iStack_d4 |
| d720 | d000d5f5 | **3** | iStack_d8 |
| d724 | d000d670 | **4** | iStack_e0 |
| d728 | d000d67f | **5** | iVar37 |
| d72c | d000d685 | **7** | iVar38 |
| d730 | d000d693 | **8** | iVar39 |
| d734 | d000d695 | **9** | iVar40 |
| d738 | d000d680 | **10** | iVar41 |
| d73c | d000d5fc | **11** | iVar42 |
| d740 | d000d683 | **12** | iVar43 |

Condition bytes are GATHERED (copied), not computed, by `801dec08` (most), `800cf8bc` (d680), `80102f18`
(d683). The actual PLAUSIBILITY CHECKS that set each condition to 0..3 are further upstream.

## THE TASKS (ranked)

### 1. Map the 13 condition bytes → FR diagnosis names (the unlock)
Two convergent methods — use both, they cross-check:
- **(a) FR enum/index.** `fr_search.py analysis/fr --grep-labels 'NC_IDX_DIAG_AC|NC_IDX_DIAG_VS|NC_IDX_DIAG_BRAKE'`
  and `--label NC_IDX_DIAG_AC_MIN_CRU` etc. to get each diagnosis's canonical index; the FR ERR_SYM table
  (pages ~12234–12236) lists the cruise diagnosis instances (AC_DCRU_PLAUS, AC_DE_BRAKE_CRU,
  AC_DE_ORNG_ENG_CRU, AC_LGT, AC_MAX_CRU, AC_MIN_CRU, AC_ORNG_CRU, AC_VEH_CLC, BRAKE_*, VS_*, …). Match the
  `cal(0x16e)` enable mask + descriptor/bit order above to the index order.
- **(b) Trace each condition byte to its CHECK (more robust).** For each of the 13 cond bytes, find the
  writer of its SOURCE (what `801dec08`/`800cf8bc`/`80102f18` copy FROM), then the function that sets that
  source to 0..3. The check's comparison names the diagnosis: **accel setpoint < a ~−3.0 limit ⇒ AC_MIN_CRU**;
  **vehicle speed < a ~15 km/h cal ⇒ the VS/speed diagnosis**; brake-pressure/torque ⇒ BRAKE_*. Decompile-grep
  the cond-byte and its source with `grep -rlE`. `801dec08` is a big scatter/gather — read the RHS that feeds
  each `DAT_d000d6xx =`.
Deliverable: a table {bit → FR diagnosis name → check fn → cal}. Identify the AC_MIN_CRU bit and the speed bit.

### 2. Pin `C_AC_SP_LIM_NEG_CRU` (−3.0 functional) and `C_VS_MIN_CRU_MON` (15 km/h)
- **`C_AC_SP_LIM_NEG_CRU`** = "Limiting factor for deceleration set point for cruise control", u16, res
  **850e-6 m/s²** → −3.0 = raw **−3529** (0xF227). FR shows it applied as a `max()` clip on `AC_CRU_REQ_NOT_LIM`
  (`fr_full.txt` lines ~2111477, 2117623). It is read via a **cal-struct pointer** (NOT a1-relative, so absent
  from `cal_reads.csv`). Caveats already established: a plain cal-region scan for exact −3529 = 0 hits — so
  either the calibrated value differs slightly, or it is pointer-addressed. **Also search the 0.001 encoding**
  (−3.0 = −3000; the L2 monitor uses it) and the ACC cal-struct family pointed by `*(0x80090f80..0x80090fb0)`.
  Best route: find the functional limiter FUNCTION (the `max()` on the accel request) via the AC_MIN_CRU check
  from Task 1, then read whatever cal it clamps to (in whatever scale) — don't assume the constant's location.
- **`C_VS_MIN_CRU_MON`** = "Minimum threshold for vehicle speed control active", **u8 km/h** (res 1), FR
  **ch.14.16** "Monitoring of cruise control conditions" (Fig 14.16.5): `VS_MON < C_VS_MIN_CRU_MON` → SR-SET
  `LV_CRU_MON_ACT_MON` → cruise off (`fr_full.txt` ~418078–418193; "derived from C_VS_MIN_CRU_OFF − 2 km/h").
  Find via the speed diagnosis from Task 1, or the ch.14.16 monitor. **First establish the vehicle-speed
  variable + its scale** (do NOT reuse the withdrawn `d000d644<0x180` guess — see the UPDATE-53 CORRECTION;
  `d000d644 = d0005618*32/25` from a percentage-shaped source, unconfirmed as speed). Cross-check any candidate
  against a known speed on the CAN map.

### 3. Confirm the `d000d8e0` → `TSK_Status_GRA_ACC_02 = 3` packer byte
`d8e0` (error word) & `cal(iVar17+0x178)` → deactivation flags `d000d746`/`d000d894`. Trace forward to the
byte that becomes TSK_04's status. TSK_04 (0x10e) is assembled by `canmo_10e_TSK_04 (0x8011e9ce)` from
`*(d000d404)+8` (payload) with a status byte near `*(d000d404)+0xf`; the Com buffer is filled via the
runtime-dispatched Com TX (see can_signal_map "Com wall"). Find where the ACC state → status value 3 is
written (candidates seen: `801e3f26` sets `d000d9c7=3`; `80102f60` writes `d000d8e8∈{0,1,2}` + the d8xx block).
Deliverable: the exact RAM byte = TSK_Status_GRA_ACC_02 and the `=3` assignment tied to the fatal-error mask.

## KEY TOOLS
- **`core/pdf/fr_search.py analysis/fr`** — FR search: `--grep-labels '<regex>'`, `--label <NAME>`,
  `--term "<text>" [--context N]`. FR gives label/type/unit/resolution but **no addresses** — anchor to the
  binary via the consumer fn + value/scale. Decel family = FR ch.70 (VHSC) + 70.6 (CRU/VVSL diagnosis) +
  14.16 (cruise-condition monitoring).
- **decompile-grep** — the decompiler resolves a0/a1-relative RAM to `DAT_d000xxxx`/cal addresses, so
  `grep -rlE 'd000XXXX ='` finds writers, `grep -rlE 'd000XXXX'` finds all refs. USE THIS for RAM dataflow.
- **`core/ghidra/FindRefsTo.java`** — a0/a1-relative xref (`FindRefsTo <addr>`; `<lo> <hi> --range` maps a
  region). For cal reads via absolute/base+disp.
- Labelled already: `0x80102f60` acc_status_error_aggregator, `0x801e3d78` acc_diag_debounce_evaluator,
  `0x800c553c` ac_min_cru_plausibility_monitor. Add new labels to `analysis/symbols_merged.csv`
  (`address,name,type,comment,source`); they apply on the next `reproduce.sh`.

## Ground rules
- Static + FR only; **no on-car** (separate/unavailable). Prefer decompile-grep + `FindRefsTo` + `fr_search`.
- **Be honest about scale/units** — the −3.0 lives in ≥2 encodings (850e-6 functional, 0.001 monitor).
  Verify a constant's SCALE via its consumer before claiming its m/s²/km-h value (cf. the withdrawn
  `d000d644<0x180` guess — RESULTS UPDATE-53 CORRECTION). Don't pattern-match a stray immediate to a spec value.
- To raise a limit you must move the **functional AND monitor** copies together (EGAS L1/L2; mismatch →
  `LV_SYM_ERR_*` fault) and recompute the cal-block checksum (`core/checksum`) before any (future) reflash.
- Log findings as a new UPDATE in `maps/RESULTS.md`; keep the tree reproducible (`reproduce.sh`; validate new
  `function_entries.txt` additions with `CheckManifest.java`).

## Already-in-hand editable levers (regardless of the above)
- **Engine-torque ACC decel −0.82 m/s²** @ file `0x79982` (`0x80079982`, s16 −164, 0.005 scale).
- **−3.0 L2 monitor limit** @ `0x80043514` (s16 −3000, 0.001 scale) — the plausibility floor in `800c553c`.
  (The functional `C_AC_SP_LIM_NEG_CRU` truncation constant is Task 2 — needed for the actual delivered decel.)
