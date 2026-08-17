# ACC longitudinal flow: ACC_01 → TSK (MED17.1.1 8R0907115N_0006)

End-to-end map of the engine ECU's ACC/cruise longitudinal path: from the received ACC request
(**ACC_01, `0x109`, RX**) through the ACC/decel coordinator to the deceleration, hold and status the
engine transmits to the brake and gateway (**TSK_01 `0x10a`, TSK_02 `0x10c`, TSK_04 `0x10e`, TX**).

Built from the decompiled corpus (`analysis/decompiles_r/`) plus firmware reads. Load base
`0x80000000`; `0xa00xxxxx` = uncached mirror; file offset = `addr & 0x1FFFFFFF`; RAM = `0xd00xxxxx`.
Read `can_signal_map.md` first — every signal↔RAM binding quoted here comes from the COM message
table decoded there.

Confidence tags: **[C]** read the decompile/bytes and verified · **[M]** measured on-car ·
**[I]** inferred · **[G]** gap.

> **Two structural facts up front.**
> 1. **Nothing about the ACC path is hand-coded per message.** RX unpacking and TX assembly are
>    generic table walks (`FUN_8008a75e` / `FUN_8008a3f8`) over flash descriptors, and the frames go
>    out through the TC1797's own MultiCAN. The application functions below produce and consume RAM
>    shadows; the wire layout is data.
> 2. **The ACC controllers reach their calibration through `a9`**, which is `0xa0103464` — the
>    uncached alias of the cal-object table `0x80103464`, so `*(a9+off)` is cal object `off/4`. It is
>    in `ecu.conf` `BASEREGS`, so the decompiles already fold every ACC cal read to a concrete
>    `0x803b_xxxx` address. See `a9_resolution.md`.

## Block diagram

```
 CAN RX (powertrain)                    ENGINE ECU (MED17.1.1)                          CAN TX
 ┌───────────────┐                ┌──────────────────────────────────────────┐      ┌──────────────┐
 │ ACC_01 (0x109)│──generic RX───▶│ ACC_Sollbeschleunigung  d00084aa         │─────▶│ TSK_02 (0x10C)│
 │  radar/OP     │  FUN_8008a75e  │ ACC_Anhalten            d000a59b.0       │      │ Verzoeg_Anf   │
 │  accel/hold/  │                │ ACC_Status_ACC          d000a590         │      │ d0008d5a 56|8 │
 │  status       │                │            ▼                             │      │ Radbremsmom   │
 │               │                │ FUN_801455ae  ACC/ESP decel coordinator  │      │ d0005de0 40|12│
 │ ACC_05 (0x10D)│──same shadows─▶│  (gate d000a454==2)                      │      │ Anhalten      │
 │               │                │   → d0005f20 / d0005d00 (±500000 rail)   │      │ d000a33d 12|1 │
 │ ESP_05 (0x106)│──ECD relay────▶│   → d000ab01 ACC state (0..3)            │      └──────────────┘
 │  bit33 ECD_   │  see           │            ▼                             │      ┌──────────────┐
 │  nicht_verf.  │  ecd_relay.md  │ FUN_8014322e  ACC→TSK decel bridge       │─────▶│ TSK_04 (0x10E)│
 │               │                │ FUN_801434de  rails / standstill         │      │ ax_Getriebe   │
 │ mode: d000a3c1│──FUN_802c806e─▶│ FUN_801418ea  accel envelope (cal #247)  │      │ d00082b6 18|9 │
 │  →  d000a454  │  (1=GRA 2=ACC) │ FUN_80140922  TSK_02 shadows             │      │ Status_GRA_   │
 │               │                │ FUN_801405d4  decel/hold output gate     │      │ ACC_02 d000ab01│
 └───────────────┘                │ FUN_8014469a  status coordinator         │      └──────────────┘
                                  │ FUN_80050eea  brake-torque producer      │      ┌──────────────┐
                                  └──────────────────────────────────────────┘─────▶│ TSK_01 (0x10A)│
                                                                                    │ Status_AB     │
                                                                                    │ d0005e34 16|24│
                                                                                    └──────────────┘
```

## The spine [C]

```
ACC_01 (0x109, MO cfg record 63)
  → FUN_8008a75e            generic RX distributor; per-signal descriptors listed in can_signal_map.md
  → ACC_Sollbeschleunigung  d00084aa (24|11), ACC_Anhalten d000a59b.0 (57|1),
                            ACC_Status_ACC d000a590 (60|3), gradients d00084be/c0
  → FUN_800b1136 / 800b0e94 ACC-command bridge: d000a590 → d000a368 state, d000a59b.0 → d0000113.4
  → FUN_801455ae            ACC/ESP decel coordinator — gate d000a454==2 — writes decel
                            d0005f20/d0005d00, state d000ab01, ACC-active flag d000a367 (FUN_80145c88)
  → FUN_8014322e            ACC→TSK decel bridge (d0005f20 + d000a454 + d000ab01; PT1 FUN_8007c10c)
  → FUN_801418ea / 801434de accel envelope + ±500000 authority rails
  → FUN_80140922            TSK_02 shadow producer (mode-muxed on d000a454)
  → FUN_801405d4            output gate: TSK_Verzoeg_Anf d0008d5a, TSK_Anhalten d000a33d
  → FUN_8008a3f8            generic TX assembler + E2E → MultiCAN → TSK_02 (0x10C)
Parallel: FUN_8014469a → TSK_01 Status_AB (d0005e34) + TSK_04 ax_Getriebe (d00082b6);
          FUN_801455ae → TSK_04 status (d000ab01);  FUN_80050eea → TSK_Radbremsmom (d0005de0)
```

## Encoding conventions

| domain | encoding | notes |
|---|---|---|
| `ACC_Sollbeschleunigung` (ACC_01 24\|11) → `d00084aa` | res **0.005 m/s²**, offset **−7.22** | commanded accel; negative half = decel request |
| `TSK_Verzoeg_Anf` (TSK_02 56\|8) ← `d0008d5a` | res **0.024 m/s²**, offset **−3.984** | decel out; raw 0 = −3.984, raw 166 = 0.000 |
| `TSK_ax_Getriebe` (TSK_04 18\|9) ← `d00082b6` | res 0.024, offset **−2.016** | raw 84 = 0.000 |
| `TSK_amax_moeglich` (TSK_01 48\|9) ← `d0008ec0` | res 0.024, offset −2.016 | max achievable accel |
| internal accel/decel authority (`d0005f20`, `d0005cd0/cf4`) | s32, **±500000** ≈ ±5.0 m/s² (**[I]** on scale) | rail clamp `0xfff85ee0` = −500000 |
| vehicle speed, functional | `d0008f5e` / `d0008c22`, **0.01 km/h** | from `comsig_d0008608_b32l16` (ESP_01 32\|16) |
| vehicle speed, EGAS-L2 monitor | `d0007b8a`, **1/128 km/h** = functional × 32/25 | independent decode, `min_speed_l2.md` |

## 1. INPUT — ACC_01 → RAM shadows [C]

Every ACC_01 signal now has a concrete RAM target; the full list is in `can_signal_map.md`. The three
that drive the longitudinal path:

| signal | frame | RAM | consumer |
|---|---|---|---|
| `ACC_Sollbeschleunigung` | 24\|11 | `d00084aa` | setpoint chain → `FUN_800b1136` → `d000830a` |
| `ACC_Anhalten` | 57\|1 | `d000a59b` bit 0 | hold relay, §4a |
| `ACC_Status_ACC` | 60\|3 | `d000a590` | `FUN_800b0e94` → `d000a368` ACC state |

**ACC_05 (`0x10d`) writes the same two shadows** — `d000a590` from 57\|3 and `d000a59b` from 62\|1 —
so a platform that sends the ACC command on `0x10d` lands on the same variables. `FUN_800b0e94` is
dispatched per sub-frame (`0x55`, `0x29`, `0x2a`, `0x56`) and handles both.

E2E is generic: alive counter plus a type-9 XOR checksum with the id-derived seed (`0x109` → `0x08`),
handled inside `FUN_8008a75e`. On a failed check or a timeout, `FUN_8008b17c`
(`COM_rx_default_substitution`) overwrites the message's shadows with their defaults.

## 2. MODE SELECT — the GRA/ACC master mode `d000a454` [C]

The whole TSK cluster is gated by **`DAT_d000a454`**, set by **`FUN_802c806e`** from the ACC master
state **`DAT_d000a3c1`** (produced by the state-vector engine `FUN_800accac` — see
`engage_state.md`):

| `d000a3c1` | `d000a454` | meaning |
|---|---|---|
| 1 | **1** | GRA-type cruise |
| 2 | **2** | ACC/DCC-type active |
| 3 | **2** (+ `d000a453`=1) | ACC "extended" |
| else | 0 | ACC inactive |

`d000a454` gates `FUN_801455ae` (`==2`), `FUN_80140922` (`==1`/`==2`), `FUN_8014469a`,
`FUN_801434de`, `FUN_801405d4` (`∈{1,2}`).

**Actively-regulating gate:** `DAT_d000a361` / `DAT_d000a362`, values `1`/`2`/`5`; **`∈{1,5}` = ACC
actively regulating** — the analog of Simos8.5's `b28e∈{1,5}`. It gates the accel pass-through
(`FUN_801434de`, `FUN_8014469a`) and the TSK_02 output stage (`FUN_801405d4`). **[C]**

## 3. REQUEST FORMATION and the decel authority [C]

- **`FUN_801455ae` = the ACC/ESP decel coordinator** (also the TSK_04 status producer). Reads the ACC
  request, gated `d000a454==2`, and emits the internal decel authority as `DAT_d0005f20` and
  `DAT_d0005d00` (s32). **The negative rail clamp is `0xfff85ee0` = −500000**
  (`801455ae.c:247-248, :346-347`; `iVar9=-500000` at `:289`).
- The ± rails are set in **`FUN_801434de`**: `DAT_d0005cd0 = +500000`, `DAT_d0005cf4 = −500000`
  (`801434de.c:26-27`). At the inferred 1e-5 m/s²/LSB scale that is ±5.0 m/s². The on-wire
  `TSK_Verzoeg_Anf` then saturates at −3.984 m/s² because of its 8-bit range, so the effective wire
  floor is −3.984 unless both the internal rail and the signal range change. Both rails are
  **hardcoded immediates, not cal reads** — firmware patch, not calibration. **[C]**
- **`FUN_8014322e` = the ACC→TSK decel bridge**: reads `d0005f20` + `d000a454` + `d000ab01`, runs
  `FUN_8007c10c` / `FUN_8007bfec`, feeds `FUN_80140922`. **`FUN_8007c10c` is a first-order PT1 lag
  filter** (`new = old + (in−old)·(1−k)`, coefficient from `&DAT_80041198`) — the decel setpoint is
  *filtered* on this hop, not hard-clamped. **[C]**
- **`FUN_801418ea` = the ACC accel/decel envelope**: 24 map lookups
  (`Kennfeld_s16` / `Kennlinie_s16`) into **cal object #247 `0x803b4834`** (via `a9+0x3dc`), fields up
  to `+0x6e4`. This is the shaping lever; see `kennlinie_interpolators.md` for how to decode the
  axes. **[C]**

## 4. TSK_02 (`0x10C`) OUTPUT [C]

`FUN_80140922` computes the shadow set, mode-muxed on `d000a454`; `FUN_801405d4` is the **output
gate** that actually writes the two wire variables.

| wire signal | frame | RAM | producer |
|---|---|---|---|
| `TSK_Anhalten` | 12\|1 | `d000a33d` bit 0 | `FUN_801405d4:174` — §4a |
| `TSK_Status` | 16\|2 | `d000ab01` | `FUN_801455ae` (same byte as TSK_04 62\|2) |
| (`TSK_Fahrzeugmasse`) | 18\|5 | `d00082e6` | shared with TSK_05 |
| — | 23\|1 | `d000a358` bit 0 | `FUN_8014106e:57` |
| **`TSK_Radbremsmom`** | 40\|12 | **`d0005de0`** | `FUN_80050eea:457/463` — brake-torque request, cal-substituted in the failsafe branch |
| `TSK_Standby_Anf_ESP` | 52\|1 | `d000a968` bit 0 | `FUN_80050eea:454/461` |
| (`TSK_Codierung_ACC`) | 53\|1 | `d000a33f` bit 0 | `FUN_8014469a:57` |
| (`TSK_Zwangszusch_ESP`) | 54\|1 | `d000a345` bit 0 | `FUN_801405d4` tail |
| (`TSK_Freig_Verzoeg_Anf`) | 55\|1 | `d000a968` bit 1 | `FUN_80050eea` |
| **`TSK_Verzoeg_Anf`** | 56\|8 | **`d0008d5a`** | `FUN_801405d4:180` |

Names in parentheses are taken from TSK_05, which binds the same RAM bytes at the same geometry;
`vw_mlb.dbc`'s TSK_02 variant does not list them.

The decel output is a **hard zero, not a cal substitution**:

```c
// FUN_801405d4 (TSK02_decel_gate) :176-180
uVar8 = 0;
if (bVar1) uVar8 = DAT_d00082c0;
TSK_Verzoeg_Anf_tx = uVar8;          // 0xd0008d5a
```

`bVar1` derives from `a362 ∈ {1,5}` (ACC regulating), `a363`, and a `d0005cb0 <= d0005cc0` test. That
is why the neutral value on the wire is raw 166 (= 0.000 m/s² through the 0.024/−3.984 conversion)
rather than an SNA sentinel: the engine affirmatively requests nothing.

Internal shadows produced by `FUN_80140922` (not directly wire-bound):

| shadow | GRA (`a454==1`) | ACC (`a454==2`) | consumed by |
|---|---|---|---|
| `d0008302` | `min(d0008c9e, 0x7fff)` | cal `#780+0x1a` | `8014469a` |
| `d00082ae` | `d000864c` | `d000830a` | `801418ea` |
| `d00082ce` → TSK_04 12\|6 | `d000864e` | `clamp(d000830c,1000,10000)` | `8014469a` |
| `d00082d0` | `d0008650` | `min(clamp(d000830e,1000,10000), wheelspeed)` | `801418ea` |
| `d000a343` | `d000a7e7` | `d000a368` OR'd digital-input bits | `801418ea` |
| `d000a344` | `d000a7e7 & 3` | enum from present-gates | `8014469a` |
| `d000a35c` | `d000a7ef` | standstill bit from cal `#780+0x13`, wheelspeed-gated | `801434de` |

`d000a35c` is an **internal** standstill flag consumed by `FUN_801434de` (it turns into the
standstill request `d000a365` when `a361 ∈ {1,5}`). It is *not* the `TSK_Anhalten` COM source.

### 4a. `ACC_Anhalten` → `TSK_Anhalten` — a direct gated relay [C]

```
ACC_01 (0x109) frame bit 57  ACC_Anhalten
  → boolean descriptor 0x80034a04       → 0xd000a59b bit 0
  → FUN_800b0e94                        → 0xd0000113 bit 4        (:65-72 and :102-109)
  → FUN_801405d4:167-174                → 0xd000a33d
        d000a33d = (a362 ∈ {1,5} && d000a454 == 2) ? (d0000113 >> 4 & 1) : 0
  → boolean descriptor 0x80034b58       → TSK_02 (0x10C) frame bit 12  TSK_Anhalten
```

So MED17 relays the received `ACC_Anhalten` bit straight through, gated on ACC mode and on ACC
actively regulating — structurally the same relay Simos8.5 uses (`anhalten_compare.md`).
**openpilot, as the ACC command source, owns `TSK_Anhalten`.** ACC_05 bit 62 reaches the same
`d000a59b` bit, so the alternate command frame works identically.

## 5. TSK_04 (`0x10E`) OUTPUT [C]

| wire signal | frame | RAM | detail |
|---|---|---|---|
| `TSK_zul_Regelabw` | 12\|6 | `d00082ce` | from `FUN_80140922` |
| **`TSK_ax_Getriebe`** | 18\|9 | **`d00082b6`** | written by `FUN_8014469a:864` |
| `TSK_Wunsch_Uebersetz` | 27\|10 | `d00082fc` | gear-ratio request |
| `TSK_Freig_WU` | 37\|1 | `d000a720` bit 0 | |
| `TSK_Limiter_aktiv` | 38\|1 | `d000aac0` bit 0 | `FUN_8020aef6:164` |
| **`TSK_Status_GRA_ACC_02`** | 62\|2 | **`d000ab01`** | `FUN_801455ae` switch on `ab01`; `ab01=3` forced when the TSK_04 present-gate fails. Remapped by `FUN_80199344` (1→3, 2→4, 3→7) into `d000a13d`. Same byte as TSK_02 16\|2, which is why the two move in lockstep. |

### Payload behaviour while the engine is not granting **[M]**

Measured on-car with openpilot as ACC master. When `TSK_Status_GRA_ACC_02 == 0` the ACC request
channels are not "live but flagged inactive" — they are driven to a well-formed neutral and held:

| field | status 0 (n=8472) | status 1 (n=921) |
|---|---|---|
| `TSK_04.TSK_ax_Getriebe` | raw **84** on all 8472 frames — one value (0.000 m/s²) | 75 distinct raws, −1.440…+1.416 m/s² |
| `TSK_02.TSK_Verzoeg_Anf` | raw 166 on 8466/8472 (0.000 m/s²) | 44 distinct raws, −1.440…+0.504 m/s² |
| `TSK_02.TSK_Radbremsmom` | 0 on 8465/8472 | 0 or 18 (144 Nm) |

Raw 84 and raw 166 are exact zeros, not SNA sentinels — the CAN-side confirmation of the hard-zero in
`FUN_801405d4` and of `FUN_801455ae` case 0 setting `d0005f20 = d0005d00 = 0xfff85ee0`.

Held under load: a steady commanded **+1.535 m/s²** for 7.8 s while the engine was not granting never
moved `ax_Getriebe` off raw 84. When the status does flip, the command appears in the **same frame**
(cmd 0.900 → `ax_raw` 121 = 0.888), so while granting `TSK_ax_Getriebe` tracks
`ACC_Sollbeschleunigung` ~1:1 at the 0.024 quantum.

**The two channels release asymmetrically at disengage** (7 non-neutral frames in one ~120 ms
window): `TSK_ax_Getriebe` steps to neutral in the same frame as the status, while
`TSK_Verzoeg_Anf` ramps out over ~6 frames (raw 126 → 166) with `TSK_Radbremsmom` decaying 18 → 15.
Brake pressure is released gracefully; the gearbox accel channel is cut instantly.

**What stays live while not granting** — the engine is refusing, not asleep: `TSK_amax_moeglich`
(99 distinct values, 0.000…6.072 m/s², tracking speed), `TSK_Wunsch_Uebersetz` (63 distinct values),
and `TSK_Status_AB` (`0x180` vs 0).

**Consequence:** there is no residual setpoint for a downstream consumer to act on — a well-formed
zero goes out at 50 Hz.

## 6. TSK_01 (`0x10A`) OUTPUT [C]

`TSK_Status_AB` (16\|24) is the single 32-bit word **`d0005e34`** (descriptor `0x80039460`), written
only at `0x801454b6` in `FUN_8014469a` as a copy of `d0005e38`, which copies `d0004938`, which is
OR-accumulated from the 8-bool→byte packer `FUN_80143a68`. `TSK_amax_moeglich` (48\|9) is `d0008ec0`;
its origin is the powertrain torque model, upstream of the TSK cluster. **[G]**

**Frame bit 23 of TSK_01 is the engine's echo of the ESP's ECD availability.** The complete chain —
`ESP_05` bit 33 → `d000ab42` bit 5 → … → `d0005e34` bit 7 → the wire — plus the on-car evidence is in
**`ecd_relay.md`**. It is not reproduced here.

## 7. Where the ACC low-speed floor is

**Not in this ECU.** The ~15 km/h floor is `ESP_05` frame bit 33 `ECD_nicht_verfuegbar`, declared by
the ESP/ABS and relayed by the engine. No MED17 calibration edit lifts it on its own. Full account
and evidence: **`ecd_relay.md`**.

Two ECU-side items remain relevant and must not be confused with it:

- **EGAS-L2 cal #208** (`0x80389809` = 15, `0x8038980e` = 7) is a **separate, real** Level-2 monitor
  gate running on the independent monitor speed `d0007b8a`. It is a fault contributor, not the ACC
  permit, but it can impose its own 15/7 boundary regardless of the ESP — so sub-15 operation likely
  needs it edited *as well as* the ESP-side constraint addressed. See `l2_monitors.md`.
- **A real but inert low-speed engage lock** hangs off `ESP_05` bit 36 (`ESP_HDC_Standby`) →
  `d000ab6a` → … → `d00049ca` → `FUN_80143b34` → `ACC_engage_state_machine`. Constant 0 on these
  cars. See `ecd_relay.md` and `engage_state.md`.

## 8. Editable levers (openpilot)

| goal | lever | status |
|---|---|---|
| **operate below ~15 km/h** | `ESP_05` bit 33 `ECD_nicht_verfuegbar` — an **ESP/ABS** decision, not an engine cal | **not addressable in this ECU** (`ecd_relay.md`) |
| ...and the ECU-side monitor that would still bite | cal #208 `0x80389809`=15 / `0x8038980e`=7 | editable; necessary but not sufficient (`l2_monitors.md`) |
| **raise the brake decel floor** | decel-shaping maps in `FUN_801418ea` = cal obj **#247 `0x803b4834`** (via `a9+0x3dc`) and block **#269 `0x803b5bfc`** (via `a9+0x434`) | addressable |
| decel *ceiling* (±500000, −3.984 wire) | hardcoded immediates in `FUN_801434de` / `FUN_801455ae` + the Com signal range | firmware patch only |
| hold / standstill | `ACC_Anhalten` → `TSK_Anhalten`, §4a | openpilot drives it directly; stock is fine |
| drive-off shaping | `FUN_801405d4`, cal `*(a9+0x3d8)` = `PTR_DAT_8010383c` | behavioural tuning only |
| ACC/GRA mode | `d000a3c1` → `d000a454` (`FUN_802c806e`) | runtime state, not a cal |
| 3 km/h "creep gate" | `0x803b88ae` / the 3.01 km/h literal | **leave stock — diagnostic flags, not control gates** (`min_speed_l2.md`) |

All cal edits need a cal-block checksum recompute (`core/checksum`), and the two bytes should be read
back over UDS after flashing.

## 9. Open threads

1. **The upstream ACC-enable arbitration** that packs `cond[0x1c] = 2` into the condition vector
   `d0009b63` — one hop above the state-vector engine. **[G]** (`engage_state.md`)
2. **`TSK_amax_moeglich`'s source** (`d0008ec0`) in the torque model. **[G]**
3. **Cyclic TX period** — the producers run from an OS function-pointer task table with no in-corpus
   callers, so the period is not statically recoverable. **[G]**
4. **`d00082e6` / `d000a358` / `d000a33f` semantics** — bound to the wire and named by analogy with
   TSK_05, but their producers are only partly traced. **[I]**

## Function inventory

| addr | role | conf |
|---|---|---|
| `FUN_8008a75e` | generic RX distributor (signal + boolean walk, E2E) | C |
| `FUN_8008a3f8` | generic TX assembler (+ checksum) → `FUN_800a3848` → MultiCAN | C |
| `FUN_8008b17c` | `COM_rx_default_substitution` — RX timeout/default setter | C |
| `FUN_800981cc` | `DSM_get_event_status` — per-signal substitution gate (0 = released) | C |
| `FUN_800accac` / `FUN_800abc46` | ACC master state-vector engine → `d000a3c1` | C |
| `FUN_802c806e` | `a3c1` → `a454` GRA/ACC mode select | C |
| `FUN_800b0e94` | ACC command remap: `a590`→`a368`, `a59b.0`→`d0000113.4` | C |
| `FUN_800b1136` | ACC-mode setpoint bridge — `d00084xx` RX shadows → `d000830a/c/e` | C/med |
| `FUN_801455ae` | ACC/ESP decel coordinator + TSK_04 status (`d0005f20`, `ab01`, rail −500000) | C |
| `FUN_80145c88` | ACC-active flag `d000a367` | C |
| `FUN_8014322e` | ACC→TSK decel bridge | C |
| `FUN_801434de` | decel/standstill stage (±500000 rails, `d000a365` hold) | C |
| `FUN_801418ea` | ACC accel envelope (24 map lookups into cal #247) | C |
| `FUN_8007c10c` | PT1 lag filter | C |
| `FUN_80140922` | TSK_02 shadow producer (mode-mux) | C |
| `FUN_801405d4` | TSK_02 output gate — writes `d0008d5a` and `d000a33d` | C |
| `FUN_8014469a` + `FUN_80143a68` | status coordinator + 8-bool→byte packer → `d0005e34`, `d00082b6` | C |
| `FUN_8014106e` | TSK status bits `d000a358` / `d000a35d` | C |
| `FUN_80050eea` | brake-torque producer — `d0005de0`, `d000a968` | C |
| `FUN_80199344` | `ab01`→`a13d` status remap (1→3, 2→4, 3→7) | C |
| `FUN_802cb15e` | GRA-mode TSK_02 source controller | C |
| `FUN_80143b8a` / `FUN_80143b34` | ACC engage state machine + its low-speed block guard | C |
