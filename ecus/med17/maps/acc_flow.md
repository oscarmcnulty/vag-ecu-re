# ACC longitudinal flow: ACC_01 → TSK signals (MED17.1.1 8R0907115N_0006)

End-to-end map of the Bosch engine ECU's ACC/cruise longitudinal path — from the received ACC request
(**ACC_01, 0x109, RX**) through the ACC/decel coordinator to the deceleration + status transmitted to the
brake/gateway (**TSK_01 0x10a, TSK_02 0x10c, TSK_04 0x10e, all TX**). The MED17 counterpart of the Simos8.5
`acc_flow.md`. Built from the decompiled corpus (`analysis/decompiles_r/`) + firmware reads.
Load base `0x80000000`; `0xa00xxxxx` = uncached mirror; file off =
`addr & 0x1FFFFFFF`; RAM = `0xd00xxxxx`. Read `can_signal_map.md` first for the CAN infrastructure.

Confidence tags: **[C]** = read the decompile & verified · **[I]** = inferred / architecture-consistent ·
**[G]** = gap, not recovered from the C.

> **How this ECU differs from Simos8.5, up front.** Simos8.5 hand-decodes each frame into named signal
> shadows and hand-packs each TX message (`80137a00` etc.). **MED17.1.1 is generic table-driven Vector
> CANbedded IL / AUTOSAR-Com over an external CAN controller (MLI link)** (see `can_signal_map.md`).
> Two structural consequences dominate this whole document:
> 1. **The byte↔signal wire layout is in flash descriptor tables, not in code** — so exact per-signal bit
>    offsets are read from the dbc + shadow semantics, not from a readable packer. **[G]**
> 2. **The ACC controllers address their calibration through base register `a9`**
>    (`a9 = 0xa0103464` = the cal-object table `0x80103464`; `*(a9+off)` = cal object `off/4`). It's in
>    `ecu.conf` `BASEREGS`, so `reproduce.sh` folds every ACC `*(a9+off)` to a concrete `0x803b_xxxx` cal
>    address. This is the Simos8.5 `a1`-unlock analog; resolved by boot emulation. See `maps/a9_resolution.md`.
>    (The `*(a9+0x3ec)` "RX-request struct" is actually a cal object, not a RAM buffer.) **[C]**

## Block diagram
```
 CAN RX (powertrain bus)                 ENGINE ECU (MED17.1.1, generic CANbedded)          CAN TX
 ┌───────────────┐  FUN_80099600   ┌──────────────────────────────────────────┐  Com/Il    ┌──────────────┐
 │ ACC_01 (0x109)│──generic MO──▶  │ *(a9+0x3ec) ACC-request struct             │──sig 8/9/10─▶│ TSK_02 (0x10C)│─▶ ESP
 │  MO#59  radar │   RX engine     │   ▼                                        │  FUN_9d0ca │  Verzoeg_Anf │  (decel+hold
 │  accel/hold/  │   (table decode)│ FUN_801455ae  ACC/ESP decel coordinator    │            │  +TSK_Status │   +status)
 │  status       │                 │  (gate d000a454==2)                        │            └──────────────┘
 │               │                 │   → d0005f20/d0005d00 decel  (±500000 rail) │  Com       ┌──────────────┐
 │ ACC_05 (0x10D)│──validity gate─▶│   → d000ab01 ACC state (0..3)              │──sig 5/6/7─▶│ TSK_04 (0x10E)│─▶ gw
 │ ESP_05 (0x106)│  FUN_800981cc   │   ▼                                        │            │ Status_GRA_  │   (status+
 │  (feedback)   │                 │ FUN_8014322e  ACC→TSK decel bridge          │            │ ACC_02, gear │    gear)
 │               │                 │   ▼         FUN_801418ea accel ctrl          │            └──────────────┘
 │ mode: d000a3c1│──FUN_802c806e──▶│ FUN_80140922 TSK_02 handler (mode-mux)     │  Com       ┌──────────────┐
 │  →  d000a454  │  (1=GRA 2=ACC)  │   → d00082ae/ce/d0/8302, a343/a344/a35c    │──packer────▶│ TSK_01 (0x10A)│─▶ gw
 └───────────────┘                 │ FUN_8014469a status coordinator (+80143a68)│  80143a68  │  Status_AB   │   (24b status
                                    └──────────────────────────────────────────┘            │  +amax       │    +max accel)
                                                                                             └──────────────┘
```

## The spine (verified end-to-end) [C]
```
ACC_01 (0x109, MO#59)
  → FUN_80099600            generic per-MO RX dispatch (CAN msg-RAM *(a9+0x370); descriptor DAT_d0009330/d0013e64)
  → *(a9+0x3ec)             ACC-request struct (decoded by the generic table engine — flash sig-descr tables
                            DAT_800455a0/8003debc/8004556f/800441f8; NOT a hand-coded unpacker)
  → FUN_801455ae            ACC/ESP decel coordinator — gate d000a454==2 — writes decel d0005f20/d0005d00,
                            state d000ab01, + FUN_80145c88 → ACC-active flag d000a367
  → FUN_8014322e            ACC→TSK decel bridge (reads d0005f20 + d000a454 + d000ab01; interp FUN_8007c10c)
  → FUN_801418ea / 801434de accel/decel controller (internal ±500000 authority rail; PT1 filter FUN_8007c10c)
  → FUN_80140922            TSK_02 signal handler (mode-mux → shadows d00082ae/ce/d0/8302, d000a343/a344/a35c)
  → FUN_8009d0ca → Com      generic Com bit-pack + E2E → TSK_02 (0x10C) wire bytes
Parallel TX: FUN_8014469a (+FUN_80143a68) → TSK_01 Status_AB (d000f828/29/2a);  FUN_801455ae → TSK_04 status (d000ab01)
```

## Encoding conventions
| domain | encoding | notes |
|---|---|---|
| ACC_Sollbeschleunigung (ACC_01 24\|11) | res **0.005 m/s²**, offset **−7.22** | radar target accel; negative half = decel request |
| TSK_Verzoeg_Anf (TSK_02 56\|8) | res **0.024 m/s²**, offset **−3.984** | decel out; byte 0x00 = −3.984, saturates |
| TSK_amax_moeglich (TSK_01 48\|9) | res 0.024, offset −2.016 | max achievable accel |
| internal accel/decel authority (d0005f20/d0005cd0/cf4) | s32, **±500000 = ±5.0 m/s²** (≈1e-5 m/s²/LSB, **[I]** on scale) | rail clamp `0xfff85ee0` = −500000 |
| ego speed / gap terms (d00082ce/d0) | clamped to `[1000,10000]` | approach/time params |

---

## 1. INPUT — ACC_01 RX → ACC-request struct [C generic / G per-signal]
- **ACC_01 (0x109, MO#59)** is received by the **generic MO dispatch loop `FUN_80099600`**, which walks the
  external controller's message-RAM (`*(a9+0x370)`, per-MO index `DAT_d0013e64[MO]`, control `DAT_d0009330[MO]`).
  The 8 payload bytes are held **C_CAN-style as parallel per-byte arrays indexed by MO** — there is no
  contiguous "8 bytes of ACC_01" copy in the C. **[C]**
- **Signal decode is table-driven.** No hand-coded bit-unpacker exists (exhaustive search: no `&7)<<8` 11-bit
  split, no byte-7 combined hold/status decode, no `0.005`/`−7.22` literal in a CAN context). Bit
  offsets/lengths/destinations live in the flash signal-descriptor tables the generic engine indexes
  (`DAT_800455a0`, `DAT_8003debc`, `DAT_8004556f`, `DAT_800441f8`). **[C that it's table-driven]**
- **The decoded ACC request lands in the struct at `*(a9+0x3ec)`** [I]: byte flags at `+0x20..+0x24`
  (ACC status / Anhalten / Anfahren / enable-class — `+0x21==0` and `+0x24` drive the ACC-active flag
  `d000a367` in `FUN_80145c88`), s16 fields at `+0x10..+0x34` (target-accel / thresholds / gradient limits).
  **Live-signal vs calibration fields are interleaved in this struct and could not be cleanly separated
  without resolving `a9`** — so individual ACC_01 signals are deliberately *not* assigned specific
  `d000xxxx` addresses here (that would be a guess). **[G]**
- **Trust gate** = the presence/timeout accessor `FUN_800981cc(id)` (`0` = fresh, `1` = timed-out; see
  `can_signal_map.md`). The coordinator gates on neighbour handles (ACC_05 `0x10d`, TSK_04 `0x10e`, and a
  cluster `DAT_80028bb4/baa/bb6/…`), not on the ACC_01 handle directly. **[C]**
- **E2E** is handled generically (rolling counter `DAT_d000b729`→per-slot; checksum seed for 0x109 = 0x08).
  No per-message seed-0x08 compare surfaced as a literal — generic per-id E2E callback. **[G on exact site]**

## 2. MODE SELECT — the GRA/ACC master mode `d000a454` [C]
The whole TSK cluster is gated by the master-mode byte **`DAT_d000a454`**, set by **`FUN_802c806e`** from the
ACC master state **`DAT_d000a3c1`** (written by the ACC state machine `FUN_800accac`, whose state byte =
`abStack_74[0x1b]` from the state-machine step `FUN_800abc46` over descriptor `0x8003f374`):

| `d000a3c1` | `d000a454` | meaning |
|---|---|---|
| 1 | **1** | GRA-type cruise |
| 2 | **2** | ACC/DCC-type active |
| 3 | **2** (+ `d000a453`=1) | ACC "extended" |
| else | 0 | ACC inactive |

`d000a454` is *the* linking variable — it gates `FUN_801455ae` (`==2`), `FUN_80140922` (`==1`/`==2`),
`FUN_8014469a`, `FUN_801434de`, `FUN_801405d4` (`∈{1,2}`). Directly analogous to the Simos8.5 `a453/a454`
GRA-vs-ACC pair.

**Actively-regulating gate:** `DAT_d000a361` (companion `a362`), values `1`/`2`/`5`; **`∈{1,5}` = ACC
actively regulating** — the exact analog of Simos8.5's `b28e∈{1,5}`. It gates the accel pass-through
(`FUN_801434de`, `FUN_8014469a`). **[C]**

## 3. REQUEST FORMATION + the decel authority  ⭐ (openpilot decel lever) [C mechanism / G addresses]
- **`FUN_801455ae` = the ACC/ESP decel coordinator** (also the TSK_04 producer). Reads the `*(a9+0x3ec)` ACC
  request, gated `d000a454==2`, and emits the internal decel authority as **`DAT_d0005f20`** and
  **`DAT_d0005d00`** (s32 internal units). **The negative rail clamp is `0xfff85ee0` = −500000**
  (`801455ae.c:247-248, :346-347`, and `iVar9=-500000` at `:289`). **[C]**
- The ±rails are set in **`FUN_801434de`**: `DAT_d0005cd0 = +500000` (accel), `DAT_d0005cf4 = −500000`
  (decel) (`801434de.c:26-27`). At the inferred 1e-5 m/s²/LSB internal scale this is **±5.0 m/s²** — the
  internal decel authority ceiling. The CAN signal `TSK_Verzoeg_Anf` then saturates at **−3.984 m/s²** at the
  Com layer (its 8-bit range), so the effective on-wire decel floor is −3.984 unless both the internal rail
  and the signal range are changed — structurally the same two-stage clamp as Simos8.5 (curve/rail then
  packer floor). **[C on −500000; I on the m/s² scale]**
- **`FUN_8014322e` = the ACC→TSK decel bridge**: reads `d0005f20` + `d000a454` + `d000ab01`, runs the interp
  helpers `FUN_8007c10c`/`FUN_8007bfec`, and feeds `FUN_80140922`. **`FUN_8007c10c` is a first-order PT1 lag
  filter** (IIR: `new = old + (in−old)·(1−k)`, coeff from table `&DAT_80041198`) — the decel setpoint is
  *filtered*, not hard-clamped, on this hop. **[C]**
- **`FUN_801418ea` = the ACC longitudinal/accel controller**: the decel *shaping* here is **24× map lookups
  (`func_0xc00004ca`/`func_0xc0000638`) indexed off the ACC cal struct `*(a9+0x3dc)`** — the MED17 analog of
  Simos8.5's flat `IP_AC_SP_MIN_CRU` decel-limit kennlinie. **[C that they exist]**
- **⚠ The openpilot lever is here but NOT yet addressable.** Every calibration in this path is reached
  through `*(a9+0xNNN)` cal-struct pointers (`0x3dc`, `0x434`, `0x3e4`, `0xc28`, `0xc30`) — **no absolute
  `0x8038xxxx` cal literal appears in any of these functions**, and there is no hardcoded decel-floor
  literal (unlike Simos8.5's `0x6db1`). To produce editable flash cells for the decel clamp, **`a9` must be
  resolved first** (§7). **[G]**

## 4. TSK_02 (0x10C) OUTPUT — decel / hold / status [C shadows / I signal map / G wire bytes]
Handler **`FUN_80140922`**, mode-muxed on `d000a454`, writes the TSK_02 signal-shadow group:

| shadow | GRA (`a454==1`) source | ACC (`a454==2`) source | consumed by | signal (best-effort) |
|---|---|---|---|---|
| `d0008302` | `min(d0008c9e, 0x7fff)` | `*(a9+0xc30)+0x1a` | `8014469a` | positive setpoint (not the signed decel) |
| `d00082ae` | `d000864c` | `d000830a` | `801418ea` | accel/setpoint floor |
| `d00082ce` | `d000864e` | `clamp(d000830c,1000,10000)` | `8014469a` | gap/time param |
| `d00082d0` | `d0008650` | `min(clamp(d000830e,1000,10000), wheelspeed)` | `801418ea` | approach/gap-decel term |
| `d000a343` | `d000a7e7` | `d000a368` OR'd digital-input bits | `801418ea` | **status/permission byte** |
| `d000a344` | `d000a7e7 & 3` | enum {0,1,3,4} from present-gates | `8014469a` | **TSK_Status (16\|2)** [I, med-high] |
| `d000a35c` | `d000a7ef` | standstill bit `*(a9+0xc30)+0x13`, wheelspeed-gated | `801434de` | **TSK_Anhalten (12\|1)** [I, med] |

The GRA-mode sources (`d0008c9e`, `d000864c/e`, `d0008650`, `d000a7e7/ef`) are produced by the primary
longitudinal controller **`FUN_802cb15e`**; the ACC-mode sources (`d000830a/c/e`) by **`FUN_800b1136`**
(from the `d00084xx` setpoint block written by `FUN_8008b17c`). Both feed the *same* TSK_02 shadows.

- **`TSK_Verzoeg_Anf` (56|8, the decel byte) is NOT one of these shadows in a signed-decel form** — the decel
  authority is computed in the accel domain (`d0005f20`, ±500000) by `801455ae`/`801434de`/`801418ea`, and a
  **generic Com source converts it to the 0.024/−3.984 byte at serialize time**. Which internal var the Com
  config binds to 56|8 is not visible in the C. **[G]**
- **`TSK_Anhalten` (12|1, hold)** ← `d000a35c`. In ACC mode it is a **standstill-detected bit** (wheelspeed-
  gated), turned by `801434de` into the standstill request `d000a365` **gated on `d000a361∈{1,5}`**. The raw
  relay edge from the incoming ACC_01 `ACC_Anhalten` bit was **not pinned** (the 0x109 handle only feeds a
  presence collector; hold here is derived from ACC-state + standstill rather than a visible direct RX-bit
  relay). This is the one place the MED17 story is *less* resolved than Simos8.5's UPDATE-64 relay chain. **[G]**
- **`TSK_Radbremsmom` (40|12)** and **`TSK_Standby_Anf_ESP` (52|1)**: no dedicated computation — consistent
  with the Simos "constant 0 / not used" finding. **[I]**

## 5. TSK_04 (0x10E) OUTPUT — ACC status + gear [C for status / G/LOW for gear]
Producer **`FUN_801455ae`** (gated `d000a454==2`; references TSK_04 handle `DAT_80028bd0`).

| dbc signal | source shadow | detail | conf |
|---|---|---|---|
| **TSK_Status_GRA_ACC_02 (62\|2)** | **`DAT_d000ab01`** (0..3 enum) | `801455ae` switch(ab01) cases 0/1/2/3; **`ab01=3` (fault/not-possible) forced when the MO#67 present-gate `FUN_800981cc(0x10e)` fails**. Remapped by `FUN_80199344`: ab01 1→3, 2→4, 3→7 into `d000a13d`. Direct parallel to Simos8.5 `STATE_DCC`. | **HIGH** |
| TSK_ax_Getriebe (18\|9) | `d0005f20` / `d0005d00` | accel-domain outputs of the gear state machine | MED |
| TSK_zul_Regelabw (12\|6) | — | not isolated in `801455ae` outputs | G |
| TSK_Wunsch_Uebersetz (27\|10) | `d00078d8/da` ratio bounds | gear-ratio request | LOW |
| TSK_Freig_WU (37\|1) / TSK_Limiter_aktiv (38\|1) | `ab02`-region / limiter flags | discrete | LOW |

## 6. TSK_01 (0x10A) OUTPUT — 24-bit status + max accel [C for status / G for amax]
No handler is keyed on the TSK_01 handle (`DAT_80028bd8` appears only in the presence collector
`FUN_8017a760`). TSK_01's payload is produced by the shared status coordinator **`FUN_8014469a`**:

| dbc signal | source shadow | detail | conf |
|---|---|---|---|
| **TSK_Status_AB (16\|24 = 3 bytes)** | **`d000f828 / f829 / f82a`** (= `a34b/a34c/a34d`) | `8014469a` builds each byte via **`FUN_80143a68`** (8-bool→byte packer, called 5×); upstream bits from `80140922`'s `a343/a344/a346/a349` + present-gates. Three consecutive status bytes exactly fill the 24-bit field. | **MED-HIGH** |
| TSK_amax_moeglich (48\|9) | — | max achievable accel; origin is the powertrain torque model, upstream of the TSK cluster; candidates `d0008306/d0008308` unconfirmed | **G** |

TSK_01 (24-bit status view) and TSK_02 (2-bit status view) **share the same status-byte producers**
(`80140922` `a343/a344/a346/a349`) — one status word, two projections.

## 7. Editable levers (openpilot) — `a9` RESOLVED, cals now addressable
**`a9` is solved** (boot emulation `research/emulation/EmulA9.java`): `a9 = 0xa0103464` = uncached
alias of the **cal-object table `0x80103464`**, so the ACC code indexes that table (`*(a9+off)` = cal object
`off/4`). It's now in `ecu.conf` `BASEREGS`; `reproduce.sh` folds every ACC `*(a9+off)` to a concrete cal
address. Full detail: `maps/a9_resolution.md`. Min-speed + creep detail: `maps/min_speed_l2.md`.

| goal | lever (where) | status |
|---|---|---|
| **raise the brake decel floor** | decel-shaping maps in `FUN_801418ea` = cal obj **#247 `0x803b4834`** (via `a9+0x3dc`), fields to `+0x6e4`; internal rail `−500000` in `FUN_801434de` (`d0005cf4`); on-wire floor = `TSK_Verzoeg_Anf` 8-bit range (−3.984) in Com config | **addressable** (cal obj #247 / kennlinie block #269 `0x803b5bfc` via `a9+0x434`) |
| **ACC min-speed permit (self-recovering)** | **cal #208 EGAS-L2 permit floor `0x80389809`=15 + `0x8038980e`=7 (both →0)** — the ONE genuine ACC min-speed gate, gated on cruise-active. SELF-RECOVERING: below the floor the ECU withholds the ACC command (no fault), resumes at speed>15 (MED17 field-confirmed). NOT a key-off-on lockout (that was the Simos). Functional L1 cells are behavioural, NOT partners. | **SOLVED**; see `maps/l2_monitors.md` |
| **3 km/h creep gate** | `0x803b88ae` / 3.01 km/h literal | **leave stock — diagnostic flags (`d000f73c`/`d0002a14`), not control gates; no hardcoded low-speed barrier exists (unlike Simos8.5's `8013ef46:258`=7.81 km/h). See §6 + `min_speed_l2.md` Q1b** |
| ACC/GRA mode | `d000a3c1`→`d000a454` (`FUN_802c806e`) | runtime state, not a cal |
| hold/standstill | `TSK_Anhalten` ← `d000a35c` → standstill req `d000a365` (`801434de:85-93`, gated `d000a361∈{1,5}`, hold from `ACC_Anhalten`) | openpilot commands hold via ACC_01; drive-off/anfahren `801405d4` follows commanded accel (stock OK) |

**Openpilot low-speed control needs no creep-gate edit:** the hold/decel path is cal-map-driven with no
hardcoded floor, hold is the `ACC_Anhalten`→`TSK_Anhalten` relay openpilot drives, and the stock anfahren
(`801405d4`, cal `*(a9+0x3d8)`) shapes drive-off following the commanded accel. Sub-floor operation depends
on the EGAS-L2 monitor floor + openpilot supplying its own request, not the creep gate (`min_speed_l2.md` Q1b).

## 8. Open threads / uncertainties
1. **Upstream ACC-enable arbitration.** The engage precondition (`800accac`) is a generic state-vector engine;
   `a3c1` (master ACC mode) = pass-through of condition field `0x1c` of a validated condition vector
   (`d0009b63` runtime / `803def94` flash), with **no speed floor** (mode arbitration only: off/GRA/ACC/ACC-ext;
   see `maps/engage_state.md`). Open: the upstream inputs that pack `cond[0x1c]=2` (ACC-enable arbitration, one
   hop above the vector) — [G]. (`a9` base = `0xa0103464` cal-object table; see §7 + `a9_resolution.md`.)
2. **Wire byte↔signal offsets** — in the flash Com PDU/signal-descriptor tables (`DAT_800441f8`,
   `DAT_d0006e48`, decoder tables `DAT_800455a0`/`8003debc`), not in code. A table-decode job, not a
   decompile job.
3. **`TSK_Verzoeg_Anf` internal source var** — which `d0005fxx`/`d00082xx` the Com config binds to 56|8.
4. **ACC_01 `ACC_Anhalten` → `TSK_Anhalten` ingress edge** — the derived-standstill path is found; the direct
   RX-bit relay (if any) is not.
5. **`TSK_amax_moeglich` source** and the TSK_04 gear signals (`zul_Regelabw`, `Wunsch_Uebersetz`).
6. **Cyclic TX period** — producers run from an unresolved OS function-pointer task table (≈20 ms by Simos
   analogy, not statically confirmed).

## Function inventory (this trace)
| addr | role | conf |
|---|---|---|
| `FUN_80099600` | generic per-MO RX dispatch | C |
| `FUN_800981cc` | msg validity/timeout accessor (0=fresh) | C |
| `FUN_800accac` / `FUN_800abc46` | ACC master state machine → `d000a3c1` | C(writer)/I(sem) |
| `FUN_802c806e` | `a3c1`→`a454` GRA/ACC mode select | C |
| `FUN_801455ae` | ACC/ESP decel coordinator + TSK_04 producer (decel `d0005f20`, state `ab01`, rail −500000) | C |
| `FUN_80145c88` | ACC-active flag `d000a367` | C |
| `FUN_8014322e` | ACC→TSK decel bridge | C |
| `FUN_801434de` | decel/standstill stage (±500000 rails, `d000a365` hold) | C |
| `FUN_801418ea` | ACC accel controller (decel-shaping maps off `*(a9+0x3dc)`) | C |
| `FUN_8007c10c` | PT1 lag filter | C |
| `FUN_802cb15e` | GRA-mode TSK_02 source controller | C |
| `FUN_800b1136` / `FUN_8008b17c` | ACC-mode TSK_02 source controller / setpoint computer | C/med |
| `FUN_80140922` | TSK_02 signal handler (mode-mux → shadows) | C |
| `FUN_8014469a` + `FUN_80143a68` | status coordinator + 8-bool→byte packer → TSK_01 Status_AB | C |
| `FUN_80199344` | `ab01`→`a13d` status remap (1→3,2→4,3→7) | C |
| `FUN_8009d0ca`→`FUN_800bffba` | generic Com set-signal / bit-packer | C |
