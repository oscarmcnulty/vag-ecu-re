# ACC longitudinal flow: ACC_01 → TSK signals (Simos8.5 8R0907551F)

End-to-end map of the engine ECU's ACC/cruise (VHSC/DCC) longitudinal path — from the received ACC
request to the deceleration + status sent to the brake (ESP) — including the **−3.0 m/s² decel clamp**
and the **15 km/h minimum-speed floor**. Built from decompile tracing + Funktionsrahmen (FR) cross-ref +
firmware reads (RESULTS.md UPDATES 54–58; 5-agent investigation 2026-07-11). Addresses are load base
0x80000000; `0xa00xxxxx` = uncached mirror of flash `0x800xxxxx`; file offset = `addr & 0x1FFFFFFF`.

## Block diagram
```
 CAN RX (powertrain bus)                 ENGINE ECU (Simos8.5)                         CAN TX
 ┌───────────────┐   d0007baa    ┌───────────────────────────────┐   Ramd0007cb8   ┌──────────────┐
 │ ACC accel req │──10bit accel─▶│ 8013c5d4 request formation     │──=AC_SP_CRU_ ──▶│ 80137a00     │
 │ (MO 0x8a0 →   │               │  + −3.0 decel-limit KENNLINIE  │   BRAKE_CTL     │ TSK_02 (0x10C)│─▶ ESP
 │  801383fc)    │               │  (0xa005b71c, min @ :418)      │                 │  byte8=Verzoeg│
 │ status/enable │               │ → Ramd0007c9a → 8013ef46 →     │                 │  _Anf (decel) │
 │ (MO 0x600 →   │──a4xx bits───▶│   Ramd0007cae → Ramd0007cb8    │                 └──────────────┘
 │  80106db8)    │               │                                │   d000d9c7      ┌──────────────┐
 │ VS_CAN speed  │──d5618──▶d644─│ 80102f60 L2 monitor+diag,      │──STATE_DCC ────▶│ 8011e9ce     │
 │               │      =da54    │  15km/h floor (cal+0x14f/152), │   d8ee→status   │ TSK_04 (0x10E)│─▶ gw
 └───────────────┘   1/128 km/h  │  801eca44 status, d8ce engage  │                 │  byte8=Status │
                                 └───────────────────────────────┘                 └──────────────┘
```

## Encoding conventions (critical — prior sessions missed the −3.0 for this reason)
| domain | encoding | 0 m/s² | −3.0 | −3.984 | +2.112 |
|---|---|---|---|---|---|
| internal accel setpoint (d0007cxx, Kennfeld cells) | u16 **850e-6 m/s² OFFSET-BINARY** `phys=(raw−0x8000)·850e-6` | 0x8000 | **0x7237** | 0x6db1 | 0x89b6 |
| TSK_Verzoeg_Anf CAN byte | u8, res **0.024 m/s²**, offset | 0xA6 | 0x29 | 0x00 | 0xFE |
| ego speed (d000d644 / d000da54) | u16 **1/128 km/h** (128 cnt = 1 km/h) | — | — | — | — |
| VS min cals (C_VS_MIN_*) | u8 km/h, compared `da54 ≤ cal·0x80` | — | — | — | — |
| ACC engine-torque decel (0x80079982) | s16 0.005 m/s² | — | — | — | — |

---

## 1. INPUT — CAN RX → internal accel request
- **ACC_01 (0x109, DCC_1)** dedicated mailbox handler `canmo_109_ACC_01` (0x8011e8f8) only STAGES the raw
  8 bytes to `d000d40a` + sets flag `d000d408`; no static decoder — it is relayed via AUTOSAR-Com.
- The ACC longitudinal INPUT is decoded by the **RX poll loop `80108cc4`** from **three distinct receive frames**,
  each identified (UPDATE 65) by its E2E seed `= (id>>8)^(id&0xff)` + a bit-for-bit dbc match. **acc_flow's older
  "ACC_01 for everything" labels were WRONG** — corrected here:
  - **handle 0x240 → `801383e8`** (seed **0x08** = **DCC_1 / ACC_01, 0x109**): `d0007bac ← ACC_Sollbeschleunigung`
    (24|11, 0.005 m/s²), `a7ae ← ACC_Anhalten` (57), `b06a ← ACC_Dynamik` (58). *The radar/gateway ACC command;
    Gateway_B8, present on the car.* (See the dedicated subsection below for the hold bit.)
  - **handle 0x8a0 → `801383fc`** (seed **0x0C** = **DCC_5 / ACC_05, 0x10D**): `d0007baa ← ACC_Momentenanforderung`
    (16|10, a **torque/moment** request 0-1021, NOT an accel) = `min(cal_d000b0d4·raw·16, 0x7fff)`; also
    `a3ba ← ACC_Betaetigung_EPB` (60), `b057 ← ACC_Status_ACC` (57|3), `b056 ← ACC_StartStopp_Info` (44|2).
    *Gateway_D4C7; memory `vw-mlb-checksums` says NOT seen on stock B8 bus0 — likely dormant on the B8 (decode gated on
    message-present `d0006980 & 0x20000000`).* `d0007baa` read by `8013c5d4:734` (b28e∉{1,5} branch).
  - **handle 0x600 → `80106db8`** (seed **0x07** = **ESP_05, 0x106** — an ESP→engine FEEDBACK frame, not an ACC
    command): `d0007c3e ← ESP_Bremsdruck` (16|10, raw100=0bar; the "(raw−100)·3" is the internal rescale, NOT read by
    8013c5d4); `a4eb ← ESP_Verz_TSK_aktiv` (27), `a4f5 ← ESP_Konsistenz_TSK` (29), `a4e4 ← ESP_Autohold_Standby` (35),
    `a4e9 ← ESP_Autohold_aktiv` (56), `b1ec ← ESP_StartStopp_Info` (42|2), `a4f1 ← ESP_Status_Bremsdruck` (61). So the
    `a4e4…a4f6` "cluster" is **ESP status feedback**, not "ACC enable/override" — it closes the engine↔ESP brake loop.
- FR: ACC_01=DCC_1 (0x109), ACC_05=DCC_5 (0x10D), ESP_05=TCS5 (0x106) — all in the FR received-message table.
  ACC_Sollbeschleunigung = `CAN_AC_DE_DCC_UP`, res 0.005 m/s² (FR §48.24). This firmware is the **D4/C7 baseline**.
- **Which accel is operative is a B8-vs-D4C7 question (needs a bus capture):** `d0007bac` (ACC_01 Sollbeschleunigung,
  definitely received) vs `d0007baa` (ACC_05 Momentenanforderung, likely dormant on B8). The hold path is unaffected
  (Anhalten is unambiguously ACC_01/0x109 byte7·bit1). Do NOT chase the accel→torque converter statically (it is
  table-driven — memory `openpilot-integration-goal`); resolve on the bench.
- **Engage gates** (checked in 8013c5d4): `d000ad0f` master compute-enable (`8011ac80`); mode
  `d000b28e ∈ {1,5}`; brake-control substate `d000b296==2`; driver-override selector `d000b29c==0`
  (`80141248` from driver-request flags a73x); plus ESP feedback bits from ESP_05 (the `d000a4xx` cluster).
- **Note (corrects older maps):** `801dec08` is NOT an ACC input decoder — it writes the `d5c0–d6ff`
  mirror block from *internal engine state* (e.g. `d000d606`=engine output mirror; `d000d644`=ego speed from `d5618`).

### ACC_Anhalten / setpoint ingress — ACC_01 (0x109), decoder `801383e8` (UPDATE 64, confidence HIGH)
The stop/hold + setpoint signals come on a **different** frame from the accel: **ACC_01 = DCC_1 = CAN id 0x109**
(sender Gateway_B8), decoded by **`801383e8`** (RX-poll `80108cc4`, **mailbox handle 0x240**, cal gate
`80043bc6&0x100`). It validates MLB E2E **seed 0x08** (`XOR-all-8==8`) + rolling counter (byte1 low nibble) before
writing, on the E2E-OK branch: `a7ae=(byte7>>1)&1`=**ACC_Anhalten**, `b06a=(byte7>>2)&3`=ACC_Dynamik,
`d0007bac=(byte4&7)<<8|byte3`=setpoint. The wire mapping is **triple-confirmed** — firmware seed 0x08 = opendbc
0x109 seed; FR `LCAN_DCC1_8_1 → LV_CAN_VEH_STOP_REQ_DCC = ACC_Anhalten` (DCC_1 byte8·bit1); opendbc `BO_ 265 ACC_01`
`ACC_Anhalten:57|1` (byte7 bit1), `ACC_Dynamik:58|2`, `ACC_Sollbeschleunigung:24|11`. The old "gateway-repack"
caveat is resolved: the gateway re-signs the frame AS ACC_01 (seed 0x08), so the validated buffer = ACC_01's
on-wire layout, byte-for-byte.

## 2. REQUEST FORMATION + the −3.0 DECEL CLAMP  ⭐ (openpilot decel lever)
Chain (all pinned): `d0007baa` → **`8013c5d4`** (acc_brake_request_formation) → `Ramd0007c9a` →
CRUC_MG005 state fns (`8013e3f8`/`8013e47c`) → `Ramd0007cae` → **`8013ef46`** → **`Ramd0007cb8`**
(= FR `AC_SP_CRU_BRAKE_CTL`) → packer **`80137a00`** → `TSK_Verzoeg_Anf` (TSK_02 byte 8).

**The −3.0 clamp = a flat decel-limit Kennlinie in calibration data:**
- `8013c5d4:220` reads kennlinie **values `0xa005b71c`, axis `0xa005a4c4`** (N=6), input =
  `Ramd0007ce8` = first-order-filtered `Ramd0005618` (vehicle-speed class). **All 6 y-cells = −3.000 m/s²
  (0x7237) — completely FLAT** → output `uRamc00010b2` = the negative (decel) authority.
- `8013c5d4:418` `Ramd0007c9a = min_u16_800a4bbc(uRamc00010fc, uRamc00010b2)`. **⚠ `min_u16_800a4bbc`
  is a Ghidra MISNOMER — its body returns the MAX** (`p1·(p2<p1)+p2·(p2≥p1)`; verified numerically:
  `800a4bbc(0x6f00,0x7237)=0x7237`, i.e. a harder request −3.6 is clamped UP to −3.0). So the line is
  `Ramd0007c9a = max(request, 0x7237)` = **truncate braking to −3.0** (any raw<0x7237 → −3.0) — the
  textbook clamp, matching the on-car "openpilot <−3.0 → truncated to −3.0". *(The plain `min_u16` IS a
  genuine min — do not confuse; an adversarial-review pass tripped on this name and wrongly called the
  lever backwards.)* Because the curve is flat, the cap is **−3.000 speed-independently** on this path.
- **The two curves are the cruise-mode selection** (`8013c5d4:211`, `d000a757 = LV_DCC_ENA`, from coding
  cell 27 STATE_DCC_TYP): `a757=0` → **GRA** curve `0xa005b71c` (`IP_AC_SP_MIN_CRU`); `a757=1` → **Basic-ACC**
  curve `0xa005b728`/axis `0xa005a4f4` (`IP_AC_SP_MIN_DCC`, −3.0×5 then 0). There is NO third
  (Follow-to-stop) curve — F2S is not compiled into this firmware (UPDATE 60). Both curves overlap into the
  contiguous **11× `0x7237` cluster 0x5b71c–0x5b730**, so the editable range covers both modes; for an
  ACC-coded car the *operative* cells are the `0x5b728` group.
- The packer `80137a00` then applies a **hard clamp `[0x6db1=−3.984, 0x89b6=+2.112]`** (byte saturates
  to 0x00 / 0xFE) — this is the CAN signal's outer range, below the −3.0 curve.
- **Editable cells to raise the −3.0 clamp** (u16 LE, `raw=0x8000+phys/850e-6`; −3.984=0x6db1):
  primary `file 0x5b71c … 0x5b728` (7 cells, dominant path); if alt-mode reachable also `0x5b72a…0x5b730`
  (4 cells). **Floor achievable without code edits = −3.984** (the packer's `0x6db1` literal at
  `80137a00.c:~121`); to go below, also lower that literal. Recompute cal checksum (`core/checksum`).
- Edit direction (CONFIRMED): since `:418` is `max(request, cell)`, lowering the cells (0x7237→0x6db1,
  more negative) **relaxes** the cap (allows harder braking, down to the packer floor −3.984); raising
  them tightens it. This is the correct openpilot lever.
- Remaining caveat (from adversarial review, valid): the `c9a→cb8` passthrough is **CRUC-state-dependent**.
  In states `8013e3f8`/`8013e47c`/`8013e13c` it passes through; but **`8013e674` REPLACES it**
  (`Ramd0007cae = −1−uRamc0001134` or `= cal uRam80043062`), and `8013ef46:955-956` only passes
  `cae→cb8` when decel-enable `d000a58c≠0` (else `cb8=0x8000`=0). So the −3.0 cap is the *normal active-brake*
  behavior, not literally every state. (Prior UPDATE 57 mislabeled the 8013ef46 kennlinien as the decel
  setter — those write secondary signals `Ramd0007cba/cbc`; the decel value is the 8013c5d4:219-221/418 path.)

## 3. VEHICLE SPEED + the 15 km/h MINIMUM-SPEED FLOOR  ⭐ (openpilot min-speed lever)
- **Ego-speed variable `DAT_d000d644`** = `clamp(d5618·32/25)` (`801dec08:23`; `d5618`=wheel-speed avg
  from VS_CAN via `80101a44`). Monitor copy **`DAT_d000da54` = d644** (`801efbb8:415`).
  **Scale = 1/128 km/h** (128 counts = 1.00 km/h) — proven by ~15 speed cals/immediates all landing on
  integer km/h at 1/128 and junk at 0.01 (e.g. cal+0x18c=1920=15.0, +0x192=128=1.0, da54<0x80=1 km/h).
- **`C_VS_MIN_CRU_MON` = 15 km/h** (the L2 monitor floor): u8 at **`cal(0x800793a0+0x14f)=15`
  (flash 0x800794ef)** and **`+0x152=15` (flash 0x800794f2)**, compared `da54 ≤ cal·0x80` (≤1920 = ≤15 km/h)
  in **`80102f60:1583`** (→ debounce `d000d79a` → `d88b` bit5) and **`:1645`** (DCC-masked → `d000d8ab` →
  `d7a7`). FR ch.14.16.5 (p2196/2202): `VS_MON < C_VS_MIN_CRU_MON` SETs SR-latch `LV_CRU_MON_ACT_MON` →
  cruise off; "derived from C_VS_MIN_CRU_OFF − 2 km/h". **This is the 15 km/h floor sought since UPDATE 53.**
  *(NB: the A2L (`maps/simos85.a2l`) has a `C_VS_MIN_CRU_MON` at file 0x456C0/0x456BD (also =15) — that
  is the **EGAS-L2-monitor twin** (referenced by `egas_l2_monitor_cal_init@800a0c9c`, a different cal base),
  NOT the value compared to vehicle speed here. To move the cruise floor edit **0x800794ef/0x800794f2**;
  the 0x456C0 twin may need matching to avoid an L1/L2 monitor mismatch — check, don't assume.)*
  Caveat: the base `0x800793a0` is INFERRED via the runtime pointer `iRam80090f80` (no static xref); all
  +offset values are semantically consistent, but verify the base if an absolute edit depends on it.
- **`C_VS_MIN_CRU` (functional engage floor) = 3.00 km/h**: `cal(0xa007a204+0x66)=384` (flash 0x8007a26a),
  gates `d644` in the cruise PI controller `801e9b86:301`.
- **3.00 km/h ACC creep/enable gate = `cal(0x800793a0+0x196)=384`** (flash 0x80079536), compared
  `384 ≤ da54` at `80102f60:725` → `d88c` bit4, gating fault escalation. **This is the old `0x180=384`
  immediate — under the confirmed 1/128 scale it is 3 km/h, NOT 15** (resolves the withdrawn UPDATE-53
  guess: d644 IS speed, but 0x180 = 3 km/h; the real 15 km/h is +0x14f/+0x152).
- To raise/lower the 15 km/h floor: edit u8 cals at flash **0x800794ef** and **0x800794f2** (both 15);
  the functional 3 km/h at 0x8007a26a / the creep gate at 0x80079536 (both 384) if needed. Checksum.

## 4. ACC STATE MACHINE + ENGAGE GATE
- **`d000d8ee` (ACC master state)** ∈ {0,1,2}, set in `80102f60:1191-1199`: `=0` if `d8cf≠0` (off);
  else `=(d8ce==0)+1` → **2 = engaged** (`d8ce==0`) else 1 = active.
- **`d000d8ce` = engage-INHIBIT word** (`80102f60:1188`, `= cal(+0x121=0xBF) & OR(8 bits)`): when any
  masked condition is set ACC cannot fully engage. Bits: b7=`d890.5 && d6ab==0`; b6=`d778` (mask-off);
  b5=`d890.5 && d6ac`; b4=`d67e`(=a4b2|a881); b3=`bVar19 && d890.7 && d8a8==0 && d776==0`; b2=`d8e3<2 &&…`;
  b1=`cal(+0x116/117) < d770`; b0=`d6a4 && !d893.0x40`. Conditions come from ACC-state byte `d890`,
  permission flags, and thresholds.

## 5. STATUS (TSK_Status_GRA_ACC) + the status-3 latch
- **`801eca44`** maps `d8ee` → 2-bit status `d91c/d91d` (`:66-81`): 0=nicht_verbaut, 1=aktiv,
  2=übersteuert (`d8ee==2 && d8e2.bit2`), **3=Fehler_GRA_ACC_nicht_möglich** (`d8ee==2 && !d8e2.bit2`).
- **status-3 trigger** (this CRU/AC-based coding, `CLF_CAN_CONF_FCT.Bit0=0`): any of the 13 cruise
  diagnoses latched at SYM_3 → `d000d8e0≠0` → `d744` (debounced latch, → `d8b4` gates recompute = KEY-CYCLE
  latch) → `d8e2.bit2=0` → 801eca44 → status 3, **when ACC engaged (d8ee==2)**. The fatal-DEACTIVATION
  path (`d8e0 & cal+0x178`) is dead (mask=0). The L2 plausibility monitor `800c553c` (−3.0 @0x80043514,
  0.001 scale) is DTC-isolated — NOT the status/functional path (UPDATES 55/56).
- Two status signals (both the same 0..3 enum): **TSK_Status_GRA_ACC_01** (TSK_02 byte3 = `STATE_CRU_CTL_CAN`
  via d91d/b28d) and **TSK_Status_GRA_ACC_02** (TSK_04 byte8 bits6-7 = `STATE_DCC d000d9c7` via 801e3f26).

## 6. OUTPUT — TSK messages
**Active decel packer = `80137a00` (TSK_02 / 0x10C)** — NOT 80137f2c. Selected in TX scheduler
`80106ed8:747` because `DAT_80043caf & 1 == 0` (cal=0x06, flash 0x43caf); 80137f2c is the alt coding
(never called, also gated off). Both read the same `Ramd0007cb8` + same clamp → the −3.0 lever is
packer-independent. Handles (0x680/0x8c0/0x20c0) are HW mailbox ctrl words, not CAN IDs.

### TSK_02 (DT_MNG_2, id 0x10C, 8B, 20ms) — builder 80137a00
| byte | bits | signal | source | encoding |
|---|---|---|---|---|
| 1 | 7-0 | TSK_02_CHK | computed | XOR ^0x0d |
| 2 | 3-0 | TSK_02_BZ counter | d000b0dd | 0..15 |
| 2 | 4 | **TSK_Anhalten** (hold/standstill) | **d000a58d** (←8013ef46, = a7ae when ACC active+coded) | **live pass-through of ACC_Anhalten CAN bit; 0 on stock only b/c B8 radar never asserts it — UPDATE 63** |
| 3 | 1-0 | TSK_Status_GRA_ACC_01 | d000b28d (STATE_CRU_CTL_CAN) | 0..3 (3=Fehler) |
| 3 | 7-2 | TSK_Fahrzeugmasse (+QBit) | d0007ce4/d0007b70 | |
| 6-7 | — | TSK_Radbremsmom | 0 ("not used" this variant) | 8 Nm/bit |
| 7 | 4 | TSK_Standby_Anf_ESP | 0 ("not used") | binary |
| 7 | 5 | TSK_Codierung_ACC | d000a79f | binary |
| 7 | 6 | TSK_Zwangszusch_ESP | d000a58f | binary |
| 7 | 7 | **TSK_Freig_Verzoeg_Anf** (decel ENABLE) | **d000a58c** | binary |
| 8 | 7-0 | **TSK_Verzoeg_Anf** (decel request) | **Ramd0007cb8** (AC_SP_CRU_BRAKE_CTL) | 0.024 m/s², 0xA6=0, clamp [0x6db1,0x89b6] |

### TSK_04 (DT_MNG_4, id 0x10E, 8B) — canmo 8011e9ce (copies node *d000d404+8..+0xf), payload 801e3f26
| byte | bits | signal | source |
|---|---|---|---|
| 2-3 | — | TSK_zul_Regelabw | 801e3f26 |
| 3-4 | — | TSK_ax_Getriebe | 801e3f26 |
| 5-6 | — | TSK_Wunsch_Uebersetz (0.0245/bit) | 801e3f26 |
| 5 | 6 | TSK_Limiter_aktiv | 801e3f26 |
| 8 | 7-6 | **TSK_Status_GRA_ACC_02** | STATE_DCC d000d9c7 |

- **TSK_01 (0x10A)**: byte8 = TSK_amax_moeglich (max achievable accel); carries no decel.
- **TSK_05 (0x111)**: NOT transmitted (Bit0=0; builder 80136794 has no callers).
- **Standstill/hold — TSK_Anhalten is a LIVE, gated pass-through of the incoming ACC_Anhalten CAN bit (NOT
  constant 0 — UPDATE 63 retracts the earlier "constant 0" read).** Full chain, every hop firmware-verified (UPDATE 64):
  **ACC_01/DCC_1 (0x109) byte7·bit1 (ACC_Anhalten)** →[`801383e8:94`, E2E seed-0x08 OK, RX-poll handle 0x240]→
  **`d000a7ae`** →[`8013ef46:937-943`, `a58d = a7ae` when the gate holds, else 0]→ **`d000a58d`** →[`80137a00:49/94`,
  TSK valid ad7a/a852]→ **TSK_02 (0x10C) byte2·bit4** →[TX `80106ed8:739-753`, cal caf&1=0 → mailbox 0x680]→
  gateway J533 (separate ECU) → ESP.
  - **The forward gate (`8013ef46`, what openpilot must satisfy):** `ad0f≠0` (master ACC compute-enable) AND
    `a757≠0` (LV_DCC_ENA — coded Basic-ACC; GRA a757=0 never forwards) AND `a5a8==0` AND **`b28e∈{1,5}`**
    (cruise actively regulating). NOTE (UPDATE 66): **`a5a8 = 0x80043caf & 1` is CAL-FIXED = 0 on the Q5** (sole writer
    `801abf64:21`), so that condition is guaranteed by calibration — not a runtime state openpilot manages. The runtime
    conditions reduce to: ACC compute-enabled, ACC-coded, and cruise actively regulating (`b28e∈{1,5}`).
  - `801a6134` (UPDATE 61's "sole a7ae=0 writer") is really `reset_flags_and_values` (init/timeout reset). TSK_Anhalten
    reads 0 on a stock car ONLY because the single-radar B8 ACC never asserts ACC_Anhalten (30 km/h floor) — the path
    is intact, unlike F2S (UPDATE 60, genuinely compiled out).
  - **Completeness (UPDATE 64):** TSK_Anhalten is the ONLY discrete engine-originated *hold* request.
    TSK_Zwangszusch_ESP (`a58f`, byte7·bit6 = `b28f∈{1,2}`) is a LIVE companion ESP-coupling *enable*, not a hold.
    TSK_Radbremsmom + TSK_Standby_Anf_ESP = constant 0 (FR "not used"). Engine originates no EPB vector (ACC_05/0x10D
    is RX-only). See UPDATE 64 for the ingress/egress detail; UPDATE 63 for the middle hop; UPDATE 61 for the TSK dataflow.
- **Stop-and-go / follow-to-stop — TWO architectures, engine is a FOLLOWER in both (UPDATE 66):**
  - **(A) F2S / SOFT_STOP** — only the F2S-SPECIFIC refinements are compiled out (the explicit wheel-brake-hold-torque
    `TQ_BRAKE_HLD`→`TSK_Radbremsmom`=const 0, the smooth-approach curve `IP_AC_SP_MIN_DCC_FOL_2_STOP` empty @0x5b734,
    `LV_DCC_ENA_FOL_2_STOP` stub). **BUT the ACC_01/Basic-ACC path itself DOES brake toward standstill** via the normal
    decel path: −3.0 authority to 0 km/h (both curves), `TSK_Anhalten` hold-relay, and standstill-regime management
    (mechanisms 2/3/4 are approach control/status, not hard floors — the 15 km/h monitor doesn't build `d8cf`). So a
    de-facto follow-to-stop is present; only the OEM F2S *mode* + wheel-brake-torque are absent. See UPDATE 66 Q2-followup.
    (RESOLVED 2026-07-27 — see `maps/cruc_state_machine.md`: `STATE_CRU_CTL` has **no ego-speed transition out
    of {1,5}** on the way down — its two speed terms are sub-flags only, and the `d0007e84` hysteresis is a
    high-side 1→2 selector — so it stays regulating to 0 km/h → engaged-to-standstill via `TSK_Anhalten`. Residual
    LOW: an ESP/driver *inhibit* input to `8013ef46` could still hand off near 0, but that's not a cruise speed floor.)
  - **(B) ACC_05 Momentenanforderung / EPB stop-and-go** (Macan: EPB holds, engine coordinates drive-off): **PRESENT in
    the machine code but CAL-GATED OFF** (`a5a8=0x43caf&1=0`). `8010a6ec` = EPB/standstill-hold state machine (hold timer
    →`a54d` hold-confirmed, inhibits `a54b/a54c`); `80141528` = drive-off Momentenanforderung→torque (`d0007baa`→`d0007ce0`
    via kennlinie `0xa005d608`, fires on `b057∈{3,4}` && `a3b9` && `a54b==0` && `b055==1`); `8010a4fc` = its diagnostics.
  - **Neither originates a hold on the bus** (no ACC_05 TX packer; `TSK_Anhalten` relay off when `a5a8≠0`) — hold is
    radar→EPB direct (B) or relayed via `TSK_Anhalten` (A/Q5). **openpilot supplies the stop decision as ACC master; the
    Q5 relay path (ACC_01.ACC_Anhalten→TSK_Anhalten) is sufficient — the missing autonomous soft-stop does NOT block it.**
  - **openpilot:** transmit ACC_01 (0x109) with byte7·bit1=1 + valid MLB E2E (checksum seed 0x08, rolling counter
    byte1 low nibble), keep the ECU Basic-ACC coded and ACC actively engaged (b28e∈{1,5}) → engine relays hold on
    0x10C byte2·bit4. This is the OEM-intended ACC→ESP hold channel (alternative to forging ESP_05/ACC_05→EPB directly).

---

## 7. Editable levers (openpilot) — summary
| goal | lever | flash addr / file off | current | to change |
|---|---|---|---|---|
| **raise −3.0 brake decel** | decel-limit Kennlinie cells (flat −3.0) | 0x8005b71c / **file 0x5b71c** (7×, +4 alt) | 0x7237 (−3.000) | → 0x6db1 (−3.984) or lower + packer literal |
| (packer hard floor) | 80137a00 `0x6db1` literal | in 80137a00 code | −3.984 | lower only to exceed −3.984 |
| **15 km/h monitor floor** | C_VS_MIN_CRU_MON u8 ×2 (+lower-bound/band) | 0x800794ef, 0x800794f2 (+0x800794f3, 0x8007952c) | 15, 15 | set desired km/h (status-only, no DTC latch) |
| low-speed CRUC hysteresis (u16 pair) | 8013ef46:761/814 — hysteresis on **`d0007e84` (=Ramd0007e86, NOT ego speed; ACC-internal, scale unverified)** → bits 0x40/0x80 of CRUC state word `uRamc0001118` | 0x800439f8, 0x800439fa | 1004, 973 | feeds a CRUC sub-state, **NOT a direct standstill cutoff**; the "7.84/7.60 km/h" label is retracted (d0007e84 isn't the 1/128-km/h ego speed) |
| launch-regime latch (CODE) | 8013ef46:**265** `if (Ramd0005618 > 1000 ≈ 7.81 km/h) d000118a=0`; latch set=1 at state reset → bit 0x10 of the local permission byte `d0001160` | — in code — | 1000 | one permission input to the CRUC state, **NOT the direct Anhalten/decel gate** (see corrected note below) |
| ACC creep enable / 3 km/h family | C_VS_MIN_CRU / creep gate / arb | 0x8007a26a, 0x80079536, 0x80043c5c, 0x80043538 | 384/384/300/800 | set desired |
| engine-torque ACC decel | s16 0.005 | 0x80079982 / file 0x79982 | −164 (−0.82) | more negative |
| **ACC frame select (Q5↔Macan)** | cal word (ACC_01 vs ACC_05 decode) | 0x80043bc6 | 0x0900 (ACC_01) | reflash; NOT VCDS |
All cal edits require cal-block **checksum recompute** (`core/checksum`) before reflash. EGAS L1/L2: if a
functional limit has a monitor twin (e.g. 0x80043514 −3.0@0.001), move both or the L2 monitor faults.
**Reaching true standstill (corrected 2026-07-27 — supersedes the earlier UPDATE-66 wording).** The earlier
claim ("the ~7.8 km/h hysteresis + the hardcoded `1000` literal are the *dominant sub-15 barriers*,
firmware-patch-only") **overstated the code and is retracted.** Traced end-to-end in `8013ef46`/`8013e8aa`:
- The **DIRECT gate on both `TSK_Anhalten` and the decel is `STATE_CRU_CTL ∈ {1,5}`** (the `b28e` regulating
  states): `8013ef46:941` sets `tsk02_TSK_Anhalten_src = acc01_ACC_Anhalten` iff `STATE_CRU_CTL∈{1,5} &&
  LV_DCC_ENA`; the decel `Ramd0007cb8 = Ramd0007cae` passes only when decel-enable holds, which also needs
  `STATE_CRU_CTL∈{1,5}` (via `bVar1`).
- The three low-speed thresholds — **2.34 km/h** (cal `0x80043c78`, line 156 → creep flag `d0001171`),
  **7.81 km/h** (literal `1000`, line 265 → launch latch `d000118a`), and the **`d0007e84` hysteresis**
  (`0x800439f8/fa`, lines 761/814) — all feed **permission / sub-state flags** (`d0001160`, `d0001171`,
  `uRamc0001118`, → sub-flags `d1185/1186/1187/1188` in `8013e8aa`) *within* the regulating state. **None of
  them directly forces `STATE_CRU_CTL` out of {1,5} or zeros the outputs.**
- Consequence: there is **no single "dominant barrier" cell or literal**; whether the vehicle brakes to true
  standstill is decided by the CRUC state machine (`8013e8aa`/`8013e47c`) as a whole. The `d0007e84`
  hysteresis is not even confirmed to be a *speed* (its source `Ramd0007e86` is an ACC-internal value, not the
  1/128-km/h ego speed), so the "7.84/7.60 km/h creep" reading is unverified.
- **openpilot is unaffected either way** — it owns hold-at-stop via `ACC_01.ACC_Anhalten` (§6); these internal
  CRUC creep/sub-state flags shape the engine's *autonomous* low-speed behaviour, not the openpilot relay path.
- RESOLVED (2026-07-27, `maps/cruc_state_machine.md`): the CRUC state machine (`8013e8aa`+`8013e47c`+sub-handlers)
  was traced — `STATE_CRU_CTL` does **not** leave {1,5} on decel to 0 (its two ego-speed terms only set sub-flags;
  the `d0007e84` hysteresis is a high-side 1→2 selector; the request producer `801408bc` reads no ego speed). So
  Simos stays regulating to standstill. Residual LOW: the ESP/driver *inhibit* inputs to `8013ef46` (`d000b1c7`,
  autohold, pedal) weren't each traced to root — an upstream standstill-correlated inhibit is a driver/ESP handoff,
  not a cruise speed floor, and doesn't affect the openpilot `ACC_01.ACC_Anhalten` relay path.

## 8. Open threads / uncertainties
1. MO handle ↔ CAN ID (0x8a0/0x600 vs 0x109) — needs the driver MO config / DBC (external to image).
2. `d0007baa` absolute m/s² scale (runtime gain b0d4) — FR says 0.005; reconcile with the ·16 + 850e-6 target.
3. Whether the −3.0 min acts as floor vs cap in every CRUC sub-state (min_u16 semantics) — needs dynamic sim;
   editing can only relax, so low-risk for the lever.
4. Full semantic naming of the d8ce engage-inhibit bits and the d890 ACC-state byte.
