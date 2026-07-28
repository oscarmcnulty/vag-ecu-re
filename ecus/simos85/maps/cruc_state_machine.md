# CRUC longitudinal state machine — `STATE_CRU_CTL` (d000b28e) end-to-end trace

Closes the last open item in the Simos8.5 (8R0907551F) ACC/cruise longitudinal path: the CRUC_MG005
brake-setpoint state machine that sits between the decoded ACC_01 request and the TSK_02 brake outputs.
Answers the standing question **"does the engine keep the hold/decel relay live to true standstill?"**

Built from `analysis/decompiles_r/{8013ef46,8013e8aa,8013e13c,8013e3f8,8013e674,8013e47c,8013c5d4,80137a00}.c`,
`analysis/symbols_merged.csv`, and firmware reads. Addresses: load base `0x80000000`; `0xa00xxxxx` = uncached
mirror of flash `0x800xxxxx`; file offset = `addr & 0x1FFFFFFF`. Every claim tagged CONFIRMED / INFERRED / GAP.
Supersedes nothing in `acc_flow.md`; it fills the "Open (MEDIUM)" bullet in acc_flow §7 with a definitive answer.

> **Retraction honoured:** the "7.84/7.60 km/h creep floor / dominant sub-15 barrier / firmware-patch-only"
> framing stays RETRACTED. `d0007e84` is not the ego-speed variable, and the hysteresis on it is a *high-side*
> sub-state selector (state 1↔2), not a low-speed cutoff. See §4 and the answer in §6.

---

## 0. Cast of variables (CONFIRMED addresses, from symbols_merged.csv + decompiles)

| symbol | addr | role |
|---|---|---|
| `STATE_CRU_CTL` | `d000b28e` | **published** CRUC state 0..6 — the gate `∈{1,5}` in 8013ef46:860 arms TSK_Anhalten + decel |
| internal state shadow | `d0001165` | drives the dispatch in 8013e8aa; = STATE_CRU_CTL except in the "6"/"0-confirm" transients (§3) |
| prev-state shadow | `d0001166` | last cycle's `d0001165` (handlers run only when `d0001165==d0001166`, i.e. state stable) |
| off-substate | `d0001167` | 0 = decay handler runs, 1 = outputs hard-cleared (within state 0) |
| `STATE_CRU_CTL_long_substate` | `d000b28f` | 0=off /1=controlling /2=decel-approach /3=fault; drives `TSK_Zwangszusch_ESP` (`∈{1,2}`) |
| `STATE_CRU_CTL_CAN` | `d000b28d` | 0..3 CAN status (3=Fehler) → TSK_02 byte3 (`TSK_Status_GRA_ACC_01`) |
| condition word | `uRamc0001118` | the per-cycle bit-vector 8013ef46 builds; its bits are the transition inputs (§2) |
| permission OR | `d000115f` | engage-permission byte (8013ef46:231-262) → c1118 bit0 |
| inhibit OR | `d0001160` | inhibit byte (8013ef46:294-324) → c1118 bit1 |
| secondary cond | `d000b291` | (8013ef46:382-443) → c1118 bit2 (drives 1→5) |
| launch latch | `d000118a` | 7.81 km/h launch latch — **1 of 2 ego-speed terms** (other = 2.34 km/h creep flag `d0001171`); both sub-flags only, see §4 |
| `acc01_ACC_Anhalten` | `d000a7ae` | ACC_01 (0x109) byte7·bit1 stop/hold input |
| `acc01_ACC_Sollbeschleunigung` | `d0007bac` | ACC_01 24|11 accel setpoint (0.005 m/s²) |
| request | `Ramd0007c9a` | clamped brake request out of 8013c5d4 (carries the −3.0 cap) |
| staged decel | `Ramd0007cae` | state-machine decel setpoint (per-state, §5) |
| output decel | `Ramd0007cb8` | = `AC_SP_CRU_BRAKE_CTL` → TSK_Verzoeg_Anf packer |
| `tsk02_TSK_Anhalten_src` | `d000a58d` | hold bit → TSK_02 byte2·bit4 |
| `tsk02_TSK_Freig_Verzoeg_Anf_src` | `d000a58c` | decel-ENABLE → TSK_02 byte7·bit7 |
| `tsk02_TSK_Zwangszusch_ESP_src` | `d000a58f` | forced-ESP-coupling → TSK_02 byte7·bit6 |
| `LV_DCC_ENA` | `d000a757` | Basic-ACC coded (cell 27); required to forward the hold |
| `acc_master_compute_enable` | `d000ad0f` | master gate; 8013ef46 early-returns if 0 |
| `acc_mode_ACC05_Momentenanf_sel` | `d000a5a8` | `=0x43caf&1` cal-fixed **0** on the Q5 (selects the ACC_01/TSK_02 hold branch) |

Master-request bytes feeding the machine (produced by `801408bc`, the stalk/master-ACC state machine —
CONFIRMED it contains **zero ego-speed reads**):
`d000b296` (mode), `d000b297`, `d000b298` (`==4`→state 4, `==3`→fault), `d000b295`.

---

## 1. Where the machine sits in the chain (CONFIRMED)

```
ACC_01 0x109 ─801383e8─▶ d0007bac (accel), d000a7ae (Anhalten), d000b06a (Dynamik)
                               │
801408bc (stalk/master) ─▶ d000b296/97/98  (mode/fault/override — NO speed term)
                               │
   8013c5d4  acc_brake_request_formation ──▶ Ramd0007c9a   (request, −3.0 cap folded in here)
                               │
   8013ef46  acc_brake_setpoint_statemachine (top)
     ├─ builds condition word uRamc0001118  (bits = transition inputs)
     ├─ calls 8013e8aa  ── writes STATE_CRU_CTL (d000b28e) 0..6  + dispatches per-state handler:
     │        state0→8013e13c  state1→8013e47c  state2/3→8013e674  state5→8013e3f8
     │        (each sets Ramd0007cae = the staged decel/torque setpoint)
     └─ OUTPUT gate (8013ef46:855-976): if STATE_CRU_CTL∈{1,5} (bVar4) →
              tsk02_TSK_Anhalten_src = acc01_ACC_Anhalten   (and LV_DCC_ENA)
              Ramd0007cb8 = Ramd0007cae   (else 0x8000 = 0 decel)
                               │
   80137a00  TSK_02 packer ──▶ 0x10C  byte2.4 Anhalten, byte7.7 Freig, byte8 Verzoeg_Anf
```

---

## 2. `STATE_CRU_CTL` states 0..6 — meaning + handler (CONFIRMED)

| state | meaning | `b28f` substate | `CAN` | per-state handler (runs when state stable) | `Ramd0007cae` set to | in {1,5}? |
|---|---|---|---|---|---|---|
| **0** | OFF / standby | 0 | 0 | `8013e13c` (decay/ramp of stored setpoints) when `d1167==0`; hard-clear when `d1167==1` | `0x8000` (0) | no |
| **1** | **REGULATING** (primary, torque+brake) | 1 | 1 | `8013e47c` (`acc_dynamik_torque_switch`, INERT dynamik) | `= Ramd0007c9a` (the −3.0-capped request) | **YES** |
| **2** | active, **high-`d0007e84` sub-regime / decel ramp** | 2 | (from b292) | `8013e674` (active decel ramp `cae = −1−uRamc0001134`; also drives the Anhalten-permission `d0001188`) | ramped `−1−uRamc0001134` | no |
| **3** | FAULT (`Fehler_GRA_ACC`) | 3 | 3 | none (outputs neutral) | `0x8000` | no |
| **4** | driver OVERRIDE / special mode (`b298==4`) | (0) | 0 | none (outputs cleared) | `0x8000` | no |
| **5** | **REGULATING** (brake-only; torque parked) | 1 | (1) | `8013e3f8` (`cae = Ramd0007c9a`, `caa=0x8000` torque-neutral) | `= Ramd0007c9a` | **YES** |
| **6** | RAMP-DOWN / functional-off transient (published only; internal shadow still 1) | 0 | 0 | (re-evaluates state-1 logic next cycle) | held/blend | no |

Notes (CONFIRMED):
- States **1 and 5 are the only regulating states** and the **only ones the output gate arms** (8013ef46:859-862
  `bVar4 = STATE_CRU_CTL==1 || ==5`). State 1 = full longitudinal control; state 5 = "brake-only" (the torque
  request `Ramd0007caa` is parked at neutral `0x8000` while the decel request stays live) — entered from 1 when
  the secondary-condition bit `c1118 bit2` (`d000b291`) sets.
- **State 2 is a *higher*-regime split of state 1**, not a lower one (see §4). Its handler `8013e674` runs an
  active decel ramp and sets `d0001188` (which can keep the decel-ENABLE latched even outside {1,5}).
- **State 6** is subtle: 8013e8aa writes `STATE_CRU_CTL=6` but does **not** update the internal shadow
  `d0001165` (it stays at 1), so the next cycle re-runs the state-1 transition logic. State 6 is therefore a
  *published* brake-blend-out transient; if permissions return it re-publishes state 1. (CONFIRMED, 8013e8aa:271-302.)

---

## 3. Transition conditions (CONFIRMED — from 8013e8aa dispatch on the internal shadow `d0001165`)

The transition inputs are bits of `uRamc0001118` (low byte `c1118`, high byte `c1119`), built each cycle in
8013ef46. Bit meanings (CONFIRMED, 8013ef46 line refs):

| bit | set condition | drives |
|---|---|---|
| `c1118 0x01` (bit0) | **all engage-permissions present**: `d000115f == cal(0x8004341f lo=0xFF) && d000115f!=0` (692-697) | must be **1** to enter/stay {1,2,5} |
| `c1118 0x02` (bit1) | **inhibit present**: `d0001160 != 0` (`= inhibit-OR & cal(0x80043422 lo=0xEF)`) (698-704) | must be **0** to stay regulating; set → 6 / 0 |
| `c1118 0x04` (bit2) | `d000b291 != 0` (secondary-condition OR) (705-712) | 1 → **5** |
| `c1118 0x08` (bit3) | `d000a59c!=0 || d000b298==3` (fault/override) (731-737) | any → **3** |
| `c1118 0x40` (bit6) | **`d0007e84` HIGH** (above cal `0x800439f8`=1004, or `bVar4`); CLEAR when low (751-765) | 1 → **2** |
| `c1118 0x80` (bit7) | `d0007e84` hysteresis vs cal `0x800439fa`=973 + kennlinie (811-826) | in state 2: 1 → back to **1** |
| `c1119 0x01` | high-byte permission mirror | blocks entry to 1 |
| `c1119 0x02` | high-byte cond | in state 5: → **0** |

### Transition table

**From 0 (OFF):**
- `c1118 bit4` or `bit3` set → **3** (fault; also latches `a586=a599`).
- `b298==4` → **4**.
- **ENTER 1** iff: `bit0 set` ∧ `bit1 clear` ∧ `bit2 clear` ∧ `(c1119&1)==0` ∧ `a587!=0` ∧ `(d1173==0 ∨ cal43ccc[0xb]&1)`. (8013e8aa:33-52)
- else stay 0 (latches `d1167=1` to confirm-off when `a588!=0`).

**From 1 (REGULATING):** (8013e8aa:217-302)
- `c1118 bit3` → **3**  ·  `b298==4` → **4**
- `bit0`∧`!bit1`∧`!bit2`∧`bit6` → **2**
- `bit0`∧`!bit1`∧`bit2` → **5**
- `bit0`∧`!bit1`∧`!bit2`∧`!bit6` → **stay 1**
- **`!bit0` (permission lost) ∨ `bit1` (inhibit)** → **6** (blend-out; `d1188=1`, CAN=0)

**From 2:** (8013e8aa:125-171)
- `c1118 bit3` → **3**  ·  `b298==4` → **4**
- `!bit0 ∨ bit1` → **6**  ·  `bit2` → **5**  ·  `bit7` → back to **1**  · else stay 2

**From 4:** `c1118 bit5`→ housekeep `a589=1` (stay 4); `bit3`→ **3**; else sticky 4 (exits on fault or on the
8013ef46 master reset). (8013e8aa:172-179)

**From 5 (REGULATING):** (8013e8aa:180-215)
- `c1118 bit3` → **3**  ·  `b298==4` → **4**
- **`!bit0 ∨ bit1 ∨ (c1119&2)`** → **0**  · else stay 5

**From 3 / 6:** no transition arithmetic in 8013e8aa (fall-through). Recovery is via the **master reset** at the
top of 8013ef46 (48-105: `acc_master_compute_enable==0` or coding lost → force `STATE_CRU_CTL = 0` or `3`), and —
for state 6 — via the internal-shadow quirk that re-runs state-1 logic (§2).

**Master reset (8013ef46:48-105, CONFIRMED):** if `acc_master_compute_enable==0` → early return (state frozen).
If not ACC/GRA-coded (or ACC_05-mode selected) → clear everything, `STATE_CRU_CTL = 3` if `d000aab5 && cal43ccc[0x59].hi`
else `0`; `d000118a` (launch latch) re-armed to **1**.

---

## 4. The ego-speed content of the machine — TWO terms, both sub-flags (CONFIRMED; corrected)

A full grep of the CRUC machine (`8013ef46` + `8013e8aa` + all four sub-handlers) for **every** ego-speed
variable (`Ramd0005618` raw, **`Ramd0007ce8` filtered**, `d000d644`, `d000da54`) plus the 15 km/h-monitor
outputs (`d000d8ab`, `d000d79a`, `d000d88c`, `d000d8ee`, `d000d8ce`) returns **two ego-speed terms** (an earlier
version of this doc said "exactly one" — it missed the filtered-speed term because it did not grep
`Ramd0007ce8`). **Neither exits `STATE_CRU_CTL` from {1,5}; both only set sub-flags inside the regulating state**,
which is why the engaged-to-0 conclusion below is unchanged (and in fact reinforced):

```c
// TERM 1 — 8013ef46:263-265 (raw speed, 7.81 km/h launch latch)
uVar9 = Ramd0005618;                 // vehicle-speed class (1/128 km/h)
if (1000 < uVar9) UNK_d000118a = 0;  // clear the launch latch above ~7.81 km/h

// TERM 2 — 8013ef46:156 (filtered speed, 2.34 km/h creep flag)
if (... (Ramd0007ce8 < WORD_ARRAY_80043c5c[0xe] /* =0x80043c78 = 300 = 2.34 km/h */) ...) d0001171 = 1;
```
**Term 2 (2.34 km/h):** `d0001171` → in `8013e8aa` (state-1 entry, :57/:148) sets the sub-flag `d0001187`
(`= 1` iff `d0001171==0`, i.e. speed ≥ 2.34), which only modifies the **state-1 torque/setpoint** computation
(`iVar7`/`d0001186`, read by the state-1 handler `8013e47c`) — it does **not** assign `STATE_CRU_CTL`. So the
2.34 km/h term is a within-regulating creep sub-behaviour, not a disengage. (CONFIRMED by reading `8013e8aa:48-90`.)

**Term 1 (7.81 km/h):**

`d000118a` is a **one-way launch latch**: set to **1** at every master reset (8013ef46:103), cleared to 0 the
first time speed exceeds `1000` (≈7.8125 km/h at 1/128). It **never re-arms as speed falls.** So at any low speed
*after* the car has been moving, `d000118a = 0`. Its only consumer inside the machine is the inhibit-word term
`(bVar4 && d000118a==0)` (8013ef46:304), where `bVar4` is a debounce timer on the ESP/brake flag `d000b1c7`. With
`d000118a==0` being the normal post-launch condition, that term reduces to "`bVar4` (an ESP/brake-debounced
inhibit)". **`d000118a` therefore functions as a launch-enable (suppresses an inhibit during initial
acceleration), not a stop-floor.** (CONFIRMED — matches the retraction: the `1000` literal is a launch latch,
not a decel/hold gate.)

The `d0007e84` hysteresis (cals `0x800439f8`=1004, `0x800439fa`=973 — read below) drives `c1118` bits 6/7, which
select **state 1 ↔ state 2**. Bit6 is SET when `d0007e84` is **high** → moves 1→2; CLEARED when low → stays in 1.
So as the car slows toward 0, `d0007e84` falls, bit6 clears, and the machine **stays in state 1** — it does not
get pushed out of the regulating set by falling speed. `d0007e84`'s physical scale is unverified (source
`Ramd0007e86`, an ACC-internal value, **not** the 1/128-km/h ego speed), so no km/h label is asserted here.

Cal reads (CONFIRMED, firmware):
`0x800439f8 = 1004`, `0x800439fa = 973`, `0x800439f4 = 51`, `0x800439f6 = 31`;
permission mask `0x8004341f` (8004327a[0xd3].lo) `= 0xFF`, inhibit mask `0x80043422` (8004327a[0xd4]) `= 0xFFEF`;
decel-limit cells `0x5b71c/1e/20/28/2a` all `= 0x7237` (−3.000 m/s², flat — confirms the speed-independent −3.0 cap).

---

## 5. ACC_01 → request → state → decel setpoint (CONFIRMED)

- **ACC_01 (0x109) decode** `801383e8`: E2E seed 0x08 OK → `d0007bac`=Sollbeschleunigung(24|11, 0.005 m/s²),
  `d000a7ae`=ACC_Anhalten(byte7·bit1), `d000b06a`=ACC_Dynamik.
- **Request formation** `8013c5d4`: builds `Ramd0007c9a` from the accel via the decel-limit kennlinie
  (`0xa005b71c`/`0xa005b728`, all `0x7237`) → `max(request, 0x7237)` = **truncate braking to −3.0** (acc_flow §2,
  unchanged). `8013c5d4` also reads `STATE_CRU_CTL` in several places (e.g. :120, :626, :684, :717, :736, :924,
  :1151 `d00011c9 = STATE_CRU_CTL`) — it shapes the request differently in state 1 vs 5 vs other, but the
  **decel authority itself is set by the flat kennlinie, state-independently.**
- **Into the machine:** `Ramd0007c9a` is copied to the staged decel `Ramd0007cae` inside the per-state handlers:
  - state 1 (`8013e47c`) and state 5 (`8013e3f8`): `Ramd0007cae = Ramd0007c9a` (full request passes).
  - state 2 (`8013e674`): `Ramd0007cae = −1 − uRamc0001134` (an internally-ramped decel, not the raw request).
  - state 0 (`8013e13c`): `Ramd0007cae = Ramd0007cac` (decayed).
  - states 3/4/6: `Ramd0007cae = 0x8000` (0) via the 8013e8aa clear paths.
- **ACC_Dynamik** (`8013e47c`) selects a torque-rate cal but is **INERT** (all four cals = 500) — no effect.
- **The state transitions themselves do NOT read the accel value**; they are driven by the permission/inhibit
  bits (driver/stalk/coding/ESP), the fault flags, and `b296/98`. The accel only sets the *magnitude* of the
  decel once a regulating state is entered. (CONFIRMED.)

---

## 6. ★ THE ANSWER: does `STATE_CRU_CTL` leave {1,5} as speed → 0?

**Definitive (CONFIRMED, within the CRUC machine + its direct producer):
NO — there is no ego-speed transition that drops `STATE_CRU_CTL` out of {1,5} as the vehicle decelerates toward 0.**

Every exit from the regulating set {1,5} is governed by (§3):
1. **Fault** — `c1118 bit3` = `d000a59c!=0 || d000b298==3` → state 3.
2. **Permission lost** — `c1118 bit0` clears (`d000115f` ≠ full mask) → state 6 (from 1/2) or 0 (from 5).
3. **Inhibit** — `c1118 bit1` set (`d0001160 != 0`, an ESP/brake/driver-override OR) → state 6 / 0.
4. **Override** — `b298==4` → state 4.
5. **Sub-state split** — `bit2`→5, `bit6`→2 (both *lateral*, and bit6 is a **high**-side move).

None of (1)-(5) is a function of low ego speed:
- The machine contains **two ego-speed terms, both of which only set sub-flags inside {1,5}** (neither assigns
  `STATE_CRU_CTL`): (a) the 7.81 km/h **one-way launch latch** `d000118a` (8013ef46:263) that de-asserts as speed
  *rises* and never re-arms on the way down; (b) the 2.34 km/h **creep flag** `d0001171` (8013ef46:156) that only
  tweaks the state-1 torque via `d0001187`/`d0001186`. Neither can force a low-speed exit (§4).
- The `d0007e84` hysteresis is a **high-side** selector (1→2), so falling speed keeps the machine **in** state 1.
- The master-request producer **`801408bc` reads no ego-speed variable at all** (CONFIRMED grep), so `b296/98`
  cannot introduce a hidden speed floor either.
- The 15 km/h L2 monitor (`80102f60`) and its outputs (`d8ab/d79a/d88c`) are **not read anywhere in the CRUC
  machine** (CONFIRMED grep) — they feed status/diagnosis (acc_flow §3/§5), and the deactivation path is dead
  (fatal mask = 0), so the monitor does not fault the state machine.

**Consequence:** with ACC engaged and no fault / driver-override / ESP-brake intervention, `STATE_CRU_CTL` **stays
in {1,5} down to 0 km/h**, so the output gate stays armed and the hold-relay (`TSK_Anhalten`) and the decel-relay
(`Ramd0007cb8 = Ramd0007cae`, the −3.0-capped request) **remain live to true standstill.** This settles the last
item: **the Simos does brake to true standstill via the ACC_01.ACC_Anhalten → TSK_Anhalten channel**, exactly as
`acc_flow.md` §6 describes for openpilot — the sub-15 km/h creep/sub-state flags shape only the *magnitude/blend*,
not the engaged state.

**Residual bound (GAP, LOW):** the permission/inhibit *inputs* to 8013ef46 — `a587`, `a593/594`, `a5a2`, the
`d000b1c7` ESP flag, `a335`, the `0x80086b00/b50/bc0` pedal switches, and the ESP-feedback bits — are computed in
functions outside the CRUC chain and were not each traced to their root. I verified none is read from ego speed
*within* the CRUC machine or its direct producer `801408bc`; but an upstream input that is *itself* speed- or
standstill-correlated (e.g. an ESP standstill/autohold flag, or a driver brake tap at the stop) could set an
inhibit and move {1,5}→6/0 near 0 km/h. That would be an ESP/driver-domain handoff, **not** a speed floor in the
engine's cruise code — and it does not affect the openpilot relay path, which owns the stop decision via
`ACC_01.ACC_Anhalten` regardless.

---

## 7. State + request → TSK outputs (CONFIRMED)

Output stage in `8013ef46:855-976`, gated by the branch condition
`(ACC05-mode==0 && LV_DCC_ENA) || (GRA-coded && a572)`; inside it `bVar4 = STATE_CRU_CTL∈{1,5}`:

| TSK signal | src var | rule (8013ef46) | packer |
|---|---|---|---|
| **TSK_Anhalten** (hold) | `d000a58d` | `= acc01_ACC_Anhalten` iff `bVar4 (∈{1,5}) && LV_DCC_ENA`; else 0 (:944-950) | `80137a00` byte2·bit4 |
| **TSK_Verzoeg_Anf** (decel) | `Ramd0007cb8` | `= Ramd0007cae` iff `TSK_Freig_Verzoeg_Anf_src≠0`; else `0x8000`=0 (:951-963) | `80137a00` byte8, 0.024 m/s², clamp `[0x6db1,0x89b6]` |
| **TSK_Freig_Verzoeg_Anf** (decel ENABLE) | `d000a58c` | `= (a57c==0 && bVar3 && sRamc113c≤cal) ‖ d0001181`, where `bVar3 = bVar4 ‖ d0001188` (:864-943) | `80137a00` byte7·bit7 |
| **TSK_Zwangszusch_ESP** (forced ESP coupling) | `d000a58f` | `= (STATE_CRU_CTL_long_substate ∈ {1,2})` (:970-976) | `80137a00` byte7·bit6 |
| **TSK_Status_GRA_ACC_01** | `d000b28d` (`STATE_CRU_CTL_CAN`) | 0..3 from 8013e8aa (3=Fehler in state 3) | `80137a00` byte3·bits1-0 |
| **TSK_Codierung_ACC** | `d000a79f` | coding constant | `80137a00` byte7·bit5 |
| **TSK_Status_GRA_ACC_02** | `d000d9c7` (`STATE_DCC`) | via `801e3f26` | `8011e9ce`/`801e3f26` → TSK_04 (0x10E) byte8·bits7-6 |
| **TSK_amax_moeglich** | — | max achievable accel (no decel) | TSK_01 (0x10A) byte8 |

Key nuance (CONFIRMED): the **hold** (`TSK_Anhalten`) is gated *strictly* by `STATE_CRU_CTL∈{1,5}`. The **decel**
enable is slightly looser — `bVar3 = bVar4 || d0001188` — so `d0001188` (set in states 2/6/0 handlers) lets the
decel ramp **blend out** for a few cycles after leaving {1,5}, but a *new* decel request requires {1,5}. The
packer (`80137a00`) additionally zeroes both if `d000ad7a==0` (TSK not active) or forces decel→`0xA6`(=0)/Anhalten→0
if `d000a852!=0`. Neither `ad7a` nor `a852` is speed-derived.

---

## 8. Suggested edit to an existing doc (not applied here)

`acc_flow.md` §6 and §7 leave the engaged-to-0 question "Open (MEDIUM)". That bullet can now be closed with the
§6 result above: **CONFIRMED engaged to 0 km/h within the CRUC machine; no speed-floor transition exists; the only
speed term is a one-way launch latch.** The retracted "7.84/7.60 creep floor" wording stays retracted and is
further substantiated here (`d0007e84` bit6 is a high-side 1→2 selector). No firmware or existing repo files were
modified.
