# Calibration edit targets (8R0907551F)

Every cal address the ACC/cruise work has pinned, in one table, with the direction of the edit. Values
are as read from `8R0907551F_Original.bin`. Flash address `0x800xxxxx` ⇔ file offset `0x xxxxx`
(`addr & 0x1FFFFFFF`). The mechanism behind each row is in the doc named in the last column.

**Two rules that bite:**

1. **All cal edits require a cal-block checksum recompute (`core/checksum`) before reflash.** There is
   no static cal-CRC word inside the image — integrity is enforced at flash-write time — but the tool
   path still checks the streamed block.
2. **EGAS L1/L2 pairing.** Where a functional limit has a monitor twin, move both or the monitor faults
   anyway: −3.0 m/s² (`0x5b71c` ↔ `0x80043514`), 15 km/h (`0x800794ef/f2` ↔ `0x800456c0/bd`).

## Deceleration authority

| goal | target | address (flash / file) | current | change | doc |
|---|---|---|---|---|---|
| **raise the −3.0 brake-decel cap** | flat decel-limit Kennlinie cells, 11 × u16 LE | `0x8005b71c`–`0x8005b730` / file `0x5b71c` | `0x7237` = −3.000 | **lower** the raw (offset-binary): `0x6FEA` ≈ −3.5, `0x6db1` = −3.984 | `decel_limit_flow.md` §1 |
| **−3.0 L2 monitor twin** (move with the cells) | `AC_DCRU_PLAUS` limit | `0x80043514` (s16, 0.001) | −3000 | raise magnitude to match | `decel_limit_flow.md` §2 |
| (companion +2.0 limit / rate) | same monitor | `0x80043512` = +2000, `0x80043510` = 32 | | usually leave | `decel_limit_flow.md` §2 |
| (packer hard floor) | `0x6db1` literal inside `80137a00` | in code | −3.984 | only to exceed −3.984 | `decel_limit_flow.md` §1 |
| engine-torque ACC decel | s16, 0.005 m/s² | `0x80079982` / file `0x79982` | −164 = −0.82 | more negative = more engine-side authority | `decel_limit_flow.md` §3 |
| (its ceiling) | s16, 0.005 | `0x80079980` | +328 = +1.64 | — | `decel_limit_flow.md` §3 |

Without a reflash the practical decel lever is the sending side: clamp commands at the confirmed-safe
**−2.95 m/s²**.

## Low-speed floors

| goal | target | address | current | change | doc |
|---|---|---|---|---|---|
| **15 km/h L2 crawl monitor** (mechanism A) | `C_VS_MIN_CRU_MON`, u8 km/h ×2 | `0x800794ef`, `0x800794f2` | 15 | set desired km/h — **cannot be zeroed** (`<=` on unsigned; 0 matches at standstill) | `low_speed_floors.md` §1 |
| (its accel band / lower edge) | u8 cals | `0x800794f3` = 50, `0x800794f8/fa/fc/fe` = 240/144/248/208 | | only if chasing the band escape | `low_speed_floors.md` §1 |
| (EGAS-L2 twin — match to avoid an L1/L2 mismatch) | A2L `C_VS_MIN_CRU_MON` / `_DCC_MON` | `0x800456c0`, `0x800456bd` | 15 | keep consistent | `low_speed_floors.md` §1 |
| (its hysteresis / clear values) | u8 | `0x800456be`, `0x800456c3` | 13 | keep MON − 2 | `low_speed_floors.md` §3 |
| activation floor | `C_VS_MIN_CRU`, u16 1/128 km/h | `0x8007a26a` | 384 = 3.0 km/h | raw = km/h × 128 | `low_speed_floors.md` §3 |
| creep / accel-control gate | `C_VS_MIN_AC_CTL_CRU`, u16 1/128 | `0x80079536` | 384 = 3.0 km/h | raw = km/h × 128 | `low_speed_floors.md` §3 |
| **ESP ECD permission** (mechanism B) | — | **not in this ECU** | — | the ESP declares `ECD_nicht_verfuegbar` below ~15 km/h; no engine cal changes it | `low_speed_floors.md` §2, §5 |
| (which ECD bit the engine debounces) | u8, bit 0 | `0x80043cd0` | `0x01` → uses `ECD_nicht_verfuegbar` | clearing bit 0 switches to `ECD_Fehler` — does **not** remove the gate | `low_speed_floors.md` §2 |

## Architecture / mode selection

| goal | target | address | current | change | doc |
|---|---|---|---|---|---|
| **ACC frame select (Q5 ↔ Macan)** | cal word: ACC_01 vs ACC_05 decode | `0x80043bc6` | `0x0900` = ACC_01 active | **reflash only, not VCDS coding**; switching kills the `TSK_Anhalten` relay | `acc_flow.md` §8 |
| companion mode word | `d000a5a8 = caf & 1` | `0x80043caf` | `0x06` (bit0 = 0 → ACC_01/TSK_02 branch) | as above | `acc_flow.md` §8 |
| cruise type (GRA / Basic-ACC / F2S) | long-coding cell 27 `STATE_DCC_TYP` → `d000a757` | coding, not cal | — | cell 27 = 3 (F2S) faults: the F2S stub is compiled 0 | `acc_flow.md` §8 |

## CRUC state-machine cals (context, rarely the lever)

| what | address | current | note |
|---|---|---|---|
| `d0007e84` state 1→2 threshold | `0x800439f8` | 1004 | high-side selector; `d0007e84` is **not** ego speed, scale unverified |
| its hysteresis back to state 1 | `0x800439fa` | 973 | |
| engage-permission mask | `0x80043421` (high byte of the word at `0x80043420`) | `0x1B` | `d000115f` must equal this and be non-zero |
| inhibit mask | `0x80043422` | `0xEF` | any surviving inhibit bit leaves the regulating set |
| creep-flag threshold (2.34 km/h) | `0x80043c78` | 300 | sub-flag only |
| launch latch (7.81 km/h) | literal `1000` in `8013ef46:265` | in code | one-way launch enable, not a stop floor |

## Performance / tuning

Torque ceilings, rev and speed limiters, boost, fuelling and ignition are catalogued with addresses in
`performance_maps.md` (named objects) and `tune_diff_analysis.md` (what the Stage1/Stage2 tunes change,
block by block). The canonical machine-readable store is `simos85.a2l` → `a2l_catalog.csv`.
