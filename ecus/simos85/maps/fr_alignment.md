# Funktionsrahmen alignment — targets for tuning + cruise min speed

Source: `Simos8.5.pdf` (Continental Funktionsrahmen, project S859300C), **13,002 pages**,
indexed via `core/pdf/fr_index.py` -> `analysis/fr/{fr_pages.jsonl,fr_labels.tsv}`.
Search with `core/pdf/fr_search.py`.

Naming convention (Continental, NOT Bosch-German): `C_*` = calibration constant,
`KF*`/maps = Kennfeld, `LV_*` = logical/boolean var, `LF_*` = logical field,
`NC_*`/`AC_*` = config/application constants, `TQI_*` = indicated torque, `VS_*` = vehicle speed.

> The FR gives label names, types, units and scaling — but **no addresses**. Addresses
> come from matching to the binary (descriptor table + axis signatures + consumer fn +
> tuner-diff anchoring). This file records the FR-side targets; binary offsets get filled
> in during Phase B/C.

---

## ② Minimum cruise-control speed  (FOUND on FR side)

Cruise control = **VHSC (Vehicle Speed Control)**: ch.70 (pp.12213–12303 logic),
ch.14.16 "Monitoring of cruise control conditions" (p.2193), ch.48 CAN (p.9089),
Audi task `AUDI_GRA_TSK` (pp.10352+). Labels use the `CRU_` infix.

Minimum-speed calibration constants (all `C_` constants, single byte, value directly in unit):

| Constant | FR meaning (verbatim) | Type | Unit | Res | def p. | binary |
|---|---|---|---|---|---|---|
| **`C_VS_MIN_CRU`** | "minimal vehicle speed for cruise **activation**" (activation floor, NOT a set-speed) | u16 0..FFFFh | km/h | 0.01 (FR); **operative 1/128** | **12415** | **`0x8007a26a` = 3.0 km/h** (`cruise_torque_pi_controller`) |
| **`C_VS_MIN_CRU_MON`** | "Minimum threshold for vehicle speed control active" (L2 monitor); "Derived from C_VS_MIN_CRU_OFF − 2 km/h" (p.2351) | u8 | km/h | 1 | **2196** | `0x800794ef`/`0x800794f2` = 15 km/h; EGAS twin `0x456c0`/`0x456bd` |
| `C_VS_MIN_AC_CTL_CRU` | "Lower limit of vehicle speed for acceleration control" (DCC accel-controller low-speed enable) | u16 | km/h | 0.01 (FR); operative 1/128 | **12502** | **`0x80079536` = 3.0 km/h** (`acc_status_error_aggregator`, cand.) |
| `C_VS_MIN_CRU_MPH` | MPH-market variant | u8 | mph | 1 | — | — |

**Corrected 2026-07-12:** the earlier "`C_VS_MIN_CRU` = min *set* speed ~30 km/h, def p.1250" was a
mis-citation — p.1250 is Cylinder Balancing. The FR defines `C_VS_MIN_CRU` (p.12415) only as an
*activation floor* with **no value stated** (level-1 value lives in the dataset), so the binary's
3.0 km/h is fully FR-consistent. Full trace + the 30-vs-3 resolution: **`cruise_control_flow.md`**.
Gate logic: `if (ego_speed < C_VS_MIN_CRU) -> not-active` (direct raw compare to the 1/128 km/h ego signal).

**To locate in binary (Phase C):** find the VHSC / cruise-monitor functions (annotation:
names containing cruise/vhsc/speed; FR consumer pages 2196/2202/2203 and 12280+), then the
`u8` compare against a ~30 constant in the cal region. Negative control: it should **not**
appear in the Stage1/2 tuner diff.

Related setpoint vars: `VS_SP_CRU` (active setpoint), `VS_SP_CRU_DISP` (display),
`VS_MAX_CRU` (max), `STATE_CRU_CTL` (engagement state machine), `CRU_SWI_POS` (stalk).

---

## ① Performance-tuning targets  (FR labels; maps pinned via tuner-diff in Phase B/C)

Strategy: the 50 changed blocks from `core/diff/diff3.py` (Original vs Stage1/2) ARE the
performance maps. Attach FR names by matching each block's consumer function + axes to these
functional variables.

**Torque structure (ceilings = top tuning targets):**
- `TQI_MAX` (p.562), `TQI_BAS_MAX` (561), `TQI_POW_MAX` (563), `TQI_VS_MAX` (565),
  `TQ_MAX_CLU` (558), `TQ_LIH_MAX` (557) — indicated/clutch/power torque limits.
- `LV_TQ_LIM_INTV` (441) — torque-limit intervention flag (find the map/threshold behind it).
- Pedal->torque request map (search `PED`/driver demand) feeds this structure.

**Limiters:**
- Rev limit: `N_MAX_THD` (p.464), `LV_N_MAX` (416).
- Top-speed limiter: `V_PVS_MAX` (567), `VS_MAX`/`LV_VS_MAX` (447).

**Boost / charge pressure:** `VBOOST` (568), `MFP_BOOST` (7117), wastegate `LV_PWM_WG_EXT_ADJ`
(423). Search the charge-pressure setpoint map (boost target vs rpm/load).

**Ignition / knock:** `KNKS`, `N_KNK` (464), knock adaptation `FAC_AD_KNK` (203). Ignition
timing map (Zündwinkel) feeds torque; pin via the diff blocks in 0x4xxxx cal region.

---

## Next (Phase B/C)
- `core/ghidra/DumpMaps.java`: walk descriptor table -> `maps/binary_maps.csv`
  (id, vaddr, dims, cell_width, axis values); tag blocks ∈ diff3 changed ranges.
- `core/maps/axis_match.py`: join binary maps ↔ FR axes ↔ consumer-fn annotations -> name them.
- Cruise: grep finished annotations for cruise/vhsc/speed; find the u8 min-speed compare.

---

## ③ ACC/cruise deceleration limit + fault (−3.0 m/s²)  (FR ↔ binary, UPDATE 52)

The −3.0 m/s² TSK_Verzoeg_Anf clamp + latching status-3 fault = the FR **AC_MIN_CRU / AC_DCRU_PLAUS**
mechanism (VHSC ch.70, diagnosis ch.70.6). Key encoding: the functional clamp is a **Kennlinie in cal data**,
u16 **850e-6 m/s² OFFSET-BINARY** (`phys=(raw−0x8000)·850e-6`) → **−3.0 = 0x7237** (not signed −3529); the L2
plausibility monitor uses a separate **0.001** scale → −3.0 = raw −3000.

> **Corrected 2026-07-12 → UPDATE 57 (do not cite the older "raw −3529 / not located" reads):** the functional
> decel clamp is **located** — the flat decel-limit Kennlinie at file **`0x5b71c`** (0x7237 cells, read by
> `8013c5d4:209-224`), NOT a scalar `C_AC_SP_LIM_NEG_CRU`. Per UPDATE 54 that FR constant is a calibrated **0**
> offset (added to a *computed* neg limit), consistent with FR's "computed neg limit" — it is not the −3.0
> truncation value. Full path + edit cells: `acc_flow.md` §2 and `decel_limit_flow.md`.

| FR label | meaning | type/res | binary anchor |
|---|---|---|---|
| functional decel clamp (`C_AC_SP_NEG_LIM_CRU` family) | delivered −3.0 saturation | u16, 850e-6 offset-binary | **flat Kennlinie file `0x5b71c` = 0x7237 = −3.0** (GRA `0xa005b71c` / Basic-ACC `0xa005b728`); read `8013c5d4:209-224` |
| `C_AC_SP_LIM_NEG_CRU` | negative *offset* on the computed min limit | u16, 850e-6 | **cal = 0** (an offset, not the −3.0 value — UPDATE 54) |
| `AC_DCRU_PLAUS` / `AC_MIN_CRU` monitor | L2 plausibility: fault if setpoint ∉ (−3.0,+2.0) | 0.001 m/s² | **`FUN_800c553c`**; cal `0x80043514=−3000`(−3.0), `0x80043512=+2000`(+2.0), rate `0x80043510` |
| `LV_ERR_AC_MIN_CRU` / status-3 | latching fault → `TSK_Status_GRA_ACC` = 3 | bool | via `d8e0→d744→d8b4→801eca44` (UPDATE 55; `acc_flow.md` §5) |
| `C_T_ERR_AC_MIN_CRU_H/_L`, `C_T_ERR_AC_DCRU_PLAUS_H/_L` | fault debounce timers (0.02 s steps) | — | — |

**Editable −3.0 today:** lower the flat Kennlinie cells at **file `0x5b71c`** (delivers harder braking) **AND**
raise the L2 monitor limit `0x80043514` (−3000) **together** (EGAS L1/L2 pair; mismatch → the monitor still
faults at −3.0). Recompute the cal-block checksum before reflash.
