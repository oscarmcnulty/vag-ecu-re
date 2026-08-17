# Vehicle speed on this ECU, and the functional low-speed calibration cells

Two things this file settles: **where vehicle speed lives** (three separate decodes of the same wire
field, on three separate paths) and **which functional-path calibration cells actually compare
against it at low speed**. It is the inventory you need before deciding what to change; it is not
where the ACC floor comes from.

> **The ~15 km/h ACC floor is not an engine calibration.** It is `ESP_05` (`0x106`) frame bit 33
> `ECD_nicht_verfuegbar`, declared by the ESP/ABS and relayed by this ECU. Full account and on-car
> evidence: **`ecd_relay.md`**. The separate EGAS-L2 monitor gate (cal #208) is in
> **`l2_monitors.md`**. Nothing in the table below is that floor, and none of these cells was ever
> going to be.

Load base `0x80000000`; file offset = `addr & 0x1FFFFFFF`; RAM = `0xd00xxxxx`. `a9` is folded, so
`*(a9+off)` already appears as a concrete cal-object address in the decompiles (`a9_resolution.md`).

Confidence: **[C]** read the code/bytes · **[M]** measured on-car · **[I]** inferred · **[G]** gap.

## 1. Three decodes of one wire signal [C]

The vehicle speed the whole car agrees on is **`ESP_v_Signal`, ESP_01 (`0x100`) frame bits 32\|16**.
This ECU decodes it three times, deliberately:

| path | variable | scale | how it gets there |
|---|---|---|---|
| **COM shadow** | `comsig_d0008608_b32l16` = **`0xd0008608`** | 0.01 km/h | generic RX distributor via signal descriptor `0x8003a770`; defaulted by `COM_rx_default_substitution` on timeout |
| **Functional** | **`0xd0008f5e`** (core ctx 0), **`0xd0008c22`** (ctx 1) | **0.01 km/h** | written by `FUN_80199c9e:495` / `FUN_80316b2a:753` from the COM shadow, with a low-cut against cal `#…+0x5c` |
| **EGAS-L2 monitor** | **`0xd0007b8a`** | **1/128 km/h** | `d0007b8a = FUN_8007dc3c(d0008f5e * 0x20, 0x19)` = functional × 32/25 (`80199130:15`, ctx-1 `801991c4:15`) |

The scales are self-consistent: `0.01 km/h` × 100/km/h × 32/25 = 128/km/h. The `×32/25` conversion is
the same one Simos8.5 uses for its monitor speed.

**A fourth, fully independent decode exists on the monitor path** and does not go through the COM
shadows at all: thirteen RX messages keep a verbatim 8-byte frame snapshot, mirrored into a
contiguous block at `0xd0009a2c` by `FUN_800a3f76`. `FUN_8005e822` and `FUN_80050a04` rebuild
`byte4 | byte5<<8` straight out of that block — ESP_01 frame bits 32..47. That redundancy is the
point of the Level-2 architecture: the monitor never trusts the functional path's copy.

Corroboration for the 0.01 km/h functional scale: `DAT_d000a139 = (d0008f5e < 100)` is the
"below 1 km/h" standstill flag (`80199130:29`, `801991c4:31`), and cal #247's speed axis at
`0x803b4eb6` reads 1200/1400/1600/1800/2000/2200/2400/2660 — clean 2 km/h steps from 12.0 to
26.6 km/h. **[C]**

## 2. Functional low-speed calibration cells [C]

Every functional cell that compares the 0.01 km/h speed at low speed, with what it actually does.
None of them is a permit or an engage gate.

| flash | cal object | value | site | what it does | conf |
|---|---|---|---|---|---|
| `0x803b528e` | #251 `0x803b5230` +0x5e | **10.00 km/h** | `801455ae:60` | `cal < d0008f5e` → clears `d0009e1b`/`d000aafe`, the ACC low-speed creep/approach **sub-state** | [C] code / [I] role |
| `0x803b5a30` | #260 `0x803b59a6` +0x8a | 20.00 km/h | `802c35d8:201` | upper bound of the plausibility window `[0, 20]` on `d0008c22` | [C]/[I] |
| `0x803b5a36` | #260 +0x90 | 80.00 km/h | `802c35d8:517` | lower bound of the second window `[80, 140]` | [C]/[I] |
| `0x803b88ae` | #279 `0x803b8762` +0x14c | 3.00 km/h | `8030347a:276` | `d0008f5e <= cal` → sets `d000f737/738/f73c` — **diagnostic**, §3 | [C] |
| (literal) | — | 3.01 km/h (`< 0x12d`) | `802c23b8:120` | sets `d0002a14`, read only inside that function | [C] |
| cal #247 `0x803b4834` | many fields = 2000 | 20.00 km/h ×~60 | `801418ea` | speed **axes** of the ACC decel-shaping maps | [C] |

Notes:

- **#247 `0x803b4834` (1768 B, `a9+0x3dc`)** and **#251 `0x803b5230` (96 B, `a9+0x3ec`)** are the
  ACC-functional cal objects; **#260 `0x803b59a6` (150 B, `a9+0x410`)** is the GRA/cruise/limiter
  object. All functional speed cells live in the `0x803b_xxxx` region, disjoint from the EGAS-L2
  objects at `0x80384xxx…0x8038axxx`.
- The 35 km/h cell (`0x803e0bd4`, object #838) and the `[0,20]`/`[80,140]` pairs are **speed-signal
  plausibility windows** in a self-contained diagnostic (`802c0c24/66/d78/dee`) with no cruise-state
  reference. Do not read 35 as a floor. **[C]**
- The B8 Q5's ~30 km/h *factory* ACC floor is a single-radar **hardware** property (repo memory
  `b8-acc-radar-hardware`): the radar simply never issues a request below ~30 km/h, so no engine cal
  needs to encode 30 — which is why no clean 30 km/h engine-side engage cell exists. **[I]**

## 3. The 3 km/h "creep gate" — leave it stock [C]

It does not block low-speed or standstill control.

- Both 3 km/h cells are **diagnostic, not control**:
  - `0x803b88ae` (`8030347a:276`) sets `d000f737`/`738`/`f73c`, and **`d000f73c` has zero readers in
    the control path** — `0x8030_xxxx` is the diagnostic/observer block. A dead measurement flag.
  - the 3.01 km/h literal (`802c23b8:120`) sets `d0002a14`, used only locally at `:153`/`:194`.
- **No hardcoded low-speed barrier in the hold/decel path.** `FUN_801434de` uses `d0008f5e` only as
  the X-axis input to cal maps (`Kennfeld_s16`/`Kennlinie_s16` over `*(a9+0x3e4)` = #249 and
  `*(a9+0x3d8)`), with no hardcoded speed compare, and those axes reach standstill.
- **openpilot's control flows through the stock creep/anfahren logic.** The hold request `d000a365`
  (`801434de:85-93`) is gated on `d000a35c`; the drive-off shaping (`FUN_801405d4` → `d000ab00`, read
  by `80140922`/`801418ea`) is gated on ACC engaged (`a454==2`) and regulating (`a362 ∈ {1,5}`), which
  openpilot maintains as ACC master. The anfahren map *shapes* drive-off torque following the
  commanded accel rather than blocking it.
- **Residual, behavioural only:** the anfahren torque profile is cal `*(a9+0x3d8)` =
  `PTR_DAT_8010383c`. If stock creep torque feels wrong under openpilot at very low speed that is a
  tuning edit, not a requirement for control. There is no evidence of uncommanded creep against
  openpilot's hold (`a35c` suppresses drive-off via `a365`).

## 4. What the functional path does *not* contain [C]

These negatives were established exhaustively and they are the reason the answer turned out to be
external. They stand:

- **No 15 km/h scalar** in any calibration on the functional path: 5,877 regex-resolved cal reads
  plus 30,199 reads resolved through the `a9` cal-object table, including 904 runtime-indexed
  accesses over 518 arrays that the regex could not see.
- **No 15 km/h breakpoint** in any reachable characteristic curve or map: 29 1-D Kennlinien and
  10 2-D Kennfelder decoded axis by axis (`kennlinie_interpolators.md`).
- **No literal `1500` compare anywhere in the image**, in any of ten speed encodings.
- The `±1500` pairs at cal `0x803c2d34 +0x356/+0x358` and `+0x366/+0x368` are **saturation clamps**
  passed as (lower, upper) to the integrators `FUN_8007ca62`/`FUN_8007c9f2` — not a gate.
- `FUN_800accac`'s condition table contains no speed variable and no cal read at all
  (`engage_state.md`).

## Summary of addresses

- COM shadow `0xd0008608` (ESP_01 32\|16, 0.01 km/h) · functional `0xd0008f5e` / `0xd0008c22`
  (0.01 km/h) · monitor `0xd0007b8a` (1/128 km/h) · raw-frame mirror `0xd0009a2c`
- Functional low-speed cells: `0x803b528e` (10 km/h, #251), `0x803b5a30`/`0x803b5a36` (20/80 km/h
  windows, #260), `0x803b88ae` (3 km/h, #279)
- EGAS-L2 monitor cells: `0x80389809` / `0x8038980e` (#208) — see `l2_monitors.md`
