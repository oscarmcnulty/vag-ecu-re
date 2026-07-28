# ACC/cruise minimum-speed floor + EGAS-L2 monitor twin (MED17.1.1 8R0907115N_0006)

Answer to the two min-speed questions, built on the resolved `a9 = cal-object table` (see `a9_resolution.md`)
so every `*(a9+off)` folds to a concrete cal object. Built 2026-07-26 from the folded corpus
(`analysis/decompiles_r/`) + firmware reads. Load base `0x80000000`; file off = `addr & 0x1FFFFFFF`;
`0xa00xxxxx` = uncached alias; RAM = `0xd00xxxxx`.

Confidence tags: **[C]** read the code/bytes · **[I]** inferred · **[G]** gap.

> ## ⚠ UPDATE 2026-07-27 — read `maps/l2_monitors.md` (this doc's §Q2 is superseded)
> An 8-subagent characterisation of every EGAS-L2 monitor, plus the **empirical** result (openpilot below
> 15 km/h latches a non-volatile ACC lockout, key-off-on to clear), corrected the picture:
> - **The operative ACC min-speed lockout is ONE hysteresis pair in cal #208: `0x80389809`=15 (SET) and
>   `0x8038980e`=7 (CLEAR)** → `MON_cru_permit_flags` bit7 → latch `d00148be` → `d00000e1.b4` → stored Dem DTC.
>   It is gated on `cru_acc_active_flag` (d000a113), i.e. it only faults when cruise/ACC is the active
>   controller — that is what makes it the ACC monitor. **The 7-CLEAR edge was missing from §Q2 below; it must
>   be zeroed too** (so the permit holds through standstill — see the A2L GROUP 1 note).
> - **The other cells in the §Q2 table are NOT the ACC floor.** #148 (`0x80384760/61`, `800d5828`) is a general
>   torque monitor that **provably self-disables below ~12 km/h**; #215 (`0x8038a5c6/c9/ca`, `800f5d68`) is a
>   crawl monitor whose trip runs only in a **failsafe branch** (signal 0x3fc stale). Neither is the lockout.
> - **The "move L1/L2 together" premise (§Q1b verdict, §Q2 "Move both", Summary Q2) is WRONG.** The functional
>   L1 cells and the L2 monitor are independent; the lockout is #208's 15/7 alone. The functional decel/hold
>   path is cal-map-driven to standstill and engagement is a table-driven state machine with **no speed gate**
>   (`maps/engage_state.md`), so the L1 cells are behavioural, not required. **Edit only #208 `0x80389809`+`0x8038980e`→0.**
>
> §0, §Q1 (functional cell inventory), and §Q1b (creep gate = leave stock) below remain valid.

---

## 0. Ego-speed variable + scale  ⭐ (the anchor) — [C]

MED17 keeps **two** ego-speed shadows, exactly the Simos8.5 `d000d644`(functional)/`d000da54`(monitor) split:

| role | variable | scale | evidence |
|---|---|---|---|
| **Functional ego speed** | **`DAT_d0008f5e`** (core ctx 0), **`DAT_d0008c22`** (core ctx 1) | **0.01 km/h** (100 cnt = 1.00 km/h) | `DAT_d000a139 = (DAT_d0008f5e < 100)` = the "< 1 km/h" standstill flag (`80199130:29`, `801991c4:31`); every speed cal read against it lands on clean km/h at 0.01 (cal #247 axis `0x803b4eb6…` = 1200/1400/1600/1800/2000/2200/2400/2660 = 12.0…26.6 km/h in clean 2 km/h steps). **[C]** |
| **Monitor (L2) ego speed** | **`DAT_d0007b8a`** | **1/128 km/h** (128 cnt = 1.00 km/h) | `DAT_d0007b8a = FUN_8007dc3c(DAT_d0008f5e * 0x20, 0x19)` = `func_speed × 32/25` (`80199130:15`; ctx-1 `801991c4:15` uses `DAT_d0008c22`). This is the **identical `×32/25` conversion Simos used** for `d644`. Proven decisively: ~30 monitor cals compared `d0007b8a </<= cal·0x80` (=`·128`) all resolve to **clean integer km/h** (see §2). **[C]** |

`d0008f5e × 32/25 = d0007b8a` ⇒ `d0008f5e(0.01 km/h) × 100/km/h × 32/25 = 128/km/h` ✓ — the two scales are self-consistent.

---

## Q1 — Functional (L1) ACC/cruise minimum speed

**Headline finding: unlike Simos8.5 there is NO single hardcoded `C_VS_MIN_CRU` engage-floor cell.** The
MED17 functional ACC/cruise min-speed is enforced as a **layered set of low-speed thresholds** in the ACC
decel controllers and the GRA/cruise operating logic (all comparing the 0.01-km/h ego speed
`d0008f5e`/`d0008c22`), and the ACC **master engage precondition itself is table-driven** through the state
machine `FUN_800accac` (descriptor `0x8003f374`) — that specific precondition is **[G]** (no C-visible speed
cal). The concrete, editable functional speed cells found:

| flash addr | cal obj (#, base) | value | function : line | what it gates | conf |
|---|---|---|---|---|---|
| **`0x803b528e`** | #251 `0x803b5230` +0x5e | **10.00 km/h** | `801455ae:60` (ACC/ESP decel coordinator, gate `d000a454==2`) | `cal < d0008f5e` → clears `d0009e1b`/`d000aafe` (the low-speed ACC creep/approach sub-state) | **[C] code / [I] role** |
| `0x803b5a30` | #260 `0x803b59a6` +0x8a | 20.00 km/h | `802c35d8:200` (GRA/cruise/limiter logic, 5× `a454`/`a3c1`/`ab1b` refs) | lower window `[0,20]` for a cruise sub-feature enable | **[C] code / [I] role** |
| `0x803b5a36` | #260 +0x90 | 80.00 km/h | `802c35d8:518` | second window `[80,140]` | [C]/[I] |
| `0x803b88ae` | #279 `0x803b8762` +0x14c | 3.00 km/h | `8030347a:276` | `d0008f5e <= cal` creep gate | [C] |
| (literal) | — | 3.01 km/h (`< 0x12d`) | `802c23b8:120` | hardcoded creep threshold (firmware, not a cal) | [C] |
| cal #247 `0x803b4834` | many `+…` = 2000 | 20.00 km/h ×~60 | `801418ea` decel-shaping | ACC decel-map speed axes/thresholds (0.01 km/h) | [C] |

Notes / caveats:
- **cal #247 (`0x803b4834`, 1768 B, via `a9+0x3dc`) and cal #251 (`0x803b5230`, 96 B, via `a9+0x3ec`)** are
  the ACC-functional cal objects; **cal #260 (`0x803b59a6`, 150 B, via `a9+0x410`)** is the GRA/cruise/limiter
  object (adjacent to the ACC cals, references cruise state). All functional speed cells live in the
  **`0x803b_xxxx` cal region.**
- The `35 km/h` window (`0x803e0bd4`, obj #838) and the `[0,20]/[80,140]` windows are **feature/CAN-signal
  plausibility windows**, *not* the ACC engage floor (`802c0c24/66/d78/dee` are a self-contained speed-signal
  diagnostic with no cruise-state reference — checked & excluded). Do not treat 35 km/h as the floor. **[C]**
- **The B8 Q5's ~30 km/h ACC floor is a single-radar *hardware* property** (repo memory `b8-acc-radar-hardware`):
  the radar simply never issues ACC requests below ~30 km/h, so no engine-ECU cal needs to encode 30. This is
  the most likely reason no clean 30 km/h engine-side engage cal exists. **[I]**

**openpilot lever (lower the functional floor):** the layered low-speed thresholds above are the editable
cells (`0x803b528e` 10→lower; `0x803b88ae`/creep 3 km/h family). Lowering them relaxes the low-speed
behaviour, but because engagement is table-driven + radar-gated, cal edits alone will not reach standstill —
openpilot supplies the sub-floor request itself; keep it E2E-valid on ACC_01 (0x109). All cal edits need a
cal-block checksum recompute (`core/checksum`).

## Q1b — the 3 km/h creep gate: **stock value is fine, no modification needed** [C]

Investigated 2026-07-27 (does the creep gate block openpilot's low-speed/standstill control?). **It does not.**
- The two 3 km/h "creep gate" cells are **diagnostic, not control gates**:
  - `0x803b88ae` (3.0 km/h, `8030347a:276`) sets `DAT_d000f737/738/f73c` — and **`d000f73c` has zero readers
    in the control path** (`8030347a` is in the `0x8030_xxxx` diagnostic/observer block). Dead measurement flag.
  - the 3.01 km/h literal (`802c23b8:120`) sets `DAT_d0002a14`, used only *locally* inside that `0x802C`
    status function (`:153/:194`). Neither cell gates ACC availability nor touches the accel/decel setpoint.
- **No hardcoded low-speed barrier in the hold/decel path** — the decisive contrast with Simos8.5, whose
  sub-15 barrier was a hardcoded `1000` (7.81 km/h) literal at `8013ef46:258` needing a firmware patch.
  MED17's decel controller `801434de` uses vehicle speed (`d0008f5e`) **only as the X-axis input to cal maps**
  (`func_0xc0000638`/`func_0xc00004ca` over cal `*(a9+0x3e4)`=#249 / `*(a9+0x3d8)`), no hardcoded speed compare;
  the map axes reach to standstill.
- **openpilot's control flows through the stock creep/anfahren logic:** the standstill/hold `DAT_d000a365`
  (`801434de:85-93`) is gated on the hold bit `DAT_d000a35c` = the **`ACC_Anhalten` bit openpilot sets in
  ACC_01**; the drive-off/anfahren (`801405d4` → `DAT_d000ab00`, read by `80140922`/`801418ea`) is gated on ACC
  engaged (`a454==2`) + regulating (`a361∈{1,5}`), states openpilot maintains as ACC master. The anfahren
  *shapes* drive-off torque following the commanded accel rather than blocking it.
- **Residual (behavioral, not a gate):** the anfahren torque profile is cal `*(a9+0x3d8)` = `PTR_DAT_8010383c`.
  If stock creep torque feels wrong under openpilot at very low speed, that's a *tuning* edit to that map —
  not required for control. No evidence of uncommanded creep against openpilot's hold (hold `a35c` suppresses
  drive-off via `a365`).

**Verdict:** leave the creep-gate cells stock. Sub-floor operation depends on lowering the EGAS-L2 monitor
permit floor **`0x80389809`=15 + `0x8038980e`=7 (both →0)** and openpilot supplying its own request — not on
the creep gate, and not on the functional L1 cells (see the UPDATE banner + `maps/l2_monitors.md`).

---

## Q2 — EGAS Level-2 monitor twin  ⭐ — **YES, present and architecturally separate** [C]

There is a full **EGAS L2 monitor cluster (~20 functions at `0x800d_xxxx … 0x8010_xxxx`)** — the Bosch
"Überwachung" level — that:

1. Reads its **own monitor ego speed `DAT_d0007b8a`** (1/128 km/h), distinct from the functional
   `d0008f5e`/`d0008c22`.
2. Reaches calibration through a **completely separate set of cal-object-table pointers** — `a9+0x250` /
   `+0x2b4` / `+0x2cc` / `+0x304` and the `a9+0x33c…0x35c` block (`PTR_WORD_ARRAY_801036b4`, `_80103718`,
   `_80103730`, `_80103768`, `_801037a4`, `_801037a8`, `_801037b0`, `_801037b8`, `_801037bc`, `_801037c0`) —
   all pointing at cal objects in the **low `0x80384xxx … 0x8038axxx` region**, i.e. **disjoint from the
   functional ACC cals at `0x803b_xxxx`.** This is exactly the Simos8.5 "`egas_l2_monitor_cal_init` at a
   different cal base" twin architecture. **[C]**
3. Compares speed with the tell-tale `d0007b8a </<= cal·0x80` form (u8 km/h × 128), all resolving to clean
   integer km/h — the direct analog of Simos `da54 <= C_VS_MIN_CRU_MON·0x80`.

Representative monitor speed floors (u8, km/h) that were read out of flash and confirmed. **⚠ SUPERSEDED
classification — see the UPDATE banner + `maps/l2_monitors.md`: of the cells below, ONLY `0x80389809`=15 (and
its CLEAR twin `0x8038980e`=7, missing from this table) is the genuine ACC lockout. `0x80384760/61` (#148)
and `0x8038a5c6` (#215) are general/failsafe EGAS monitors, NOT the ACC floor. `0x8038980a`=17 is a *separate*
band's set-edge, not the 15-floor's hysteresis.**

| flash addr | cal obj | value | function : line → latch | note |
|---|---|---|---|---|
| **`0x80389809`** | #208 `0x803896ec` +0x11d | **15 km/h** | `800f027c` / `800f006c:729` → `d000dc87`→`d000d7d1.b7` | **exact Simos `C_VS_MIN_CRU_MON`=15 analog** |
| `0x8038980a` | #208 +0x11e | 17 km/h | `800f006c:130` → `d000dc78` | hyst upper |
| `0x80389808` | #208 +0x11c | 2 km/h | `800f006c:135` | hyst band |
| `0x80389812` / `0x80389813` | #208 +0x126/+0x127 | 17 / 14 km/h | `800f006c` → `d000dc88` | window |
| `0x80389810` / `0x80389811` | #208 +0x124/+0x125 | 65 / 10 km/h | `800f006c:1499` | monitor band |
| `0x80384761` / `0x80384760` | #148 `0x8038436a` +0x3f7/+0x3f6 | 5 / +7 | `800d5828:191` → `d000d867` | low-speed monitor |
| `0x8038a5c6` | #215 `0x8038a568` +0x5e | 20 km/h | `800f5d68` | monitor floor |
| (literal) | — | 3.01 km/h (`< 0x181`) | `800dc570:30` | hardcoded monitor creep |

**Is there an exact numeric TWIN of a functional floor?** The L2 monitor is **value-independent** of the
functional path (it recomputes its own speed and thresholds), so it is not a byte-for-byte mirror of one
functional cell. The closest correspondence is the **15 km/h monitor floor `0x80389809`** ↔ the functional
10–20 km/h low-speed thresholds. There is **no L2 copy of a "35 km/h"** (that functional value was excluded
as CAN-plausibility, not a floor). **[C on separateness; I on which pairs are the intended L1/L2 partners]**

**"Move both" caveat — ⚠ SUPERSEDED (see UPDATE banner):** this doc originally inferred you must move a
functional L1 cell together with a matching L2 monitor cell. The 8-agent investigation refuted that: the
monitors are independent of the functional path, and the ACC lockout is the #208 **15/7 permit pair alone**
(`0x80389809`+`0x8038980e`), gated on cruise-active. You do **not** need to move functional L1 cells with it.
The retained truth: lower **both** #208 permit edges (15 and 7) together, or the permit flips at standstill.

---

## Summary of confirmed addresses

- **Functional ego speed:** `DAT_d0008f5e` / `DAT_d0008c22`, **0.01 km/h**. [C]
- **Monitor ego speed:** `DAT_d0007b8a` = `func×32/25`, **1/128 km/h**. [C]
- **Functional low-speed cells (0x803b region):** `0x803b528e` (10 km/h, cal#251), `0x803b5a30`/`0x803b5a36`
  (20/80 km/h windows, cal#260), `0x803b88ae` (3 km/h). Engage precondition proper = table-driven [G].
- **L2 monitor cells (0x8038 region, separate cal base):** `0x80389809` (15 km/h, cal#208) + the 17/14/10/65/
  20/5 km/h family; monitor speed `d0007b8a`.
- **Q1 verdict:** no single `C_VS_MIN_CRU` cell; layered thresholds + radar-hardware 30 km/h floor. [C/I/G]
- **Q2 verdict (CORRECTED 2026-07-27):** the EGAS-L2 monitor cluster is present + separate, but only **cal #208
  (`0x80389809`=15 / `0x8038980e`=7)** is the genuine ACC lockout (gated on cruise-active). Most other cells in
  the §Q2 table are general EGAS torque/speed monitors, NOT ACC. **Edit #208's 15+7 →0.** See `maps/l2_monitors.md`.
