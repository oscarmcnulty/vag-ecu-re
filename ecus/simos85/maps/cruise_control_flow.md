# Cruise / ACC control flow — how it works, and the low-speed "crawl" floors

How the Simos8.5 engine ECU's longitudinal cruise/ACC works, focused on the
**low-speed (crawl) speed floors**. Built from decompile tracing
(`analysis/decompiles_r/`) + the Continental Funktionsrahmen (`docs/Simos8.5.pdf`,
searched via `core/pdf/fr_search.py`). Addresses are load base `0x80000000`;
`0xa00xxxxx` = uncached mirror of flash `0x800xxxxx`.

The system is **VHSC** (Vehicle Speed Control) in the FR — plain cruise = GRA,
distance/adaptive = DCC/ACC. Speed unit throughout the ego path is **1/128 km/h**
(`128 counts = 1.0 km/h`); ego speed working copy = `DAT_d000d644`, ACC-monitor copy
`DAT_d000da54` (= FR `VS_MON`).

## Three functional layers

| layer | function | vaddr | what it does |
|---|---|---|---|
| 1. coding/enable | `cruise_state_machine` | `0x80116e08` | reads coding byte `DAT_800443e1`; latches cruise-present/enabled per channel (GRA + DCC) → `LV_CRU_ENA` / `LV_DCC_ENA` (`d000a910-a929`) |
| 2. torque request | `cruise_torque_pi_controller` | `0x801e9b86` | builds the cruise engine-**torque** setpoint `DAT_d000e2e8` via a PI loop; owns the **3.0 km/h functional activation floor** |
| 3. L2 monitor + diag | `acc_status_error_aggregator` | `0x80102f60` | the L2 low-speed monitor + 13-way ACC diagnosis coordinator; owns the **3.0 km/h creep discriminator**, the **15 km/h monitor floors**, and the status-3 fault path |

(The ACC **brake/decel** request path — the −3.0 m/s² clamp — is separate:
`acc_brake_request_formation 0x8013c5d4` → `acc_brake_setpoint_statemachine 0x8013ef46`
→ packer `80137a00`. See `acc_flow.md` / `decel_limit_flow.md`.)

## Layer 1 — coding/enable (`cruise_state_machine 0x80116e08`)
Pure config gate, no speed logic. Reads coding byte `DAT_800443e1`:
- GRA channel enabled by bit7 (+ feature ptr `*0x80086e20`) OR bit3 (+ `*0x80086e30`),
  cross-checked against `d000aa6c/aa6d`; sets the `d000a910/912…926/928` state block.
- DCC channel enabled by bit6/bit2 the same way; sets `d000a911/913…927/929`.
- On enable/disable edges it calls `check_status_flags(&d000a8f0/a8f8, 0x40)` /
  `process_control_flags(...)`. These blocks are `LV_CRU_ENA` / `LV_DCC_ENA`, the
  master feature-present/authorised flags consumed by the FR `CRUC_MG005` state machine.

## Layer 2 — torque PI controller (`cruise_torque_pi_controller 0x801e9b86`)
Builds `DAT_d000e2e8`, the cruise engine-torque setpoint. Cal struct base =
`*0x80090f94` (→ `0x8007a204`); it reads PI gains/limits at struct offsets
`+0x40/+0x46/+0x4c/+0x50/+0x56/+0x58/+0x5a/+0x5c/+0x60/+0x62`, sums four PI terms
(`d000e2d6/d8/da/dc`), and clamps the output to `[…, *(u16)(base+0x62)*10]`.

**★ Functional activation floor — `C_VS_MIN_CRU` @ `0x8007a26a` (base+0x66):**
```c
// 801e9b86:299-304
if ( … && (uVar3 = DAT_d000d644, uVar3 < *(ushort *)(iVar7 + 0x66)) ) {  // ego < C_VS_MIN_CRU
    DAT_d000e2c5 = (*(byte*)(iVar7+0x41) < DAT_d000d62a);                 // near-standstill branch
}
// :331-334  e2c5==0 is one condition that calls set_global_param_801ea218(0)  (integrator reset)
```
Below this ego speed the controller takes its **near-standstill branch** (sets
`d000e2c5`, which gates the integrator/anti-windup reset). This is the level-1
"may the cruise *controller* be active this low" gate.

## Layer 3 — L2 monitor + diagnosis (`acc_status_error_aggregator 0x80102f60`)
Runs each cycle. Cal struct base = `*0x80090f80` (→ `0x800793a0`,
`cal_acc_l2monitor_struct`). Builds the ACC error word `d000d8e0`, master state
`d000d8ee ∈ {0,1,2}` (→ `acc_status_hmi_state_mapper 0x801eca44` → `TSK_Status_GRA_ACC`),
and the low-speed monitor outputs. Runs 13 symptom debounces via
`acc_diag_debounce_evaluator 0x801e3d78`. Deactivation path is **dead** (fatal mask
`base+0x178 = 0`); the status-3 path is **live**.

**★ Creep / accel-control gate — `0x80079536` (base+0x196), 3.0 km/h:**
```c
// 80102f60:724-727
bVar23 = *(ushort *)(iVar17 + 0x196) <= DAT_d000da54;   // C_VS_.._AC_CTL <= ego
UNK_d000d88c = UNK_d000d88c & 0xef | bVar23 << 4;       // d88c bit4 = "moving >= 3 km/h"
```
No debounce. `d88c` bit4 is a **moving-vs-standstill discriminator** that switches
several status computations between their standstill and driving branches and is one
AND-term of the (dead) fatal-deactivation path.

**15 km/h L2 monitor floors — `C_VS_MIN_CRU_MON` @ `0x800794ef`/`0x800794f2` (base+0x14f/+0x152), u8×128:**
```c
// 80102f60:1581-1600  -> debounced output d000d79a
if ((d890 & 2) && (DAT_d000da54 <= *(byte*)(iVar17+0x14f) * 0x80)) {   // ACC active & ego <= 15 km/h
    // request inside accel window [base+0x158/+0x15a .. base+0x15c/+0x15e]
    update_char_and_flag(&d79b,&d79a, ok, *(byte*)(iVar17+0x135));     // debounce time = base+0x135
}
// 80102f60:1641-1655  -> d000d8ab / debounced d000d7a7  (band [base+0x153 .. 15 km/h], no active symptom)
```
These bracket ego speed inside a **low-speed operating band** (`[lower_edge … 15 km/h]`)
and, gated on ACC-active + an accel-request window + no active symptom, produce the
**debounced** crawl-monitor outputs `d79a` and `d7a7`/`d8ab`.

## The four low-speed thresholds — do not conflate

| threshold | flash | raw | scale | read in | role | FR label (page) |
|---|---|---|---|---|---|---|
| **activation floor 3.0 km/h** | `0x8007a26a` | 384 | 1/128 km/h | `cruise_torque_pi_controller :301` | level-1 "controller may be active" / near-standstill PI branch | **`C_VS_MIN_CRU`** (p.12415) |
| **creep / accel-ctl gate 3.0 km/h** | `0x80079536` | 384 | 1/128 km/h | `acc_status_error_aggregator :725` | moving≥3 discriminator (accel-controller low-speed enable) | **`C_VS_MIN_AC_CTL_CRU`** (p.12502, *cand*) |
| **L2 monitor floor 15 km/h** (×2) | `0x800794ef` / `0x800794f2` | 15 | u8 km/h (×128) | `acc_status_error_aggregator :1583/:1645` | L2 crawl-monitor operating band | **`C_VS_MIN_CRU_MON`** (p.2196) = `C_VS_MIN_CRU_OFF − 2` (p.2351) |
| **EGAS-L2 twin 15 km/h** (×2) | `0x800456c0` / `0x800456bd` | 15 | u8 km/h | `egas_l2_monitor_cal_init 0x800a0c9c` | independent EGAS shadow-RAM monitor (`^0xff`) | `C_VS_MIN_CRU_MON` / `C_VS_MIN_DCC_MON` (p.2196) |
| hysteresis 13 km/h (×2) | `0x800456be` / `0x800456c3` | 13 | u8 km/h | monitor layer | `MON − 2` clear/hysteresis threshold | (`C_VS_MIN_CRU_OFF` family) |

## What the FR says (resolving the "30 vs 3 km/h" confusion)
- **`C_VS_MIN_CRU`** (FR **p.12415**, ch. VHSC basic functions): verbatim *"minimal vehicle
  speed for cruise **activation**"*, mode `V`, `0…655.35`, **res 0.01 km/h** — **no numeric
  value in the FR** (level-1 value lives in the dataset/DAMOS). It is an *activation floor*,
  NOT a minimum *set* speed. Sibling `C_VS_MAX_CRU` = *"Maximal vehicle speed for cruise
  activation"*. The old alignment note ("~30 km/h min set speed, p.1250") was mis-cited —
  p.1250 is Cylinder Balancing, unrelated. So **3.0 km/h is fully FR-consistent.**
- **`C_VS_MIN_CRU_MON`** (FR **p.2196**, ch.14.16 ECM2 process monitoring): verbatim *"Minimum
  threshold for vehicle speed control active"*, u8, **res 1 km/h**; *"Derived from level-1
  calibration of `C_VS_MIN_CRU_OFF` minus 2 km/h"* (p.2351). Independent L2 monitor, anchored
  to the **turn-OFF** speed — a different quantity from the activation floor by design, so the
  15 vs 3 split is expected, not a contradiction.
- **`C_VS_MIN_AC_CTL_CRU`** (FR **p.12502**, ch. Acceleration control): verbatim *"Lower limit
  of vehicle speed for acceleration control"*, res 0.01 km/h — the low-speed enable of the
  closed-loop **acceleration controller** that DCC/ACC drives. Best FR match for `0x80079536`.
- DCC is architected to control toward standstill (`C_VS_L_AC_DRIV_SP_CRU`,
  `C_VS_LIM_HLD_AC_CTL` auto-hold, follow-to-stop map `IP_AC_SP_MIN_DCC_FOL_2_STOP` p.12504) —
  but follow-to-stop is **not compiled** into this firmware (`d000a758` dead; UPDATE 60).

## ⚠ Scale note (operative vs FR-metadata)
`C_VS_MIN_CRU` @ `0x8007a26a` is compared **directly** to `DAT_d000d644` (a **1/128 km/h**
signal, proven by ~15 speed cals landing on integer km/h at 1/128). So the **operative**
scale in this firmware is **1/128 km/h → raw 384 = 3.0 km/h**, and that is what the A2L
uses (edit raw = target_km/h × 128). The FR lists resolution **0.01 km/h** (→ 3.84) — a
DAMOS-metadata resolution that does **not** match the in-code raw compare. Operative wins
for editing; the discrepancy is flagged, not hidden. (`C_VS_MIN_AC_CTL_CRU` @ `0x80079536`
has the same situation and is likewise 1/128 → 3.0.)

## Open items
- `0x80079536` FR label is `C_VS_MIN_AC_CTL_CRU` (accel-controller enable) vs
  `C_VS_LIM_HLD_AC_CTL` (auto-hold transition) — both plausible; `d88c` bit4 reads as a
  general moving/standstill discriminator. Disambiguate by tracing every `d88c & 0x10` reader.
- `C_VS_MIN_CRU_OFF` naming: FR says `MON = OFF − 2`, so with MON=15 the OFF should be ~17,
  but the L2 block holds 13 (= MON − 2). The `0x456be/0x456c3 = 13` cals are the **MON−2
  clear/hysteresis** values, not `OFF` itself; the true `C_VS_MIN_CRU_OFF` (~17) is not yet
  pinned. Low-priority.
