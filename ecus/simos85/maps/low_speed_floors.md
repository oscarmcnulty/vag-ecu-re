# The sub-15 km/h floors — two independent mechanisms

Cruise/ACC on this ECU stops working below ~15 km/h for **two separate reasons**, and they are not
alternative descriptions of one thing. Editing either one alone leaves the other in place.

| # | mechanism | where it lives | what it does |
|---|---|---|---|
| **A** | `C_VS_MIN_CRU_MON` = 15 km/h internal L2 crawl monitor | **inside this ECU**, cal `0x800794ef` / `0x800794f2` | latches a key-cycle ACC fault → `TSK_Status_GRA_ACC` = 3 |
| **B** | `ECD_nicht_verfuegbar` — the ESP's *Externally Controlled Deceleration* permission | **in the ESP/ABS**, arriving on ESP_05 (0x106) bit 33 | withdraws brake-request authority inside `8013c5d4` |

**They are disjoint** (CONFIRMED): the whole mechanism-A latch chain — the aggregator body
(`80102f60`, whose prologue falls through into `801dfe06`) and the status mapper `801eca44` — contains
**zero `esp05_` references**. Conversely mechanism B travels entirely through
`801408bc` → `d000b296` → `8013c5d4` and never touches the diagnosis accumulator.

Practical consequence: **editing `C_VS_MIN_CRU_MON` clears the latching fault but does not enable
sub-15 km/h braking**, because the ESP still refuses ECD below ~15 km/h and that half is not in this
ECU at all. See §5 for what the MED17.1.1 pack established about the ESP side.

Addresses are load base `0x80000000`; file offset = `addr & 0x1FFFFFFF`. Ego speed working copy is
`DAT_d000d644`, monitor copy `DAT_d000da54` (= FR `VS_MON`), both **1/128 km/h** (128 counts = 1.0 km/h).

---

## 0. Where the speed floors sit in the ECU

| layer | function | vaddr | role |
|---|---|---|---|
| 1. coding / enable | `cruise_state_machine` | `0x80116e08` | reads coding byte `DAT_800443e1`; latches cruise-present/enabled per channel (GRA + DCC) → `LV_CRU_ENA` / `LV_DCC_ENA` (`d000a910-a929`). Pure config gate, no speed logic. |
| 2. torque request | `cruise_torque_pi_controller` | `0x801e9b86` | builds the cruise engine-**torque** setpoint `DAT_d000e2e8` via a PI loop; owns the **3.0 km/h activation floor** |
| 3. L2 monitor + diagnosis | `acc_status_error_aggregator` | `0x80102f60` | the L2 crawl monitor and 13-way ACC diagnosis coordinator; owns the **3.0 km/h creep discriminator**, the **15 km/h monitor floors** and the status-3 path (mechanism A) |
| 4. brake-request formation | `acc_brake_request_formation` | `0x8013c5d4` | consumes the ESP's ECD permission via `d000b296` (mechanism B) |

The FR calls the system **VHSC** (Vehicle Speed Control): plain cruise = GRA, distance/adaptive =
DCC/ACC.

---

## 1. Mechanism A — the internal 15 km/h L2 crawl monitor (CONFIRMED)

Cal struct base for `80102f60` is `*0x80090f80` → `0x800793a0` (`cal_acc_l2monitor_struct`).

```c
// 80102f60:1594-1611  ->  debounced output d000d79a
if ((d890 & 2) && (ram_acc_vehicle_speed_mon <= *(byte*)(base+0x14f) * 0x80)) {  // ACC active & ego <= 15 km/h
    // ... plus an accel-request window [base+0x158/+0x15a .. base+0x15c/+0x15e]
    update_char_and_flag(&d79b, &d79a, ok, *(byte*)(base+0x135));                // debounce time
}
// 80102f60:1656-1660  ->  d000d8ab / debounced d000d7a7
//   band [ base+0x153 .. base+0x152 (=15 km/h) ], gated on no active symptom
```

- Both compares are **`<=` on an unsigned u8 scaled ×0x80**, so the threshold **cannot be "zeroed out"
  to exclude standstill**: `0 <= 0` is true, and `0x80`–`0xFF` give a 128–255 km/h threshold that
  matches everywhere. It can only be moved, not disabled, from the cal.
- Full trigger also requires an accel-plausibility band (cals `0x800794f8/fa/fc/fe`) and, for the second
  compare, a lower band edge at `0x800794f3`.
- **On-car it is a real key-cycle-latching L2 fault below ~15 km/h** (openpilot ground truth). Path:
  the debounced monitor output feeds the 13-diagnosis accumulator inside `80102f60` → `d000d8e0 != 0` →
  debounce → `d000d744` → **`d000d8b4`**, which gates recompute (`80102f60:718-731`: the accumulator is
  only rebuilt while `d8b4 == 0`) = the key-cycle latch → `d8e2.bit2 = 0` → status 3 via `801eca44`.
- The **deactivation** path (`d8e0 & cal(base+0x178)`) is dead — the fatal mask is 0. Only the status-3
  path is live, and the 15 km/h monitor outputs (`d79a`, `d7a7`, `d8ab`) are **not read anywhere in the
  CRUC state machine** (`acc_flow.md` §4.3). So mechanism A produces a fault and a CAN status, not a
  state-machine transition.
- `da46` (the monitored accel) reads as measured/computed rather than raw command. **GAP:** which exact
  one of the 13 diagnoses latches below 15 km/h, and whether it is avoidable by sending different
  signals — the empty accel-band escape, `ACC_Anhalten`-hold versus raw decel — without a cal, coding or
  firmware change.
- **INFERRED:** the cal base `0x800793a0` is reached through the runtime pointer `iRam80090f80` and has
  no static xref. Every `+offset` value is semantically consistent, but verify the base before relying
  on an absolute edit address.

### The A2L `C_VS_MIN_CRU_MON` is a different cal

The A2L (`simos85.a2l`) carries a `C_VS_MIN_CRU_MON` at file `0x456C0`/`0x456BD`, also = 15. That is the
**EGAS-L2 shadow-RAM twin**, loaded with a `^0xff` ASIL verify by `egas_l2_monitor_cal_init`
(`0x800a0c9c`) from a different cal base. It is **not** the value compared against vehicle speed. To move
the operative crawl floor edit `0x800794ef` / `0x800794f2`; then check the `0x456C0` twin and keep it
consistent, or the EGAS L1/L2 pair mismatches.

---

## 2. Mechanism B — the ESP's ECD permission (CONFIRMED)

`ECD` = **Externally Controlled Deceleration**: the ESP function that executes braking commanded by
another ECU rather than by the driver. Below ~15 km/h the ESP declares it unavailable, and the engine
withdraws ACC brake authority in response.

```
ESP_05 (0x106) bit 33  ECD_nicht_verfuegbar
   →[80106db8:131, canrx_ESP_05_106, `param_1[4] & 2`, E2E seed 0x07]→ esp05_ECD_nicht_verfuegbar (d000a4f2)
   →[801408bc:66-90, 2-cycle debounce against its own prev-cycle copy d00016f0 (stored :544-545)]
   →[801408bc:222-223]→ d000b299 (write-only) and d000b296 acc_master_request_mode
   →[8013c5d4:569 / :711 / :1043, each testing `mode == 2`]→ Ramd0007c9a (:430)
   → 8013ef46 acc_brake_setpoint_statemachine → Ramd0007cb8 → 80137a00 → TSK_02
```

`acc_master_request_mode` (`d000b296`) values:

| value | meaning |
|---|---|
| 1 | driver braking / override active |
| **0** | TSK deceleration inactive **OR** ECD unavailable (debounced) |
| 2 | ECD available **AND** TSK decel active |

The three `mode == 2` gates in `8013c5d4` and what mode ≠ 2 costs:

| line | effect |
|---|---|
| :569–575 | the enable flag `d000a582` stays 0 |
| :711–713 | the cal default `WORD_ARRAY_80043a5c[0x2d]` is used instead of the live `wRamc0001112` |
| :1043–1047 | the mode-2 alternative to the `Ramd0007c98 < iVar27` threshold is lost; flag `d00011de` |

Details worth knowing:

- **A cal selects which ECD bit is debounced.** `801408bc:66` tests `cal 0x80043cd0` bit 0
  (`WORD_ARRAY_80043ccc[2]` low byte): clear → the debounce uses `ECD_Fehler` (`d000a4f4`, prev copy
  `d00016f1`); set → it uses `ECD_nicht_verfuegbar` (`d000a4f2`, prev copy `d00016f0`). **This image has
  `0x80043cd0 = 0x01`**, so `ECD_nicht_verfuegbar` is the operative bit (CONFIRMED, firmware read).
- `d000b299` (`acc_ecd_unavail_debounced`) holds the debounced flag but is **write-only** — its only
  other reference is the zeroing in `801abe80`. The functional effect travels via `d000b296`.
- `801aa558` (`reset_control_flags`) forces `esp05_ECD_nicht_verfuegbar = 1`: the **fail-safe default is
  "ECD unavailable"**.
- `801408bc` reads **no ego-speed variable at all**. That is literally true and easy to misread: the
  speed dependence is real, it just enters from outside, because the ESP asserts
  `ECD_nicht_verfuegbar` as a function of speed at ~15 km/h. The mode byte is also mirrored into
  `d000b28c` by every CRUC handler and drives two timers in `8013ef46` (:216 / :226).

**There is no cal in this ECU that changes the ESP's mind.** The ECD decision is made in another module.

---

## 3. The other low-speed thresholds — do not conflate

| threshold | flash | raw | scale | read in | role | FR label (page) |
|---|---|---|---|---|---|---|
| **activation floor 3.0 km/h** | `0x8007a26a` (`0xa007a204+0x66`) | 384 | 1/128 km/h | `cruise_torque_pi_controller :301` | level-1 "controller may be active" / near-standstill PI branch | **`C_VS_MIN_CRU`** (p.12415) |
| **creep / accel-ctl gate 3.0 km/h** | `0x80079536` (base+0x196) | 384 | 1/128 km/h | `acc_status_error_aggregator :734` | moving-vs-standstill discriminator (`d88c` bit4) | **`C_VS_MIN_AC_CTL_CRU`** (p.12502, candidate) |
| **L2 crawl monitor 15 km/h** (×2) | `0x800794ef` / `0x800794f2` | 15 | u8 km/h (×0x80) | `acc_status_error_aggregator :1594 / :1656` | mechanism A, above | **`C_VS_MIN_CRU_MON`** (p.2196) = `C_VS_MIN_CRU_OFF − 2` (p.2351) |
| **EGAS-L2 twin 15 km/h** (×2) | `0x800456c0` / `0x800456bd` | 15 | u8 km/h | `egas_l2_monitor_cal_init 0x800a0c9c` | independent EGAS shadow-RAM monitor (`^0xff`) | `C_VS_MIN_CRU_MON` / `C_VS_MIN_DCC_MON` (p.2196) |
| hysteresis 13 km/h (×2) | `0x800456be` / `0x800456c3` | 13 | u8 km/h | monitor layer | `MON − 2` clear/hysteresis value | `C_VS_MIN_CRU_OFF` family |

### Layer-2 activation floor in code

```c
// 801e9b86:299-305   cal struct base *0x80090f94 -> 0x8007a204
if ( … && (DAT_d000d644 < *(ushort *)(base + 0x66)) ) {   // ego < C_VS_MIN_CRU
    DAT_d000e2c5 = (*(byte*)(base+0x41) < DAT_d000d62a);  // :305 near-standstill branch
}
// e2c5 == 0 is one condition that calls set_global_param_801ea218(0)  (integrator reset)
```

### Layer-3 creep discriminator in code

```c
// 80102f60:733-736
bVar23 = *(ushort *)(base + 0x196) <= ram_acc_vehicle_speed_mon;   // 3.0 km/h <= ego
UNK_d000d88c = UNK_d000d88c & 0xef | bVar23 << 4;                  // d88c bit4 = "moving >= 3 km/h"
```

No debounce. `d88c` bit4 switches several status computations between their standstill and driving
branches and is one AND-term of the (dead) fatal-deactivation path.

---

## 4. What the FR says, and the scale caveat

- **`C_VS_MIN_CRU`** (FR p.12415, VHSC basic functions): verbatim *"minimal vehicle speed for cruise
  **activation**"*, mode `V`, `0…655.35`, res 0.01 km/h, **no numeric value in the FR** — the level-1
  value lives in the dataset/DAMOS. It is an *activation floor*, not a minimum *set* speed; the sibling
  `C_VS_MAX_CRU` is *"Maximal vehicle speed for cruise activation"*. So 3.0 km/h is fully FR-consistent.
- **`C_VS_MIN_CRU_MON`** (FR p.2196, ch.14.16 ECM2 process monitoring): verbatim *"Minimum threshold for
  vehicle speed control active"*, u8, res 1 km/h; *"Derived from level-1 calibration of
  `C_VS_MIN_CRU_OFF` minus 2 km/h"* (p.2351). `VS_MON < C_VS_MIN_CRU_MON` sets the SR latch
  `LV_CRU_MON_ACT_MON` → cruise off. It is an independent L2 monitor anchored to the **turn-off** speed —
  a different quantity from the activation floor by design, so the 15-vs-3 split is expected.
- **`C_VS_MIN_AC_CTL_CRU`** (FR p.12502, Acceleration control): verbatim *"Lower limit of vehicle speed
  for acceleration control"*, res 0.01 km/h — the low-speed enable of the closed-loop acceleration
  controller that DCC/ACC drives. Best FR match for `0x80079536`.
- DCC is architected to control toward standstill (`C_VS_L_AC_DRIV_SP_CRU`, `C_VS_LIM_HLD_AC_CTL`
  auto-hold, follow-to-stop map `IP_AC_SP_MIN_DCC_FOL_2_STOP` p.12504) — but follow-to-stop is not
  compiled into this firmware (`acc_flow.md` §8).

**⚠ Operative scale beats FR metadata.** `C_VS_MIN_CRU` @ `0x8007a26a` is compared **directly** against
`DAT_d000d644`, a 1/128 km/h signal (proven by ~15 speed cals and immediates landing on integer km/h at
1/128 and on junk at 0.01). So the operative scale is **1/128 km/h → raw 384 = 3.0 km/h**, which is what
the A2L uses (edit raw = target km/h × 128). The FR lists resolution 0.01 km/h (→ 3.84) — DAMOS metadata
that does not match the in-code compare. `C_VS_MIN_AC_CTL_CRU` @ `0x80079536` is the same situation.

---

## 5. Cross-ECU: how the MED17.1.1 differs

The MED17 pack in this repo (`../../med17/maps/ecd_relay.md`) established, at instruction level and
against 8.11 h of two-car on-car data, that the **MED17 has no internal 15 km/h threshold on the
functional ACC path** — it relays `ESP_05` bit 33 and nothing else. Exhaustive sweeps there found no
15 km/h scalar in any calibration on the functional path, no 15 km/h breakpoint in any reachable curve,
and no literal `1500` compare anywhere in the image; the engine's edges lag the ESP's by a fixed
~60–90 ms and never lead.

Simos 8.5 differs: it has **both** mechanisms. Mechanism B is the same ESP_05 bit-33 relay (a much
shorter chain here — a dedicated RX decoder rather than MED17's boolean-descriptor/COM-staging path),
and mechanism A is an additional in-ECU latching monitor that MED17's functional path lacks.

One caveat when comparing: MED17 does carry an **EGAS-L2** cruise-speed monitor at 15 km/h
(`FUN_800f006c`/`FUN_800f027c`, cal #208 `0x80389809` = 15, `0x8038980e` = 7), analogous to this ECU's
EGAS-L2 twin at `0x800456c0`/`0x456bd`. Both ECUs have that L2 shadow monitor; what Simos 8.5 has and
MED17 does not is the **functional-path** 15 km/h crawl monitor of §1.

Practically, for either ECU: the lever for sub-15 km/h operation is **not** wholly in the engine. On
Simos 8.5 you would need to move `C_VS_MIN_CRU_MON` (and match the EGAS-L2 twin) *and* address the ESP's
ECD refusal; only the first half is reachable from this image. `ESP_Verzoeg_EPB_verf` (ESP_05 bit 60)
stays 1 on both sides of the floor, i.e. EPB deceleration is still advertised when ECD is not — the
MED17 doc discusses that alternative actuator path.

For an external ACC master such as openpilot, note that the hold-at-stop channel does not depend on any
of this: `ACC_01.ACC_Anhalten` → `TSK_Anhalten` is relayed whenever cruise is regulating
(`acc_flow.md` §7).

## 6. Open items

1. Which of the 13 diagnoses latches below 15 km/h, and whether a signal-only escape exists (§1).
2. Naming the relayed CAN diagnosis bits — 12 of the 13 aggregator feeders are 2-bit relayed symptoms;
   needs the ACC/brake DBC, which is external to this image.
3. `0x80079536`'s FR label: `C_VS_MIN_AC_CTL_CRU` (accel-controller enable) versus `C_VS_LIM_HLD_AC_CTL`
   (auto-hold transition). Both plausible; `d88c` bit4 reads as a general moving/standstill
   discriminator. Disambiguate by tracing every `d88c & 0x10` reader.
4. `C_VS_MIN_CRU_OFF` itself is not pinned. The FR says `MON = OFF − 2`, so with MON = 15 the OFF value
   should be ~17, but the EGAS-L2 block holds 13 (= MON − 2), i.e. `0x456be`/`0x456c3` are the
   clear/hysteresis values, not `OFF`. Low priority.
