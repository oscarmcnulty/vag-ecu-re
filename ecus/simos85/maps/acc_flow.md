# ACC longitudinal path: CAN ingress → CRUC state machine → TSK egress

The engine ECU's ACC/cruise (FR: VHSC / DCC) longitudinal path end to end — from the received
ACC request to the deceleration, hold and status sent to the brake (ESP). This is the single
flow document for that path; the two topics with their own depth live next door:

- **the −3.0 m/s² decel authority** (functional clamp + L2 plausibility monitor) → `decel_limit_flow.md`
- **the sub-15 km/h floors** (internal latching monitor + external ECD gate) → `low_speed_floors.md`
- **cal edit addresses**, all topics, one table → `edit_targets.md`

Addresses are load base `0x80000000`; `0xa00xxxxx` = uncached mirror of flash `0x800xxxxx`;
file offset = `addr & 0x1FFFFFFF`. Claims are tagged **CONFIRMED** (read out of the decompiles or
the binary) / **INFERRED** / **GAP**. Function and variable names are those in
`../analysis/symbols_merged.csv`.

## Spine

```
ACC_01 (0x109) ──801383e8──▶ d0007bac (accel), d000a7ae (ACC_Anhalten), d000b06a (Dynamik)
   (RX poll 80108cc4, mailbox handle 0x240, E2E seed 0x08 + rolling counter validated)

ESP_05 (0x106) ──80106db8──▶ esp05_* feedback cluster incl. ECD_nicht_verfuegbar (d000a4f2)
        │                                            │
        │                              801408bc  acc_master_request_producer
        │                                    └─▶ d000b296 acc_master_request_mode (0/1/2)
        ▼                                            │
   8013c5d4  acc_brake_request_formation  ◀───────────┘  (three `mode == 2` gates)
        │      + flat −3.0 decel-limit Kennlinie
        ▼
   Ramd0007c9a  (clamped brake request)
        │
   8013ef46  acc_brake_setpoint_statemachine  ── dispatch ──▶ 8013e8aa (states 0..6)
        │      per-state handlers 8013e13c / e47c / e674 / e3f8 set Ramd0007cae
        │      OUTPUT gate: STATE_CRU_CTL (d000b28e) ∈ {1,5} → arm TSK_Anhalten + decel
        ▼
   Ramd0007cb8  (= FR AC_SP_CRU_BRAKE_CTL)
        │
   80137a00  TSK_02 packer  (TX scheduler 80106ed8:747, cal 0x43caf&1 = 0, HW mailbox 0x680)
        ▼
   TSK_02 (0x10C): byte8 = TSK_Verzoeg_Anf (decel), byte2·bit4 = TSK_Anhalten (hold)
        ▼   → central gateway J533 (separate ECU) → chassis bus → ESP
```

**Frame selection is CAL-fixed, not VCDS coding** (CONFIRMED): `DAT_80043bc6` = `0x0900` (no writers)
selects **ACC_01 active / ACC_05 disabled = the Q5 configuration**; a Macan cal sets the ACC_05 bits.
The companion mode word `DAT_80043caf` = `0x06`, so `d000a5a8 = caf & 1 = 0` → the ACC_01 + TSK_02
packer + hold-relay branch. On the Q5 the live accel command is therefore
`d0007bac = ACC_01.ACC_Sollbeschleunigung`; `d0007baa` (ACC_05 `ACC_Momentenanforderung`) stays ≈0.

## Encoding conventions

Getting these wrong is what hid the −3.0 clamp for a long time — the internal setpoint domain is
**offset-binary**, not two's complement.

| domain | encoding | 0 m/s² | −3.0 | −3.984 | +2.112 |
|---|---|---|---|---|---|
| internal accel setpoint (`d0007cxx`, Kennfeld cells) | u16, 850e-6 m/s² **offset-binary**, `phys = (raw−0x8000)·850e-6` | 0x8000 | **0x7237** | 0x6db1 | 0x89b6 |
| `TSK_Verzoeg_Anf` CAN byte | u8, res 0.024 m/s² | 0xA6 | 0x29 | 0x00 | 0xFE |
| ego speed (`d000d644`, `d000da54`) | u16, **1/128 km/h** (128 counts = 1 km/h) | — | — | — | — |
| `C_VS_MIN_*` cals | u8 km/h, compared `da54 ≤ cal·0x80` | — | — | — | — |
| ACC engine-torque decel (`0x80079982`) | s16, 0.005 m/s² | — | — | — | — |
| L2 plausibility monitor (`0x8004351x` cals) | s16, 0.001 m/s² | — | −3000 | — | +2000 |

The accel→torque *converter* is table-driven through the runtime C-RAM Com context and is not
statically bindable — resolve it on the bench, not in the image (`can_signal_map.md`).

---

## 1. Ingress — the three ACC-longitudinal RX decoders (CONFIRMED)

The mailbox handler `canmo_109_ACC_01` (`0x8011e8f8`) only **stages** the raw 8 bytes of 0x109 into
`d000d40a` and sets flag `d000d408`. The actual decode happens in the RX poll loop `80108cc4`, which
drives three dedicated decoders. Each is identified by the MLB E2E seed it checks — `seed = (id>>8) ^
(id&0xff)` — plus a bit-for-bit match against the opendbc layout, and each **discards** frames whose
XOR-of-8-bytes or rolling counter (byte1 low nibble) is wrong.

| handle | decoder | seed | frame | writes |
|---|---|---|---|---|
| 0x240 | `801383e8` | 0x08 | **ACC_01 / DCC_1, 0x109** (Gateway_B8) | `d0007bac ← ACC_Sollbeschleunigung` (24\|11, 0.005 m/s²), `d000a7ae ← ACC_Anhalten` (bit 57), `d000b06a ← ACC_Dynamik` (58) |
| 0x8a0 | `801383fc` | 0x0C | **ACC_05 / DCC_5, 0x10D** (Gateway_D4C7) | `d0007baa ← ACC_Momentenanforderung` (16\|10, a *torque* request 0–1021, `min(cal_b0d4·raw·16, 0x7fff)`), `a3ba ← ACC_Betaetigung_EPB`, `b057 ← ACC_Status_ACC`, `b056 ← ACC_StartStopp_Info` |
| 0x600 | `80106db8` | 0x07 | **ESP_05 / TCS5, 0x106** — an ESP→engine **feedback** frame | the `esp05_*` cluster: `ESP_Bremsdruck` (d0007c3e), `ESP_Verz_TSK_aktiv` (a4eb), `ESP_Konsistenz_TSK` (a4f5), `ESP_Fahrer_bremst` (a4e7), `ESP_Autohold_Standby/_aktiv` (a4e4/a4e9), `ESP_Status_Bremsdruck` (a4f1), **`ECD_nicht_verfuegbar` (a4f2)**, `ECD_Fehler` (a4f4), `ESP_StartStopp_Info` (b1ec) |

So the engine↔ESP brake loop is **closed**: the engine sends decel + hold on TSK_02 and reads the ESP's
reaction and permissions back on ESP_05. The `d000a4e4…a4f6` block is ESP status feedback, not an
"ACC enable/override" cluster.

ACC_05 is decoded but gated on message-present (`d0006980 & 0x20000000`) and is not seen on the stock
B8 bus (memory `vw-mlb-checksums`), so it is dormant on this car. The hold path is unaffected —
`ACC_Anhalten` is unambiguously ACC_01/0x109 byte7·bit1, triple-confirmed by the firmware seed, the FR
(`LCAN_DCC1_8_1 → LV_CAN_VEH_STOP_REQ_DCC`) and opendbc (`ACC_Anhalten:57|1`). The gateway re-signs the
frame *as* ACC_01 (seed 0x08), so the validated buffer is ACC_01's on-wire layout byte-for-byte.

`801dec08` is **not** an ACC input decoder — it writes the `d5c0–d6ff` mirror block from internal engine
state (`d000d606` = engine output mirror, `d000d644` = ego speed derived from `d5618`).

## 2. The ESP's ECD permission → `acc_master_request_mode` (CONFIRMED)

`801408bc` (`acc_master_request_producer`, the stalk/master-ACC state machine) is the ESP_05 consumer.
It debounces the ESP's ECD declaration over two cycles against its own previous-cycle copy and folds the
result into the mode byte that the brake-request formation reads:

```c
// 801408bc:66-90 — cal 0x80043cd0 (= WORD_ARRAY_80043ccc[2] low byte) selects WHICH ECD bit is used
if ((cal_0x80043cd0 & 1) == 0)  bVar23 = esp05_ECD_Fehler          && d00016f1;  // prev-cycle copy
else                            bVar23 = esp05_ECD_nicht_verfuegbar && d00016f0;  // prev-cycle copy
if (driver braking / override)            uVar22 = 1;
else if (!esp05_ESP_Verz_TSK_aktiv || bVar23) uVar22 = 0;   // TSK decel inactive OR ECD unavailable
else                                       uVar22 = 2;      // ECD available AND TSK decel active
d000b299 = bVar23;   d000b296 = uVar22;                     // :222-223
// :544-547 tail: d00016f0 = esp05_ECD_nicht_verfuegbar;  d00016f1 = esp05_ECD_Fehler
```

- **`cal 0x80043cd0 = 0x01` in this image** (CONFIRMED, firmware read), so the **`ECD_nicht_verfuegbar`
  branch is the operative one**; the `ECD_Fehler` variant is the alternative calibration.
- `d000b299` (`acc_ecd_unavail_debounced`) is **write-only** — its only other reference is the zeroing in
  `801abe80`. The functional effect travels via `d000b296`, not via this byte.
- `801aa558` (`reset_control_flags`) forces `esp05_ECD_nicht_verfuegbar = 1` — the fail-safe default is
  "ECD unavailable".
- `801408bc` reads **no ego-speed variable** (CONFIRMED grep). The speed dependence is real but external:
  the ESP asserts `ECD_nicht_verfuegbar` as a function of speed at ~15 km/h. See `low_speed_floors.md`.

## 3. Request formation — `8013c5d4` (`acc_brake_request_formation`) (CONFIRMED)

Builds `Ramd0007c9a`, the clamped brake request, from the decoded accel. The **−3.0 m/s² saturation and
its cal cells are documented in `decel_limit_flow.md`** and are not repeated here.

Engage gates checked in this function:

| gate | variable | meaning |
|---|---|---|
| master compute-enable | `d000ad0f` (from `8011ac80`) | ACC computing at all |
| CRUC state | `d000b28e ∈ {1,5}` | actively regulating (read at :444, :740, :766, :859, :923, :1447 among others) |
| **ECD/master-request mode** | `d000b296 == 2` | ESP grants externally-controlled deceleration |
| driver-override selector | `d000b29c == 0` | from driver-request flags `a73x` via `80141248` |
| ESP feedback | the `esp05_*` bits | e.g. `ESP_Status_Bremsdruck` at :711 |

The three `d000b296 == 2` sites are where an ESP ECD refusal removes brake-request authority:

| line | effect when mode ≠ 2 |
|---|---|
| :569-575 | enable flag `d000a582` stays 0 |
| :711–713 | falls back to the cal default `WORD_ARRAY_80043a5c[0x2d]` instead of the live `wRamc0001112` |
| :1043–1047 | loses the alternative to the `Ramd0007c98 < iVar27` threshold; flag `d00011de` |

Two cruise-mode variants exist, selected at `8013c5d4:221-231` by `d000a757` (`LV_DCC_ENA`, long-coding cell 27): `a757 = 0` →
GRA curve, `a757 = 1` → Basic-ACC curve. Both feed the same clamp path.

## 4. CRUC state machine — `STATE_CRU_CTL` (`d000b28e`), 8013ef46 + 8013e8aa

`8013ef46` builds a per-cycle condition word and calls `8013e8aa`, which writes `STATE_CRU_CTL` and
dispatches the per-state handler; `8013ef46` then applies the output gate.

### 4.1 States (CONFIRMED)

| state | meaning | `b28f` substate | CAN status | handler | `Ramd0007cae` ← | regulating? |
|---|---|---|---|---|---|---|
| **0** | OFF / standby | 0 | 0 | `8013e13c` decay/ramp when `d1167==0`; hard-clear when `d1167==1` | `0x8000` (0) | no |
| **1** | **REGULATING** — torque + brake | 1 | 1 | `8013e47c` (`acc_dynamik_torque_switch`) | `Ramd0007c9a` | **yes** |
| **2** | high-`d0007e84` sub-regime / decel ramp | 2 | (from b292) | `8013e674` (ramp; also sets `d0001188`) | `−1 − uRamc0001134` | no |
| **3** | FAULT (`Fehler_GRA_ACC`) | 3 | 3 | none | `0x8000` | no |
| **4** | driver OVERRIDE / special mode | (0) | 0 | none | `0x8000` | no |
| **5** | **REGULATING** — brake-only, torque parked | 1 | (1) | `8013e3f8` (`caa = 0x8000`) | `Ramd0007c9a` | **yes** |
| **6** | ramp-down / functional-off transient | 0 | 0 | (re-runs state-1 logic next cycle) | held/blend | no |

- **1 and 5 are the only regulating states and the only ones the output gate arms** (`8013ef46:859-862`).
  State 5 is entered from 1 when the secondary-condition bit sets: the decel stays live while the torque
  request `Ramd0007caa` parks at neutral `0x8000`.
- **State 2 is a *higher*-regime split of state 1, not a lower one** (§4.3).
- **State 6** publishes 6 but does not update the internal shadow `d0001165` (it stays 1), so the next
  cycle re-runs the state-1 transition logic — a published brake-blend-out transient that re-publishes
  state 1 if permissions return (`8013e8aa:271-302`).
- Every CRUC handler mirrors `d000b296` into `d000b28c`, so the ESP's ECD verdict is also republished
  from inside the state machine; `8013ef46` additionally uses `b296 == 1` (:107, driver braking) and
  `b296 == 2` (:216/:226) to drive two internal timers.

State bookkeeping variables: internal shadow `d0001165`, previous-cycle shadow `d0001166` (handlers run
only when the state is stable, `d1165 == d1166`), off-substate `d0001167`, long substate
`d000b28f` (0 off / 1 controlling / 2 decel-approach / 3 fault — drives `TSK_Zwangszusch_ESP` when ∈{1,2}),
CAN status `d000b28d`.

### 4.2 Transitions (CONFIRMED, `8013e8aa` dispatching on `d0001165`)

Inputs are bits of the condition word `uRamc0001118` built each cycle in `8013ef46`:

| bit | set condition (8013ef46 lines) | drives |
|---|---|---|
| `0x01` | all engage-permissions present: `d000115f != 0 && d000115f == mask` (692-697), where `d000115f = permission-OR & mask` (:262) and the mask is the **high** byte of `WORD_ARRAY_8004327a[0xd3]`, i.e. cal **`0x80043421 = 0x1B`** | must be 1 to enter/stay {1,2,5} |
| `0x02` | inhibit present: `d0001160 != 0`, where `d0001160 = inhibit-OR & cal 0x80043422 = 0xEF` (:324, 698-704) | must be 0 to stay regulating |
| `0x04` | `d000b291 != 0` (secondary-condition OR) (705-712) | 1 → **5** |
| `0x08` | `d000a59c != 0 \|\| d000b298 == 3` (fault/override) (731-737) | → **3** |
| `0x40` | `d0007e84` **high** (above cal `0x800439f8` = 1004) (751-765) | 1 → **2** |
| `0x80` | `d0007e84` hysteresis vs cal `0x800439fa` = 973 + kennlinie (811-826) | in state 2: 1 → back to **1** |
| `c1119 0x01` | high-byte permission mirror | blocks entry to 1 |
| `c1119 0x02` | high-byte condition | in state 5: → **0** |

- **from 0:** `bit4 \| bit3` → 3 (also latches `a586 = a599`); `b298==4` → 4; enter **1** iff `bit0 ∧ !bit1 ∧ !bit2 ∧ !(c1119&1) ∧ a587 ∧ (d1173==0 ∨ cal43ccc[0xb]&1)` (`8013e8aa:33-52`); else stay 0 (latching `d1167=1` to confirm-off when `a588 != 0`).
- **from 1:** `bit3` → 3 · `b298==4` → 4 · `bit0 ∧ !bit1 ∧ !bit2 ∧ bit6` → 2 · `bit0 ∧ !bit1 ∧ bit2` → 5 · `bit0 ∧ !bit1 ∧ !bit2 ∧ !bit6` → stay 1 · `!bit0 ∨ bit1` → **6** (blend-out, `d1188=1`, CAN=0). (`:217-302`)
- **from 2:** `bit3` → 3 · `b298==4` → 4 · `!bit0 ∨ bit1` → 6 · `bit2` → 5 · `bit7` → back to 1 · else stay 2. (`:125-171`)
- **from 4:** `bit5` → housekeep `a589=1`; `bit3` → 3; else sticky. (`:172-179`)
- **from 5:** `bit3` → 3 · `b298==4` → 4 · `!bit0 ∨ bit1 ∨ (c1119&2)` → **0**; else stay 5. (`:180-215`)
- **from 3 / 6:** no transition arithmetic. Recovery is the **master reset** at `8013ef46:48-105` — if
  `acc_master_compute_enable == 0` the function early-returns and the state freezes; if the ECU is not
  ACC/GRA-coded (or ACC_05 mode is selected) everything clears, `STATE_CRU_CTL` → 3 or 0, and the launch
  latch `d000118a` re-arms to 1.

### 4.3 The machine stays regulating to 0 km/h (CONFIRMED)

A grep of the whole machine (`8013ef46`, `8013e8aa` and all four sub-handlers) for every ego-speed
variable (`Ramd0005618` raw, `Ramd0007ce8` filtered, `d000d644`, `d000da54`) and for the 15 km/h-monitor
outputs (`d000d8ab`, `d000d79a`, `d000d88c`, `d000d8ee`, `d000d8ce`) returns **two ego-speed terms, both
of which only set sub-flags inside the regulating states**:

```c
// TERM 1 — 8013ef46:263-265 (raw speed, 7.81 km/h launch latch)
if (1000 < Ramd0005618) UNK_d000118a = 0;
// TERM 2 — 8013ef46:163 (filtered speed, 2.34 km/h creep flag)
if (... Ramd0007ce8 < WORD_ARRAY_80043c5c[0xe] /* 0x80043c78 = 300 */ ...) d0001171 = 1;
```

- `d000118a` is a **one-way launch latch**: set to 1 at every master reset, cleared the first time speed
  exceeds ~7.81 km/h, and it **never re-arms as speed falls**. Its only consumer is the inhibit term
  `(bVar4 && d000118a == 0)` at `8013ef46:304`, where `bVar4` is a debounce on the ESP/brake flag
  `d000b1c7` — so it functions as a launch-enable that suppresses an inhibit during initial
  acceleration, not as a stop floor.
- `d0001171` (set at `8013ef46:163`) sets sub-flag `d0001187` in `8013e8aa:48-90`, which only modifies the state-1 torque
  computation read by `8013e47c`. It never assigns `STATE_CRU_CTL`.
- The `d0007e84` hysteresis (`0x800439f8` = 1004 / `0x800439fa` = 973) drives bits 6/7, selecting state
  1 ↔ 2. Bit 6 sets when `d0007e84` is **high**, so falling speed *clears* it and the machine **stays in
  state 1**. `d0007e84`'s physical scale is unverified — its source `Ramd0007e86` is an ACC-internal
  value, **not** the 1/128 km/h ego speed — so no km/h label is asserted for it (**GAP**).
- The master-request producer `801408bc` reads no ego-speed *variable*, and the 15 km/h L2 monitor
  outputs are not read anywhere in the machine. **Read that narrowly:** `801408bc` still carries a speed
  dependence, because it consumes the ESP's `ECD_nicht_verfuegbar`, which the ESP asserts as a function
  of speed at ~15 km/h (§2). What the machine lacks is an *internal* speed threshold, not immunity to a
  speed-driven input.

**Consequence:** every exit from {1,5} is a fault, permission loss, inhibit, driver override or lateral
sub-state split — none of them keyed on an internally measured low ego speed. With ACC engaged and no
fault, override or ESP-brake intervention, `STATE_CRU_CTL` **stays in {1,5} down to 0 km/h**, so the hold
relay and the decel relay remain live to true standstill. Braking authority below ~15 km/h is a separate
question, decided by the ESP's ECD permission and by the internal L2 crawl monitor
(`low_speed_floors.md`), not by this state machine.

**Residual (GAP, low):** the permission/inhibit *inputs* to `8013ef46` — `a587`, `a593/594`, `a5a2`, the
`d000b1c7` ESP flag, `a335`, the `0x80086b00/b50/bc0` pedal switches and the ESP feedback bits — are
computed outside the CRUC chain and were not each traced to root. None is read from ego speed *within*
the machine, but an upstream input that is itself standstill-correlated (an ESP autohold flag, a driver
brake tap at the stop) could raise an inhibit near 0 km/h. That would be an ESP/driver-domain handoff,
not a cruise speed floor, and it does not affect the openpilot relay path.

## 5. Output gate and TSK egress (CONFIRMED)

The output stage is `8013ef46:855-976`, entered when
`(acc_mode_ACC05_Momentenanf_sel == 0 && LV_DCC_ENA) || (coding_GRA_ena && a572)`; inside it
`bVar4 = STATE_CRU_CTL ∈ {1,5}`.

| TSK signal | src var | rule | packed by |
|---|---|---|---|
| **TSK_Anhalten** (hold) | `d000a58d` | `= acc01_ACC_Anhalten` iff `bVar4 && LV_DCC_ENA`, else 0 (:944-950) | `80137a00` byte2·bit4 |
| **TSK_Verzoeg_Anf** (decel) | `Ramd0007cb8` | `= Ramd0007cae` iff `TSK_Freig_Verzoeg_Anf_src != 0`, else `0x8000` (:951-963) | `80137a00` byte8 |
| **TSK_Freig_Verzoeg_Anf** (decel enable) | `d000a58c` | `= (a57c==0 && bVar3 && sRamc113c ≤ cal) ‖ d0001181`, `bVar3 = bVar4 ‖ d0001188` (:864-943) | `80137a00` byte7·bit7 |
| **TSK_Zwangszusch_ESP** | `d000a58f` | `= (d000b28f ∈ {1,2})` (:970-976) | `80137a00` byte7·bit6 |
| **TSK_Status_GRA_ACC_01** | `d000b28d` | 0..3 from `8013e8aa` (3 = Fehler in state 3) | `80137a00` byte3·bits1-0 |
| **TSK_Codierung_ACC** | `d000a79f` | coding constant | `80137a00` byte7·bit5 |
| **TSK_Status_GRA_ACC_02** | `d000d9c7` (`STATE_DCC`) | via `801e3f26` | `8011e9ce` → TSK_04 byte8·bits7-6 |

The **hold** is gated *strictly* on `STATE_CRU_CTL ∈ {1,5}`. The **decel enable** is slightly looser —
`bVar3 = bVar4 || d0001188` — so `d0001188` (set in the state 2/6/0 handlers) lets a decel ramp blend
out for a few cycles after leaving {1,5}, but a *new* decel request requires {1,5}. The packer
additionally zeroes both if `d000ad7a == 0` (TSK not active) or forces decel → `0xA6` (=0) and Anhalten →
0 if `d000a852 != 0`. Neither `ad7a` nor `a852` is speed-derived.

### TSK_02 (DT_MNG_2, id 0x10C, 8 B, 20 ms) — builder `80137a00`

`80137a00` is the active packer, selected in the TX scheduler `80106ed8:747` because
`DAT_80043caf & 1 == 0`. `80137f2c` is the alternate coding and is never called. Both read the same
`Ramd0007cb8` and apply the same clamp, so the decel lever is packer-independent. The handles
(0x680/0x8c0/0x20c0) are HW mailbox control words, not CAN IDs.

| byte | bits | signal | source | encoding |
|---|---|---|---|---|
| 1 | 7-0 | TSK_02_CHK | computed | XOR ^0x0d |
| 2 | 3-0 | TSK_02_BZ counter | `d000b0dd` | 0..15 |
| 2 | 4 | **TSK_Anhalten** | `d000a58d` | hold / standstill request |
| 3 | 1-0 | TSK_Status_GRA_ACC_01 | `d000b28d` | 0..3 (3 = Fehler) |
| 3 | 7-2 | TSK_Fahrzeugmasse (+QBit) | `d0007ce4` / `d0007b70` | |
| 6-7 | — | TSK_Radbremsmom | const 0 (FR "not used") | 8 Nm/bit |
| 7 | 4 | TSK_Standby_Anf_ESP | const 0 (FR "not used") | binary |
| 7 | 5 | TSK_Codierung_ACC | `d000a79f` | binary |
| 7 | 6 | TSK_Zwangszusch_ESP | `d000a58f` | binary |
| 7 | 7 | **TSK_Freig_Verzoeg_Anf** | `d000a58c` | binary |
| 8 | 7-0 | **TSK_Verzoeg_Anf** | `Ramd0007cb8` (AC_SP_CRU_BRAKE_CTL) | 0.024 m/s², 0xA6 = 0, clamp `[0x6db1, 0x89b6]` |

### TSK_04 (DT_MNG_4, id 0x10E) — canmo `8011e9ce` (copies node `*d000d404+8..+0xf`), payload `801e3f26`

| byte | bits | signal |
|---|---|---|
| 2-3 | — | TSK_zul_Regelabw |
| 3-4 | — | TSK_ax_Getriebe |
| 5-6 | — | TSK_Wunsch_Uebersetz (0.0245/bit) |
| 5 | 6 | TSK_Limiter_aktiv |
| 8 | 7-6 | **TSK_Status_GRA_ACC_02** (`STATE_DCC`, `d000d9c7`) |

**TSK_01 (0x10A)** byte8 = `TSK_amax_moeglich` (max achievable accel), carries no decel.
**TSK_05 (0x111)** is not transmitted (Bit0 = 0; builder `80136794` has no callers).

## 6. ACC master state, engage inhibit and the status enum (CONFIRMED)

- **`d000d8ee` (ACC master state) ∈ {0,1,2}**, set in `80102f60:1202-1207`: `0` if `d8cf != 0` (off),
  else `(d8ce == 0) + 1` → **2 = engaged**, 1 = active.
- **`d000d8ce` = engage-inhibit word** (`80102f60:1197`, `= cal(+0x121) & OR(8 bits)`): any masked
  condition set blocks full engagement. Bits: b7 = `d890.5 && d6ab==0`; b6 = `d778` (masked off);
  b5 = `d890.5 && d6ac`; b4 = `d67e` (= `a4b2|a881`); b3 = `bVar19 && d890.7 && d8a8==0 && d776==0`;
  b2 = `d8e3<2 && …`; b1 = `cal(+0x116/117) < d770`; b0 = `d6a4 && !d893.0x40`. Full semantic naming of
  `d8ce` and of the ACC-state byte `d890` is a **GAP**.
- **`801eca44`** maps `d8ee` → the 2-bit status `d91c`/`d91d` (:71-87): 0 = nicht_verbaut, 1 = aktiv,
  2 = übersteuert (`d8ee==2 && d8e2.bit2`), **3 = Fehler_GRA_ACC_nicht_möglich** (`d8ee==2 && !d8e2.bit2`).
- **status-3 trigger** (this CRU/AC-based coding, `CLF_CAN_CONF_FCT.Bit0 = 0`): any of the 13 cruise
  diagnoses latched at SYM_3 → `d000d8e0 != 0` → debounced `d744` → `d8b4` (which gates recompute, making
  it a **key-cycle latch**) → `d8e2.bit2 = 0` → `801eca44` → status 3, when ACC is engaged (`d8ee == 2`).
  The fatal-**deactivation** path (`d8e0 & cal+0x178`) is dead (mask = 0). The aggregator body has two
  entry points: `80102f60` (which prologues `801eee40`/`801df81c`) falls through into `801dfe06`; they are
  the same code.
- **Three** distinct signals carry a 0..3 status enum — do not conflate them (correction 2026-08-20):
  - **TSK_Status_GRA_ACC_01** (TSK_02/0x10C byte3) ← **`b28d`** (`STATE_CRU_CTL_CAN`), the CRUC state
    machine (routes A/B/C, `status3_routes.md`).
  - **The 0x5C0 status enum** ← **`d91d`** (`801eca44` from `d8ee`+`d8e2`), published via `afef`,
    packed by `80137084`. This is a **separate CAN channel**, driven by the relayed-symptom accumulator
    `d8e0`. There is **no `d91d`→`b28d` write** — the earlier "via `d91d`/`b28d`" wording wrongly merged
    these two channels. Both `b28d` and `d91d` are speed-independent (`low_speed_floors.md` §1).
  - **TSK_Status_GRA_ACC_02** (TSK_04/0x10E byte8 bits 6-7) ← `d000d9c7` (`STATE_DCC`) via `801e3f26`.

## 7. Standstill hold — `TSK_Anhalten` (CONFIRMED)

`TSK_Anhalten` is a **live, gated pass-through** of the incoming `ACC_01.ACC_Anhalten` CAN bit. Every hop
is firmware-verified:

```
ACC_01 / 0x109 byte7·bit1 (ACC_Anhalten)
  →[801383e8:100, E2E seed 0x08 OK, RX-poll handle 0x240]→ d000a7ae
  →[8013ef46:944-950, a58d = a7ae when the gate holds, else 0]→ d000a58d
  →[80137a00:55 / :127, gated by ad7a / a852]→ TSK_02 (0x10C) byte2·bit4
  →[TX 80106ed8:739-753, cal caf&1 = 0 → mailbox 0x680]→ gateway J533 → ESP
```

- **Forward gate** (what an external ACC master must satisfy): `ad0f != 0` (master compute-enable) **AND**
  `a757 != 0` (`LV_DCC_ENA` — coded Basic-ACC; a GRA-coded car with `a757 = 0` never forwards) **AND**
  `a5a8 == 0` (cal-fixed 0 on the Q5, sole writer `801abf64:21`) **AND** `b28e ∈ {1,5}`. The runtime
  conditions therefore reduce to: ACC compute-enabled, Basic-ACC coded, cruise actively regulating.
- It reads 0 on a stock car only because the single-radar B8 ACC never asserts `ACC_Anhalten` (30 km/h
  floor, memory `b8-acc-radar-hardware`). The path itself is intact.
- **Completeness:** `TSK_Anhalten` is the only engine-originated discrete *hold* vector.
  `TSK_Zwangszusch_ESP` (`a58f`, byte7·bit6) is a live ESP-coupling *enable*, not a hold.
  `TSK_Radbremsmom` and `TSK_Standby_Anf_ESP` are const 0. The engine has **no EPB-engage TX** on any
  path (`ACC_05`/0x10D `ACC_Betaetigung_EPB` is RX-only). EPB is actuated only radar→EPB or ESP→EPB.
- **Timeout is continuity, not a max-hold cap.** After 4 consecutively dropped ACC_01 frames
  (`LV_CAN_DCC_NOT_VLD_FAST`), `801a6134` (`reset_flags_and_values`, an init/timeout default rather than
  the operative writer) zeroes `a7ae` → `TSK_Anhalten` → 0 → the ESP releases. There is **no EPB failsafe
  and no rollaway prevention** — the engine simply drops the request. Stream ACC_01 continuously with a
  valid E2E seed 0x08 and incrementing counter, with no ≥4-frame gap, and the engine relays hold
  indefinitely; waiting at a light is fine.

## 8. Stop-and-go: two architectures, the engine is a follower in both (CONFIRMED)

**(A) F2S / SOFT_STOP** — the engine autonomously braking to standstill. Only the **F2S-specific
refinements** are compiled out: the explicit wheel-brake-hold torque `TQ_BRAKE_HLD` → `TSK_Radbremsmom`
is const 0; the smooth-approach curve `IP_AC_SP_MIN_DCC_FOL_2_STOP` is empty (`0x5b734` all zero);
`LV_DCC_ENA_FOL_2_STOP` is a compile-0 stub and `d000a758` (`LV_DCC_STST_ENA`) is dead (write-only).
Cruise type comes from long-coding cell 27 (`STATE_DCC_TYP`), so coding cell 27 = 3 asserts F2S while the
stub stays 0 → `LV_VAR_COD_CRU_DCC_NOT_PLAUS` → status-3 fault, which is why VCDS rejects mode 03h.
**But the ACC_01 / Basic-ACC path itself does brake toward standstill** through the normal decel path
(−3.0 authority to 0, the `TSK_Anhalten` hold relay, standstill-regime management) — a de-facto
follow-to-stop. Only the formal OEM F2S mode and the wheel-brake-hold torque are absent.

**(B) ACC_05 Momentenanforderung / EPB stop-and-go** (the Macan architecture: EPB holds, the engine
coordinates drive-off) — the machine code **exists but is cal-gated off** (`a5a8 = 0`).
`8010a6ec` is the EPB/standstill-hold state machine (hold timer → `a54d` hold-confirmed, inhibits
`a54b/a54c`); `80141528` is the drive-off Momentenanforderung→torque conversion (`d0007baa` → `d0007ce0`
via kennlinie `0xa005d608`, firing on `b057 ∈ {3,4} && a3b9 && a54b==0 && b055==1`); `8010a4fc` is its
diagnostics. Enabling it needs a reflash (`0x80043bc6` + `0x43caf` bit0), switches to a different
architecture, **kills the `TSK_Anhalten` relay**, and still adds no F2S brake side.

**Neither architecture originates a hold on the bus from the engine** — there is no ACC_05 TX packer, and
the `TSK_Anhalten` relay is off when `a5a8 != 0`. For an external ACC master (openpilot) the Q5 relay
path is sufficient: transmit ACC_01 (0x109) with byte7·bit1 = 1 and valid MLB E2E (seed 0x08, rolling
counter in byte1's low nibble), keep the ECU Basic-ACC coded and ACC actively engaged (`b28e ∈ {1,5}`),
and the engine relays hold on 0x10C byte2·bit4. This is the OEM-intended ACC→ESP hold channel, and the
missing autonomous soft-stop does not block braking to standstill. The stock 30 km/h dropout is the
single-radar limit, not the engine's.

## 9. Open items

1. **MO handle ↔ CAN-ID binding** (0x240 / 0x8a0 / 0x600) lives in external HAL/COM config. Covered to
   high confidence by E2E-seed + FR + opendbc triangulation, but not read off a decoded config line.
   (**GAP**)
2. **`d0007baa` absolute m/s² scale** — runtime gain `b0d4` versus the FR's 0.005; reconcile on the bench.
3. **`d0007e84` physical scale** — an ACC-internal value, not ego speed; unverified.
4. Full semantic naming of the `d8ce` engage-inhibit bit-word and the `d890` ACC-state byte.
5. The permission/inhibit input roots to `8013ef46` (§4.3 residual).
