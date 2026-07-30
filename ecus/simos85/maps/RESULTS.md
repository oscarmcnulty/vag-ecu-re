<!-- FINALIZED CURRENT-STATE SUMMARY (topic-organized). The full chronological trail (66 dated
     UPDATEs + retractions) lives in git history — `git log -p maps/RESULTS.md`. This file is the
     "what is true now + the concrete edit targets" digest. The curated flow docs
     (acc_flow.md, cruc_state_machine.md, decel_limit_flow.md, cruise_control_flow.md,
     can_signal_map.md, fr_alignment.md) are the deeper source of truth and win on any conflict. -->

# Simos8.5 (8R0907551F) — ACC / cruise / decel RE: current-state results

ECU: Audi Q5 3.0 TFSI, Continental **Simos8.5**, part **8R0907551F**, project **S859300C**.
MCU: Infineon **TC1796** (TriCore v1.3, little-endian). Image `8R0907551F_Original.bin`, 2 MB,
load base **0x80000000**. `0xa00xxxxx` = uncached mirror of flash `0x800xxxxx`; **file offset = `addr & 0x1FFFFFFF`**.
Goal driving the work: openpilot longitudinal + standstill on the Q5 (engine ECU is the focus; the brake
controller owns hold). See `FINDINGS.md` for the doc index and the retraction map.

---

## 1. Status — what is solved

| # | Topic | Status | Where |
|---|---|---|---|
| 1 | Performance / tuning maps | **SOLVED** — named + addressed via A2L | `performance_maps.md`, `tune_diff_analysis.md`, `maps/simos85.a2l` |
| 2 | −3.0 m/s² ACC decel clamp | **SOLVED** — flat Kennlinie cal `0x5b71c` (0x7237, offset-binary) | §3, `decel_limit_flow.md` |
| 3 | 15 km/h cruise min-speed floor | **SOLVED** — `C_VS_MIN_CRU_MON` @ `0x800794ef/f2`; on-car a **latching L2 fault** | §4, `cruise_control_flow.md` |
| 4 | Standstill hold (`TSK_Anhalten`) | **SOLVED** — live gated pass-through of `ACC_01.ACC_Anhalten` | §5, `acc_flow.md` §6 |
| 5 | "Engaged to 0 km/h?" | **RESOLVED** — `STATE_CRU_CTL` stays in {1,5} to standstill | §5, `cruc_state_machine.md` |
| 6 | Factory stop-and-go / follow-to-stop | **CHARACTERIZED** — two architectures, engine is a follower in both | §6 |
| 7 | CAN architecture + Com config + E2E | **MAPPED** | §7, `can_signal_map.md`, `dispatch_tables.md` |
| 8 | Flash / checksum integrity model | **RESOLVED** — no static cal CRC; integrity at flash-write time | §8, `analysis/RE_findings_checksum.md` |
| 9 | Cal / map engine | **DOCUMENTED** | §9 |

**Decompilation corpus:** base-register unlock + iterative call-harvest + gap recovery grew the Ghidra
project several-fold over bare auto-analysis; the residual undefined bytes are genuine cal data +
inter-bank padding. Current entry count is `analysis/function_entries.txt`, and `reproduce.sh` prints
live coverage percentages at the end of its run. **Actual CODE coverage is
effectively complete** — nothing in the image linear-decodes as function-calling code outside a defined
function. Rebuilt deterministically by `ecus/simos85/reproduce.sh` from `analysis/function_entries.txt`.

---

## 2. The ACC longitudinal spine: ACC_01 → TSK  (pointer to `acc_flow.md` / `cruc_state_machine.md`)

Full end-to-end chain, every hop firmware-verified:

```
ACC_01 (0x109) ─801383e8─▶ d0007bac (accel), d000a7ae (ACC_Anhalten), d000b06a (Dynamik)
 (RX-poll 80108cc4, handle 0x240, E2E seed 0x08 + rolling counter validated)
        │
   8013c5d4  acc_brake_request_formation  ── + flat −3.0 decel-limit Kennlinie ──▶ Ramd0007c9a
        │
   8013ef46  acc_brake_setpoint_statemachine (CRUC_MG005) + 8013e8aa dispatch
        │      states 0..6; handlers 8013e13c/e47c/e674/e3f8 set Ramd0007cae
        │      OUTPUT gate: if STATE_CRU_CTL(d000b28e) ∈ {1,5} → arm TSK_Anhalten + decel
        ▼
   Ramd0007cb8 (= FR AC_SP_CRU_BRAKE_CTL)
        │
   80137a00  TSK_02 packer  (TX scheduler 80106ed8:747, cal caf&1=0, HW mailbox 0x680)
        ▼
   TSK_02 (0x10C) byte8 = TSK_Verzoeg_Anf (decel), byte2·bit4 = TSK_Anhalten (hold)
        ▼   → central gateway J533 (separate ECU) → ESP/chassis bus → ESP
```

**Frame selection is CAL-fixed** (not VCDS coding): `DAT_80043bc6` (=`0x0900`, no writers) selects **ACC_01
active / ACC_05 disabled = the Q5 config**; a Macan cal sets the ACC_05 bits. Companion mode word
`DAT_80043caf` (=`0x06`): `a5a8 = caf&1 = 0` → the ACC_01 + TSK_02 packer + hold-relay branch. On the Q5 the
live accel command is **`d0007bac` = `ACC_01.ACC_Sollbeschleunigung`** (0x109, 24|11, 0.005 m/s²);
`d0007baa` (ACC_05 `ACC_Momentenanforderung`) stays ≈0 (dormant decoder). [HIGH]

**Encoding conventions (critical — prior sessions missed −3.0 for exactly this reason):**

| domain | encoding | 0 m/s² | −3.0 | −3.984 | +2.112 |
|---|---|---|---|---|---|
| internal accel setpoint (d0007cxx / Kennfeld cells) | u16 **850e-6 m/s² OFFSET-BINARY** `phys=(raw−0x8000)·850e-6` | 0x8000 | **0x7237** | 0x6db1 | 0x89b6 |
| `TSK_Verzoeg_Anf` CAN byte | u8, res **0.024 m/s²** | 0xA6 | 0x29 | 0x00 | 0xFE |
| ego speed (d000d644 / d000da54) | u16 **1/128 km/h** (128 cnt = 1 km/h) | — | — | — | — |
| VS min cals (`C_VS_MIN_*`) | u8 km/h, compared `da54 ≤ cal·0x80` | — | — | — | — |
| ACC engine-torque decel (0x80079982) | s16, 0.005 m/s² | — | — | — | — |
| L2 plausibility monitor (800c553c cals) | s16, 0.001 m/s² | — | −3000 | — | +2000 |

The accel→torque *converter* itself is table-driven (runtime C-RAM Com context) and not statically bindable;
resolve it on the bench, not in the image (see §7 + memory `openpilot-integration-goal`).

---

## 3. The −3.0 m/s² decel clamp + edit cells  ⭐ (openpilot decel lever)

Two distinct mechanisms — a **functional saturation clamp** (delivers −3.0) and a separate **L2 plausibility
monitor** (the latching fault). Both are in-image, statically decompiled. [HIGH]

### 3a. Functional saturation clamp — `8013c5d4` (`acc_brake_request_formation`)
- `8013c5d4:209-224` reads a decel-limit **Kennlinie**: values `0xa005b71c`, axis `0xa005a4c4` (N=6),
  input = filtered ego-speed class `Ramd0007ce8`. **All cells = `0x7237` = −3.000 m/s² (completely FLAT)** ⇒
  the cap is **−3.000 speed-independently**.
- Saturation at `:223`/`:418`: `Ramd0007c9a = max(request, 0x7237)` = **truncate braking to −3.0**.
  ⚠ `min_u16_800a4bbc` is a **Ghidra MISNOMER — its body returns the MAX** (verified: `800a4bbc(0x6f00,0x7237)=0x7237`;
  a harder request −3.6 is clamped **up** to −3.0). An adversarial review once tripped on this name and wrongly
  called the lever backwards — the lever is correct (below).
- **Two curves = cruise-mode selection** (`8013c5d4:211`, `d000a757 = LV_DCC_ENA` from long-coding cell 27):
  `a757=0` → **GRA** curve `0xa005b71c` (`IP_AC_SP_MIN_CRU`); `a757=1` → **Basic-ACC** curve
  `0xa005b728`/axis `0xa005a4f4` (`IP_AC_SP_MIN_DCC`). Both overlap into the contiguous **11× `0x7237`
  cluster `0x5b71c–0x5b730`**. There is **no third (Follow-to-stop) curve** (`0x5b734` = all `0x8000`/0).
- The packer `80137a00` then applies a **hard clamp `[0x6db1=−3.984, 0x89b6=+2.112]`** — the CAN signal's
  outer range, below the −3.0 curve.

**EDIT LEVER (raise brake-decel authority):** lower the flat cells at **file `0x5b71c`** (u16 LE offset-binary;
`raw = 0x8000 + phys/850e-6`). Lowering `0x7237` → `0x6db1` **relaxes** the cap toward −3.984; raising tightens.
GRA-coded car → `0x5b71c` group operative; ACC-coded → `0x5b728` group. **Floor without a code edit = −3.984**
(the packer's `0x6db1` literal); to go below, also lower that literal.

### 3b. L2 plausibility monitor (the fault) — `FUN_800c553c` (AC_DCRU_PLAUS)  [HIGH]
- Faults when the filtered setpoint `sRamc0001732` exits the **open interval (−3.0, +2.0)**:
  cal **`0x80043514 = −3000` (−3.0)**, `0x80043512 = +2000` (+2.0), rate `0x80043510 = 32`; **scale 0.001**.
- **The monitor gates on ACHIEVED decel, not commanded** — `sRamc0001732` filters toward `d000b4fa`
  (0.064 m/s²/LSB), which `800ca1e8` derives from a **GPTA0 hardware-timer motion capture** (ASIL-redundant,
  does NOT trust the CAN value). Byte quantization explains the on-car behavior: −3.0 → −3008 < −3000 → fault;
  −2.95 → −2944 > −3000 → safe.
- **On-car ground truth** (comma rlogs, 5 routes): fault fires at a **−3.000 command**, ~100 ms debounce
  (~5 cycles), **fixed ceiling not speed-interpolated (51–116 km/h all trip at −3.0)**, key-cycle latch,
  engine-side (`ESP_Konsistenz_TSK`/`ECD_Fehler`=0). Confirmed-safe software floor **−2.95** (monitor is coarse
  ~0.064 m/s² — do not hug the wall).
- **Editable −3.0 = `0x80043514`.** To raise *delivered* decel, move **both** the `0x5b71c` Kennfeld cells
  **and** `0x80043514` (EGAS L1/L2 pair; mismatch → the monitor still faults at −3.0).

### 3c. Engine-torque ACC decel (separate, weaker) — `801e6df0`  [HIGH]
The engine limits its own ACC engine-*braking* decel to **−0.82 m/s²**: cal `0x80079940` floor `[+0x42]=−164`
(**file 0x79982**, s16 0.005); ceiling `[+0x40]=+328`=+1.64. Harder braking is delegated to ESP via the −3.0
brake channel above. Lever: `0x80079982`, more negative for more engine-side authority.

**Historical note:** the `0x8004dd90` "−600 / 0.005" curve of earlier drafts (UPDATEs 43–49) was a **red
herring — RETRACTED**; the real clamp is the `0x7237` offset-binary Kennfeld above.

---

## 4. Cruise minimum-speed floors + the L2 monitor  ⭐ (openpilot min-speed lever)

Ego speed `d000d644 = clamp(d5618·32/25)`; monitor copy `d000da54` (`801efbb8:415`). **Scale 1/128 km/h.**
Four distinct thresholds — **do not conflate** (full table in `cruise_control_flow.md`): [HIGH]

| threshold | flash cal | raw | read in | role | FR label |
|---|---|---|---|---|---|
| **15 km/h L2 monitor** (×2) | **`0x800794ef` / `0x800794f2`** | 15 (u8, ×0x80) | `80102f60:1583/:1645` (`da54 ≤ cal·0x80`) | L2 crawl monitor → status + **latching fault** | `C_VS_MIN_CRU_MON` (= `C_VS_MIN_CRU_OFF − 2`) |
| activation floor **3.0 km/h** | `0x8007a26a` (0xa007a204+0x66) | 384 | `801e9b86:301` | level-1 "controller may be active" / near-standstill PI branch | `C_VS_MIN_CRU` |
| creep / accel-ctl gate **3.0 km/h** | `0x80079536` (0x800793a0+0x196) | 384 | `80102f60:725` | moving≥3 discriminator | `C_VS_MIN_AC_CTL_CRU` (cand.) |
| EGAS-L2 twin **15 km/h** (×2) | `0x800456c0` / `0x800456bd` | 15 (u8) | `egas_l2_monitor_cal_init 800a0c9c` | independent EGAS shadow-RAM monitor (`^0xff`); **NOT** the speed-compare value | `C_VS_MIN_CRU_MON`/`_DCC_MON` |

- The 15 km/h monitor comparison at `80102f60:1583` is **`<=` on an unsigned u8** (×0x80), so it **cannot be
  "zeroed out" to exclude standstill** (`0 <= 0` is true; 0x80–0xFF give a 128–255 km/h threshold that matches
  everywhere). Full trigger also requires an accel-plausibility band (cals `0x800794f8/fa/fc/fe`).
- **On-car it is a real key-cycle-latching L2 fault below ~15 km/h** (openpilot ground truth). Path: the
  debounced monitor output feeds the 13-diagnosis accumulator inside `80102f60` → `d000d8e0 ≠ 0` → `d000d744`
  → **`d000d8b4` (key-cycle latch)** → status-3 (`d8e2.bit2` → `801eca44`). This corrects the earlier
  "status/telemetry only" read. `da46` (monitored accel) leans MEASURED/computed, not raw command — whether the
  fault is avoidable by sending different signals (empty-band escape / hold-vs-raw-decel) is an OPEN trace (§11).
- The **A2L `C_VS_MIN_CRU_MON` @ file 0x456C0/0x456BD is the EGAS-L2 twin**, a *different* cal base — to move the
  operative cruise floor edit `0x800794ef/f2`; check/match the 0x456C0 twin to avoid an L1/L2 mismatch.

---

## 5. Standstill hold / `TSK_Anhalten` relay (+ engaged-to-0 resolved)

**`TSK_Anhalten` is a LIVE, gated pass-through** of the incoming `ACC_01.ACC_Anhalten` CAN bit — **not**
constant 0 (that earlier read was retracted). Every hop firmware-verified: [HIGH]

```
ACC_01/0x109 byte7·bit1 (ACC_Anhalten)
   →[801383e8:94, E2E seed-0x08 OK, RX-poll handle 0x240]→ d000a7ae
   →[8013ef46:937-943, a58d = a7ae when the gate holds, else 0]→ d000a58d
   →[80137a00:49/94, TSK valid ad7a/a852]→ TSK_02 (0x10C) byte2·bit4 = TSK_Anhalten
```

- **Forward gate** (what openpilot must satisfy): `ad0f≠0` (master ACC compute-enable) **AND** `a757≠0`
  (`LV_DCC_ENA` — coded **Basic-ACC**; GRA-coded `a757=0` never forwards) **AND** `a5a8==0` (cal-fixed 0 on Q5)
  **AND** `b28e ∈ {1,5}` (`STATE_CRU_CTL` actively regulating). So the runtime conditions reduce to: ACC
  compute-enabled + Basic-ACC coded + cruise actively regulating.
- Reads 0 on a **stock** car only because the single-radar B8 ACC never asserts `ACC_Anhalten` (30 km/h floor,
  memory `b8-acc-radar-hardware`) — the path is intact (opposite of F2S, which is genuinely compiled out).
- **Completeness:** `TSK_Anhalten` is the **only** engine-originated discrete *hold* vector. `TSK_Zwangszusch_ESP`
  (`a58f`, byte7·bit6 = `b28f∈{1,2}`) is a live ESP-coupling *enable*, not a hold. `TSK_Radbremsmom` +
  `TSK_Standby_Anf_ESP` = **const 0** (FR "not used"). The engine has **no EPB-engage TX** on any path
  (ACC_05/0x10D `ACC_Betaetigung_EPB` is RX-only). EPB is actuated only radar→EPB or ESP→EPB.
- **Timeout = continuity, not a max-hold cap.** On **4 consecutively-dropped ACC_01 frames**
  (`LV_CAN_DCC_NOT_VLD_FAST`), `801a6134` (a reset/timeout default, NOT the operative writer) zeroes `a7ae` →
  `TSK_Anhalten`→0 → ESP releases; **no EPB failsafe, no rollaway prevention** (engine just drops the request).
  Stream ACC_01 continuously (valid E2E seed 0x08 + incrementing counter, no ≥4-frame gap) and the engine relays
  hold **indefinitely** — waiting at a light is fine.

### Engaged-to-0 — RESOLVED (`cruc_state_machine.md`)
`STATE_CRU_CTL` (`d000b28e`) does **NOT** leave its regulating states {1,5} as speed → 0. States 1 (full) and 5
(brake-only) are the only regulating states and the only ones the output gate arms. Every exit from {1,5} is a
fault / permission-loss / inhibit / driver-override / lateral sub-state split — **none is a function of low ego
speed**:
- The two ego-speed terms in the machine set **sub-flags only**: the 7.81 km/h **one-way launch latch**
  `d000118a` (`8013ef46:265`, `if 1000 < Ramd0005618`) de-asserts as speed *rises* and never re-arms falling;
  the 2.34 km/h **creep flag** `d0001171` (`8013ef46:156`) only tweaks the state-1 torque.
- The `d0007e84` hysteresis (cals `0x800439f8=1004`, `0x800439fa=973`) is a **high-side 1→2 selector**, so
  falling speed keeps the machine **in** state 1. (`d0007e84`=`Ramd0007e86` is an ACC-internal value, **not**
  the 1/128-km/h ego speed — its scale is unverified.)
- The master-request producer `801408bc` reads **no** ego-speed variable; the 15 km/h L2 monitor outputs are
  **not read** anywhere in the CRUC machine (its deactivation path is dead, fatal mask = 0).

**Consequence:** with ACC engaged and no fault/override/ESP-brake intervention, the machine **stays regulating
to 0 km/h** → the hold-relay and the −3.0-capped decel relay stay **live to true standstill**. Residual (LOW):
an upstream ESP/driver *inhibit* input to `8013ef46` (autohold flag, driver brake tap) could hand off near 0 —
a driver/ESP-domain handoff, not a cruise speed floor, and it does not affect the openpilot relay.

**Retracted framing (do not reintroduce):** the "7.84/7.60 km/h dominant sub-15 creep floor" and the
"hardcoded `1000` literal is the dominant barrier / firmware-patch-only to reach standstill" claims are
**RETRACTED** (overstated the code and mislabeled `d0007e84`). There is no single "dominant barrier" cell/literal;
the low-speed thresholds feed permission/sub-state flags *within* {1,5}. openpilot is unaffected either way — it
owns hold-at-stop via `ACC_01.ACC_Anhalten`.

---

## 6. Stop-and-go / follow-to-stop — two architectures; engine is a FOLLOWER in both  [HIGH]

- **(A) F2S / SOFT_STOP** (engine autonomously brakes to standstill): the F2S-*specific* refinements are
  **COMPILED OUT** — the explicit wheel-brake-hold-torque `TQ_BRAKE_HLD`→`TSK_Radbremsmom` = const 0; the
  smooth-approach curve `IP_AC_SP_MIN_DCC_FOL_2_STOP` is empty (`0x5b734` all zero); `LV_DCC_ENA_FOL_2_STOP` is a
  compile-0 stub; `a758` (`LV_DCC_STST_ENA`) is dead. Cruise type = **long-coding cell 27 (`STATE_DCC_TYP`)** —
  coding cell 27=3 asserts F2S while the stub is 0 → `LV_VAR_COD_CRU_DCC_NOT_PLAUS` → status-3 fault (why VCDS
  rejects mode 03h). **BUT** the ACC_01/Basic-ACC path itself **does brake toward standstill** via the normal
  decel path (−3.0 authority to 0, `TSK_Anhalten` hold relay, standstill-regime management) = a **de-facto
  follow-to-stop**. Only the formal OEM F2S mode + wheel-brake-hold-torque are absent.
- **(B) ACC_05 Momentenanforderung / EPB stop-and-go** (Macan: EPB holds, engine coordinates drive-off):
  the machine code **EXISTS but is CAL-GATED OFF** (`a5a8=0`). `8010a6ec` = EPB/standstill-hold state machine;
  `80141528` = drive-off Momentenanforderung→torque; `8010a4fc` = its diagnostics. Enabling it needs a reflash
  (`0x80043bc6` + `0x43caf` bit0) = a different architecture, **kills the `TSK_Anhalten` relay**, and still adds
  no F2S brake side — so neither coding nor cal yields a full working follow-to-stop.
- **openpilot:** as ACC master you supply the stop decision; the Q5 relay path
  (`ACC_01.ACC_Anhalten` → `TSK_Anhalten`, §5) is sufficient. Standstill hold is physically an ESP/EPB job — the
  missing autonomous soft-stop does **not** block openpilot brake-to-standstill. The stock 30 km/h dropout is the
  single-radar limit, not the engine's.

---

## 7. CAN architecture + Com config + E2E checksum/counter

- **MLB E2E seed rule (ground truth):** `seed = (id>>8) ^ (id&0xff)`. Verified: 0x109→0x08, 0x10D→0x0C,
  0x106→0x07, 0x10C→0x0D, 0x104→0x05, 0x10E→0x0F… (ESP_01 0x100→0x01, ESP_02 0x101→0xAB/0xAA are the magic
  exceptions). Each dedicated RX decoder validates `(b0^…^b7)==seed` + rolling counter (byte1 low nibble) and
  **discards** bad frames. This lets any decoder's frame be back-solved from the XOR constant it checks. [HIGH]
- **Master acceptance dispatch @ `0x80082f18`** (104 accepted IDs; only **13 have a dedicated HW-mailbox handler**).
  `0x117` ACC_10/AEB is a filter entry with a null handler → **the engine does not process AEB**. Full table in
  `can_signal_map.md`. Key handlers: `0x109` ACC_01 RX (8011e8f8 stages raw→d000d40a), `0x10c` TSK_02 TX
  (decel out), `0x10e` TSK_04 TX, `0x10a` TSK_01 TX, `0x10d` ACC_05 RX, `0x10b` LS_01 RX.
- **Three ACC-longitudinal ingress decoders** (RX-poll `80108cc4`, identified by seed + bit-for-bit dbc match):
  `801383e8` handle 0x240 seed 0x08 = **ACC_01/0x109** (accel `d0007bac`, `a7ae` Anhalten, `b06a` Dynamik);
  `801383fc` handle 0x8a0 seed 0x0C = **ACC_05/0x10D** (Momentenanforderung `d0007baa`, EPB, StartStopp —
  dormant on Q5); `80106db8` handle 0x600 seed 0x07 = **ESP_05/0x106** (ESP→engine feedback: `ESP_Bremsdruck`,
  `ESP_Verz_TSK_aktiv`, `ESP_Konsistenz_TSK`, `ESP_Autohold_aktiv`, `ESP_Status_Bremsdruck`). The engine↔ESP
  brake loop is thus **closed** — the engine sends decel/hold on TSK_02 and reads ESP's reaction on ESP_05.
- **Generated AUTOSAR-style Com stack** (table-driven, computed-pointer dispatch). Config root `0x800906fc`
  (`DAT_d0000cd0`; 6 connections, `c3` = TSK_02/0x10C TX). Signal↔address binding is built at boot into the C-RAM
  Com context `_DAT_c03fc37c` (= flash-rooted `0x80030be0`); RX-var registry `0x801f51a0`. Runtime Com API:
  `Com_SendSignal 801cf11a`. Per-msg Com CHKSUM/COUNTER hooks (`801d0360`/`801d0364`) are **stubs** — the Com
  layer does NOT enforce E2E on periodic RX; the dedicated decoders do.
- **Emulator saga (condensed):** capturing the exact runtime signal↔mirror map requires full-boot emulation to
  materialize the C-RAM Com context; a working TC1796 boot emulator (`research/emulation/EmulBoot.java`) was built
  and materialized `_DAT_c03fc37c`, but the per-signal RX unpack is CAN-interrupt-gated — see git history
  (UPDATEs 21–31/41/48) and `research/emulation/`. Not needed for the openpilot deliverable.

---

## 8. Integrity / flash / checksum model  (`analysis/RE_findings_checksum.md`)

- **No embedded static calibration checksum in the running application.** Verified by decompiling all three
  checksum primitives + exhaustive 3-file matching. [HIGH]
- Cal integrity is enforced **at flash-write time** by the resident flash driver (per-block **CRC-16 poly
  0xA001, init 0xABCD** over the streamed UDS TransferData bytes) + whole-image checks in the FBL/bootloader
  (`0x0–0x20000`, **BLANK** in the OBD read) + **RSA-1024** signatures (key ID 0x73). Repro-status bits:
  #15 = cal CRC, #11 = ECU-SW CRC, #31 = all.
- The three primitives: `crc32_reflected 0x801dc544` (zlib, table `0x8009083c`; runtime 8-byte word only);
  `crc16_table 0x800a59f0` (init 0xABCD; UDS transfer-block only); `checksum8_table 0x800a5a18`
  (CRC-8/AUTOSAR, poly 0x2F — **0 callers**, unused here).
- **Practical:** a modified cal flashed via the normal tool path (Pcmflash) is accepted through the streamed
  CRC — **there is no static cal-CRC word to patch in the file**, but **recompute the cal-block checksum**
  (`core/checksum`) before reflash. Memory layout: `0x40000–0x70000` = cal/maps; `0x90000–0x1F0000` = main code;
  SW-ID @ `0x80040000` = `8R0907551F`, `S8500L2000000`, `CTUC`.

---

## 9. Cal / map engine

- **Base-register unlock** (the enabling step for all cal RE): `a0 = 0xd0008000` (RAM SDA base),
  `a1 = 0xa0048000 → 0x80048000` (**calibration base**), `a8 = 0x80088800`; master pointer/descriptor table
  @ `0x8008615c`. Recovered by `core/ghidra/FindBaseRegs.java`, applied by `SetBaseRegs.java`.
- **Readers:** 1-D Kennlinie `kl_interp_u16 @0x800a5f40` (+ `lookup_kennlinie_800a2cd0`); 2-D Kennfeld
  `kf_interp_u16 @0x800a5fc0` (+ `lookup_kennfeld_map_800a2e0c`). Maps reached via a **descriptor-table
  framework**: accessor `FUN_800a8ff0` (16-byte descriptors, `id*0x10` → data pointer), dispatch `FUN_801d977c`;
  dimensions live in descriptor metadata, not at the data pointer.
- Cal region `0x40000–0x80000` data-typed (`MarkCalData.java`) so "undefined" reflects only real code.
- **`a0/a1`-relative access gotcha:** `FindRefsTo`'s absolute reference DB misses `a0`-relative RAM writes;
  the decompiler resolves them (`DAT_d000xxxx`), so **decompile-grep** (or the SymbolicPropogator `--range`
  pass added to `FindRefsTo`) is the right tool for `d000xxxx` dataflow.

---

## 10. Consolidated openpilot edit-target table

| goal | lever | flash addr / file off | current | to change |
|---|---|---|---|---|
| **raise −3.0 brake decel** | flat decel-limit Kennlinie cells | `0x8005b71c` / **file 0x5b71c** (7×; +4 alt `…b730`) | 0x7237 (−3.000) | lower → 0x6db1 (−3.984) or below (offset-binary) |
| **−3.0 L2 monitor twin** (move WITH the cells) | `AC_DCRU_PLAUS` limit + companion | `0x80043514` (−3000) / `0x80043512` (+2000) | −3.0 / +2.0 | raise magnitude; scale 0.001 |
| (packer hard floor) | `80137a00` `0x6db1` literal | in code | −3.984 | only to exceed −3.984 |
| **15 km/h monitor floor** | `C_VS_MIN_CRU_MON` u8 ×2 (+ accel band) | `0x800794ef`, `0x800794f2` (+ `0x800794f8..fe`) | 15 | latching L2 fault; `<=`/unsigned so cannot be zeroed for standstill |
| (EGAS-L2 twin — match to avoid L1/L2 mismatch) | A2L `C_VS_MIN_CRU_MON` | `0x800456c0` / `0x800456bd` | 15 | keep consistent |
| activation floor / creep (3 km/h) | `C_VS_MIN_CRU` / `C_VS_MIN_AC_CTL_CRU` | `0x8007a26a`, `0x80079536` | 384 / 384 | 1/128 km/h |
| engine-torque ACC decel (−0.82) | s16 0.005 | `0x80079982` / file 0x79982 | −164 | more negative |
| **ACC frame select (Q5↔Macan)** | cal word (ACC_01 vs ACC_05 decode) | `0x80043bc6` (+ `0x43caf` bit0) | 0x0900 (ACC_01) | **reflash, NOT VCDS** |

**All cal edits require a cal-block checksum recompute (`core/checksum`) before reflash.** EGAS L1/L2: if a
functional limit has a monitor twin (−3.0 @ `0x80043514`; 15 km/h @ `0x456c0`), move both or the monitor faults.
For sub-15 km/h operation the practical enabler is lowering the min-speed floor(s); openpilot owns hold-at-stop
via `ACC_01.ACC_Anhalten` regardless.

---

## 11. Open items

1. **The sub-15 km/h L2 fault escape (HIGH interest).** Which exact one of the 13 diagnoses latches below 15 km/h,
   and whether it is avoidable by sending different signals — the empty accel-band (`bVar19`) escape,
   `ACC_Anhalten`-hold vs raw-decel, `da46` commanded-vs-measured — **without** a cal/coding/firmware change. Deep
   trace in progress.
2. **Naming the relayed CAN diagnosis bits** (12 of 13 aggregator feeders are 2-bit relayed symptoms) — needs the
   ACC/brake CAN DBC, external to the engine image.
3. **MO handle ↔ CAN-ID binding** (0x240/0x8a0/0x600) lives in external HAL/COM config; covered to HIGH by the
   E2E-seed + FR + opendbc triangulation, but not a decoded config line.
4. **`d0007baa` absolute m/s² scale** (runtime gain `b0d4`) vs FR 0.005 — reconcile.
5. **Residual (LOW):** the ESP/driver *inhibit* inputs to `8013ef46` near standstill (autohold, pedal, `d000b1c7`)
   were not each traced to root — a possible driver/ESP handoff near 0 km/h, not a cruise speed floor.
6. Full semantic naming of the `d8ce` engage-inhibit bit-word and the `d890` ACC-state byte.

---

## 12. Key artifacts + tools

- **Curated flow docs (source of truth):** `acc_flow.md` (ingress→engine→ESP, full signal tables),
  `cruc_state_machine.md` (`STATE_CRU_CTL` end-to-end, engaged-to-0), `decel_limit_flow.md` (−3.0 + on-car
  evidence), `cruise_control_flow.md` (speed floors), `can_signal_map.md`, `fr_alignment.md`,
  `dispatch_tables.md`, `performance_maps.md`, `tune_diff_analysis.md`, `FINDINGS.md` (index + retraction map).
- **Checksum / CAN validation:** `analysis/RE_findings_checksum.md`, `analysis/CHECKSUM_COUNTER_VALIDATION.md`.
- **Calibration store:** `maps/simos85.a2l`, `maps/a2l_catalog.csv`, `maps/a2l_symbols.csv`;
  tuner diff `maps/diff_block_addrs.txt`.
- **Decompiles / symbols:** `analysis/decompiles_r/` (+ `_can`, `_extra`), `analysis/symbols_merged.csv`,
  `analysis/function_entries.txt` (the manifest `reproduce.sh` rebuilds from), `analysis/com_pdu_records.csv`.
- **Ghidra tooling (canonical rebuild):** `core/ghidra/{FindBaseRegs,SetBaseRegs,FindCalXrefs,TraceMapCalls,
  CreateFunctions,DecompileAll,CoverageStat,MarkCalData,RecoverReferencedCode}.java`; diagnostics/discovery/
  emulation harnesses under `research/{diagnostics,discovery,emulation}/` (incl. `EmulBoot.java`, `FindRefsTo.java`,
  `DecompileAddrs.java`, `AddrGenSweep.java`, `RecoverGapWalk.java`).
- **Reproduce:** `ecus/simos85/reproduce.sh` (7 steps: create fns → set base regs → mark cal data → decompile).
- **Full chronological history (66 UPDATEs + retractions):** `git log -p ecus/simos85/maps/RESULTS.md`.
