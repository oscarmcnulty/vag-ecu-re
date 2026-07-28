# Stage1 / Stage2 tuner-diff — what changes, and the canonical name of every changed map

Full 3-way diff of `8R0907551F_{Original,Stage1,Stage2}.bin` (2 MB TC1796 images), every
changed calibration block identified and attributed to its consumer function + FR family.

**Method.** (1) `core/diff/diff3.py` over 0x0–0x200000 → 30 changed blocks, **all** in the
calibration region 0x40940–0x7a393; **zero code bytes differ**. (2) Consumers + axes resolved by
`core/ghidra/TraceMapCalls.java` (→ `maps/map_calls.csv`) joined to the diff via
`maps/gen_map_consumers.py` (→ `maps/map_consumers.csv`); low-region scalars additionally from
`analysis/cal_reads.csv`. (3) Canonical names from the A2L catalog (`maps/a2l_catalog.csv`, generated from `maps/simos85.a2l`) where
covered, else the FR family from the decompiled consumer (`analysis/decompiles_r|_extra/*.c`) +
`core/pdf/fr_search.py`.

Confidence: **★★★** canonical (A2L/FR-verified) · **★★** FR family from decompiled consumer ·
**★** value-semantics only.

## Headline

1. **A coordinated torque-model rework, not just "raise the ceiling."** The tune moves the torque
   ceilings (`ip_tq_pow_max_*`), the torque model (`ip_tqi_ref` + the `EFF_TQI_COR` structure at
   0x48xxx), **several torque-limit/factor blocks** (0x55e64, 0x55f04, 0x57620 — all set toward
   their max/removed), plus fuel-rail pressure, rev limit, top-speed limit, and ignition advance.
   (Consumer verification 2026-07-12 corrected the FR labels for those three — see the table notes.)

2. **Stage1 and Stage2 are different philosophies.** Stage1 = higher peak torque (600 Nm),
   lightest touch, stays inside the stock safety monitors. Stage2 = lower peak (520 Nm) but
   systematically **defeats the protection layer** — the L2 torque monitor (0x40940), the `ABC`
   load-plausibility window (0x4eb6c), thermal protection (0x423ce), the plausibility tolerance
   (0x40abc), and a monitor table (0x6567a) — none of which Stage1 touches. Both stages remove the
   Efficiency-drive-mode torque cut (`ip_tq_pow_max_eco`) and force the 0x55e64 factor block to unity.

## A. Torque delivery — ceilings, model, correction factors

| vaddr | name / FR family | conf | consumer | Original → S1 → S2 |
|---|---|---|---|---|
| 0x560f4 / 0x561e4 | `ip_tq_pow_max_at[0/1]` — AT torque ceiling | ★★★ | — | 433 → **600** → **520** Nm |
| 0x56554 / 0x56644 | `ip_tq_pow_max_eco[0/1]` — Efficiency-mode ceiling | ★★★ | — | 325 → 600 → 520 (reduction removed) |
| 0x56764 / 0x5680c / 0x568b4 | `ip_tq_pow_max_mt[0/1]`, `mt_4wd` | ★★★ | — | 433 → 612 → 520 (4WD: S1 only) |
| 0x57bd4 | `ip_tqi_ref` — 16×12 torque model | ★★★ | — | peak 714 → **755** → 755 Nm |
| 0x48c18 / 0x49114 / 0x4925c | `EFF_*` / `IP_EFF_TQI_COR_CUS` efficiency↔torque-correction structure; 0x49114 = `TQI_MAX`-type ceiling | ★★ | `FUN_800faef8` | 0x49114 +5% ceiling; 0x48c18 corner-lift; 0x4925c +30% rpm fill-curve |
| 0x48dde | 1-D charge↔torque reference curve vs N (tqi model companion) | ★★ | `FUN_8014fe88` / `FUN_800fcd78` | raised |
| 0x55e64 | factor block (unity 0x8000) — **consumer unresolved** (FAC_TQI_POW_MAX/FUN_800fed30 withdrawn on review; read nowhere in decompiles) | ★ | — | → unity (both stages): a reduction removed |
| 0x55f04 | `FAC_TQI` reserve/limit factor | ★★ | `FUN_801006d0` | **S1** → max; S2 stock |
| 0x57620 / 0x5774e | upper torque-limit value → clamp `min(torque, af8·16)` (EFF_TQI_COR "biases torque up" reading **withdrawn** — it's a torque value, not a factor) | ★ | `FUN_8014e668` → `FUN_8011a6ac` | lowered 973→922 → slightly **tightens** the cap |

## B. Limiters, monitors & protection — loosened so the extra torque passes

| vaddr | role (decompiled consumer) | conf | consumer | change |
|---|---|---|---|---|
| 0x43c2c | **`V_PVS_MAX` top-speed limiter** (5-entry table → PI speed governor; 1/128 km/h) | ★★ | `FUN_800dd3a4`/`FUN_8017338c` | **~159 → 234 → 250 km/h** |
| 0x44512 / 0x44518 | **`N_MAX` rev limiter** vs coolant / oil temp | ★★★ | `FUN_8017a1e0` | 7200 → **7392** rpm |
| 0x40940 | **L2 torque monitor** (Momentenüberwachung) deviation curve + config | ★★ | `FUN_8013273c` | **S2 → 0xFFFF: over-torque trip defeated** |
| 0x40abc | redundant-signal plausibility tolerance | ★ | `FUN_80163528` | **S2**: +60% (looser) |
| 0x4119e | per-bank thermal/component (EGTR/BTS) monitor thresholds | ★★ | `FUN_801564d0` | +3% (trips later) |
| 0x423ce | thermal permissive-gate threshold (mean of two per-bank temps; high temp *clears* the enable) | ★★ | `FUN_800ffba8` | **S2**: +6% → inhibit later |
| 0x449fc | per-bank thermal-protection torque-limiter params | ★★ | `FUN_8018e814` | +2% |
| 0x4eb6c / 0x4eb78 | **`ABC_INC_LOAD` load-plausibility window** (min/max vs N) gating a per-bank monitor | ★★ | `FUN_8012df54` / `FUN_801d424c` | **S2 opens wide → gate deleted** |
| 0x6567a | limiter / monitor table | ★ | (indirect) | **S2 zeros the whole table** |

## C. Fueling & ignition

| vaddr | name / FR family | conf | consumer | change |
|---|---|---|---|---|
| 0x5ee5c | `ip_fup_sp_hom` — HPFP rail-pressure setpoint | ★★★ | — | ~115 → **129** bar |
| 0x7865b / 0x7870e / 0x787c2 | **base ignition-timing bank** (IGA / Zündwinkel), 3 maps | ★★ | `FUN_8011d2b4` / `FUN_800cea0c` / `FUN_800d559c` | **+1…2° advance** |
| 0x74084 | ignition / charge-time correction | ★ | (ignition cluster) | +2 all cells |
| 0x6d3ac | factor/threshold block — **consumer unresolved** (MFF/`FUN_8017ecb8` binding withdrawn: the grids it reads are past the block) | ★ | — | S2 reshape |

## D. Other / honestly unidentified

| vaddr | best read | conf | note |
|---|---|---|---|
| 0x53235 / 0x532f5 | per-bank index → charge/boost gate (`[0]/[1]` pair) | ★ | `FUN_800fe060`; traced fully, no clean FR label |
| 0x48e2c | two-level limit / setpoint | ★ | in the `FUN_800faef8` / `FUN_8013273c` EFF/torque bank |
| 0x7a38c | ACC / cruise accel-profile curve | ★ | S2 extends the upper end |

## Notes / caveats

- **Drive modes:** only **Efficiency** (of Comfort/Auto/Sport/Efficiency, coordinated by the BCM
  "Charisma" over CAN — FR ch.67.8) has its own engine torque map (`ip_tq_pow_max_eco`); Sport =
  accelerator-pedal characteristic (`CAN_STATE_TAR_EMS_SPT`), not a torque ceiling. See
  `performance_maps.md`. Both tunes neutralize the Efficiency-mode cut.
- The `★` and low-`★★` FR members are **families**, not name-matched addresses — the FR gives
  labels/units but no addresses, and the descriptor→FR join (`fr_alignment.md` Phase B/C) is not
  complete. Auto-generated `FUN_*` / `process_*` symbol names are not FR names; identifications rest
  on data-flow (output global), unity scalings (0x8000 / 4096 / 1024), the `(T+300)` gas-law
  signature, and the proven rpm index `DAT_d000b4f8 = N≫5`.
