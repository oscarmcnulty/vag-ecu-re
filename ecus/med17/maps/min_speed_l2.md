# ACC/cruise minimum-speed floor + EGAS-L2 monitor twin (MED17.1.1 8R0907115N_0006)

Answer to the two min-speed questions, built on the resolved `a9 = cal-object table` (see `a9_resolution.md`)
so every `*(a9+off)` folds to a concrete cal object. Built from the folded corpus
(`analysis/decompiles_r/`) + firmware reads. Load base `0x80000000`; file off = `addr & 0x1FFFFFFF`;
`0xa00xxxxx` = uncached alias; RAM = `0xd00xxxxx`.

Confidence tags: **[C]** read the code/bytes · **[M]** measured on-car · **[I]** inferred · **[G]** gap.

**The ACC min-speed gate is EGAS-L2 cal #208 (`FUN_800f006c`/`800f027c`), SET edge `0x80389809` = 15 km/h.**
On-car the engine enforces a floor at **15 km/h**: it refuses to grant ACC below it, arms within one 20 ms
frame above it, and signals nothing (no DTC, no limp, `TSK_04` never 3). Below the floor the ACC command is
withheld **completely** — `TSK_Verzoeg_Anf`/`TSK_Radbremsmom` are exactly zero, not attenuated. Above it,
they track `ACC_Sollbeschleunigung` to one 0.024 m/s² quantum. First grant came above 15; after a drop, the
re-arm landed at 15.80–15.90 km/h — the SET edge, exactly. **[M]**

#208 reaches the ACC command not as a permit but as a **fault contributor**: permit bit7 clear →
`DAT_d000d7f9` (`800f006c:728`) → `FUN_800d9936` aggregator (`:71`) → `EGAS_L2_fault_verdict` (d000d344) →
`EGAS_L2_reaction_level` (d000aa23) → the 0x8031 ACC/DCC controller. That is why the withhold is silent —
it is a reaction *level*, not a latched DTC. Full chain in `maps/l2_monitors.md`. **[C]**

Two model corrections from the code: bit7 is an **arming pulse** (re-initialised false each cycle, assigned
only while the engaged latch is 0), not a sustained permit; and the 7 cell only clears `dc87` rather than
holding a permit open down to 7.

The `dc8b` suppression term is fully resolved, and it is **eliminated** as the min-speed mechanism (see
`maps/l2_monitors.md`): `dc8b = cru_acc_active_flag && d240<=8 && a0a9 && (gear_sel_state ∈ {6,8})`. The
state chains `d0009f76` → `d000a89a` = `tbl[d000a6c3]`, and `d000a6c3` is bound by the COM descriptor table
to **`Getriebe_03` (0x102) bit 44 len 4 = `GE_Waehlhebel`** — the **gear selector lever**, not a cruise
state. On-car it steps P→R→N→D (`5→6→7→8`) at drive start and holds **D** throughout, so `{6,8}` = selector
in R or D, and the term was satisfied across both 15 km/h transitions. That also explains why `80087a70`
and the `80143b8a` state machine contain no speed reference: they are gear logic. **[C]/[M]**

There is no key-off-on lockout on MED17 — all state is volatile RAM, no non-volatile store exists in the
corpus for this path, and the on-car floor is fully self-recovering. **[C]/[M]**

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

**openpilot lever (lower the functional floor):** the table-driven engage precondition is the barrier that
matters, and it is `[G]` — none of the cells in the table above produces the measured 15 km/h symmetric
floor (10, 20, 3 and 80 km/h are all excluded by the measured 14.90–48.25 km/h granted range). Since the
precondition is reached through a descriptor table and no C-visible speed cal sits on it, the compare is
plausibly a **code literal** — which is exactly why cal edits do not move this floor. **[M]/[I]**

Search key for the missing compare: functional ego speed `d0008f5e`/`d0008c22` (0.01 km/h) against
**1500** (`0x5dc`), or monitor speed `d0007b8a` (1/128 km/h) against **1920** (`0x780`), reached from
`FUN_800accac` / descriptor `0x8003f374`.

**`TSK_01` frame bit 23 is EXCLUDED as the floor — traced to the bottom, no speed threshold on it. [C]**
Bit 23 tracks the floor in the log (set ≤15 km/h, clear above, leading the ACC drop by one frame), so it was
the best speed-correlated observable available. The full chain is now verified at instruction level, every
link by writer-enumeration rather than by grep (`st.t`/base+displacement stores included):

> frame bit 23 → `d0005e34` bit 7 (descriptor `0x80039460`, `sb=16 len=24`, message binding confirmed via
> the §6a table) → copy of `d0005e38` → copy of `d0004938` → `FUN_80143a68` packer slot `[a10]+0x0c`
> → `d00049c9` bit 2 → snapshot `d0004930` bit 5 → **`d000a346` bit 5**, written only at `0x80140d3c`

and there it terminates in

    a346 bit5 = (DSM_status(275) == 0) || cfg(0xd000017a).bit4

- `0xd000017a` has **no writer in disassembled code** — it is part of the absolutely-addressed, bit-tested
  config block loaded at startup, i.e. static variant coding.
- `FUN_800981cc` is a **DSM event-status getter**, not a CAN-presence check:
  `id < *(0x80027f88)=23` → bit 6 of `0xd000b083+id`, else bit 5 of `0xd000b117+id`. `FUN_80097fa4`
  initialises every entry to `0x20` and clears bit 5 when a path's test completes; `FUN_80098184` clears
  bit 4 and writes `0x8e` — ISO-14229 DTC status-byte semantics. So bit 5 is a **latched monitor-completion
  status**, which cannot produce clean hysteresis at 15.0 km/h.

**Correction:** the earlier reading of this site as `presence(CAN 0x113)` was wrong. `0x113` is a DSM path
index (275), not a CAN identifier — which is why it appears in no `vw_*.dbc` and on no bus, and it is also
absent from the §6a message table. No on-car observation was needed to settle this.

**Consequence:** bit 23's correlation with the floor is a *symptom* (a monitor reporting the same underlying
state), not the gate. It carries no calibratable threshold, so no cal edit on this chain can move the floor
and it should not be pursued further. The one nearby threshold that *is* calibratable —
`lt d8, cal_obj(0x3e8)[0x2f], RAM[0xd000499e]` at `0x80144f88`, feeding frame **bit 21** — holds **2**, not
15, and bits 18–21 are conditionally cleared downstream (`andn #0x3c`). Also not the floor.

The layered low-speed cells above (`0x803b528e` 10→lower; `0x803b88ae`/creep 3 km/h family) remain editable
and may matter for *behaviour* once the precondition is lifted, but none of them is the floor. All cal edits
need a cal-block checksum recompute (`core/checksum`). openpilot supplies the sub-floor request itself; keep
it E2E-valid on ACC_01 (0x109).

## Q1b — the 3 km/h creep gate: **stock value is fine, no modification needed** [C]

Does the creep gate block openpilot's low-speed/standstill control? **It does not.**
- The two 3 km/h "creep gate" cells are **diagnostic, not control gates**:
  - `0x803b88ae` (3.0 km/h, `8030347a:276`) sets `DAT_d000f737/738/f73c` — and **`d000f73c` has zero readers
    in the control path** (`8030347a` is in the `0x8030_xxxx` diagnostic/observer block). Dead measurement flag.
  - the 3.01 km/h literal (`802c23b8:120`) sets `DAT_d0002a14`, used only *locally* inside that `0x802C`
    status function (`:153/:194`). Neither cell gates ACC availability nor touches the accel/decel setpoint.
- **No hardcoded low-speed barrier in the hold/decel path.** MED17's decel controller `801434de` uses vehicle
  speed (`d0008f5e`) **only as the X-axis input to cal maps** (`func_0xc0000638`/`func_0xc00004ca` over cal
  `*(a9+0x3e4)`=#249 / `*(a9+0x3d8)`), with no hardcoded speed compare; the map axes reach to standstill.
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
the creep gate, and not on the functional L1 cells (see §Q2 + `maps/l2_monitors.md`).

---

## Q2 — EGAS Level-2 monitor twin  ⭐ — **present and architecturally separate** [C]

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

**Cal #208 is the ACC min-speed gate.** Its cells are `0x80389809`=15 (SET/arm) and `0x8038980e`=7
(clear), driving the permit memory `d000dc87` → `MON_cru_permit_flags` bit7. It is gated on
`cru_acc_active_flag` (`d000a113`), i.e. it acts only when cruise/ACC is the active controller — that is
what makes it the ACC monitor. bit7 clear then raises `d7f9` → the EGAS-L2 aggregator → verdict `d344` →
reaction `aa23` → the 0x8031 ACC/DCC controller, which is how a monitor flag ends up withholding the ACC
command silently. **[C]**

The measured arm edge matches the SET cell exactly (re-arm at 15.80–15.90 km/h). Still `[G]`: the drop at
14.93 km/h while already engaged, which needs the `d7f6`/`dc8b` suppression conditions traced. **[M]**

For openpilot, set **`0x80389809`=15→0 and `0x8038980e`=7→0**, recompute the cal checksum
(`core/checksum`), and **read the two bytes back over UDS after flashing** — an uncorrected block checksum
is the most likely cause of an edit that appears to do nothing. See `maps/l2_monitors.md`.

The following table is a **raw catalogue of L2 monitor-speed cells** read out of flash — useful for reference,
but note that these are general/failsafe EGAS supervision cells and, apart from #208, are **not** the ACC
floor. #148 (`0x80384760/61`, `800d5828`) is a general torque monitor that provably self-disables below
~12 km/h; #215 (`0x8038a5c6/c9/ca`, `800f5d68`) is a crawl monitor whose trip runs only in a failsafe branch
(signal 0x3fc stale). `0x8038980a`=17 is a separate band's set-edge, not the 15-floor's hysteresis.

| flash addr | cal obj | value | function : line → latch | note |
|---|---|---|---|---|
| **`0x80389809`** | #208 `0x803896ec` +0x11d | **15 km/h** | `800f027c` / `800f006c:729` → `d000dc87`→`d000d7d1.b7` | **ACC gate — SET/arm edge (Simos `C_VS_MIN_CRU_MON`=15 analog)** |
| **`0x8038980e`** | #208 +0x122 | **7 km/h** | `800f006c` → `d000dc87` | **ACC gate — re-arm/clear edge** |
| `0x8038980a` | #208 +0x11e | 17 km/h | `800f006c:130` → `d000dc78` | separate band set-edge |
| `0x80389808` | #208 +0x11c | 2 km/h | `800f006c:135` | hyst band |
| `0x80389812` / `0x80389813` | #208 +0x126/+0x127 | 17 / 14 km/h | `800f006c` → `d000dc88` | window |
| `0x80389810` / `0x80389811` | #208 +0x124/+0x125 | 65 / 10 km/h | `800f006c:1499` | monitor band |
| `0x80384761` / `0x80384760` | #148 `0x8038436a` +0x3f7/+0x3f6 | 5 / +7 | `800d5828:191` → `d000d867` | general torque monitor (self-disables <~12 km/h) |
| `0x8038a5c6` | #215 `0x8038a568` +0x5e | 20 km/h | `800f5d68` | failsafe crawl monitor |
| (literal) | — | 3.01 km/h (`< 0x181`) | `800dc570:30` | hardcoded monitor creep |

**Is there an exact numeric TWIN of a functional floor?** The L2 monitor is **value-independent** of the
functional path (it recomputes its own speed and thresholds), so it is not a byte-for-byte mirror of one
functional cell. The closest correspondence is the **15 km/h monitor floor `0x80389809`** ↔ the functional
10–20 km/h low-speed thresholds. There is **no L2 copy of a "35 km/h"** (that functional value was excluded
as CAN-plausibility, not a floor). **[C on separateness; I on which pairs correspond]**

The functional L1 cells (§Q1) and the L2 monitor are **independent** — there is no requirement to move an L1
cell together with an L2 cell. The ACC gate is #208's 15/7 permit pair alone, and both edges must be lowered
together (15 and 7 → 0) or the permit flips at standstill.

---

## Summary of confirmed addresses

- **Functional ego speed:** `DAT_d0008f5e` / `DAT_d0008c22`, **0.01 km/h**. [C]
- **Monitor ego speed:** `DAT_d0007b8a` = `func×32/25`, **1/128 km/h**. [C]
- **Functional low-speed cells (0x803b region):** `0x803b528e` (10 km/h, cal#251), `0x803b5a30`/`0x803b5a36`
  (20/80 km/h windows, cal#260), `0x803b88ae` (3 km/h). Engage precondition proper = table-driven [G].
- **L2 monitor cells (0x8038 region, separate cal base):** `0x80389809` (15 km/h, cal#208) + the 17/14/10/65/
  20/5 km/h family; monitor speed `d0007b8a`.
- **Q1 verdict:** no single functional `C_VS_MIN_CRU` cell. The layered functional cells (10/20/3/80 km/h)
  are all excluded by the measured 14.90–48.25 km/h granted range, and a sweep of all 5918 decompiles for a
  15 km/h literal in ten encodings finds no speed compare anywhere in the ACC cluster — so the floor is a
  cal, not code. `FUN_800accac`'s condition table provably holds no speed variable or cal. [C/M]
- **Q2 verdict:** the EGAS-L2 monitor cluster is present + separate, and **cal #208 (`0x80389809`=15 /
  `0x8038980e`=7)** is the ACC gate — the only ACC-specific member, holder of the only 15 in the ACC path,
  with a traced output chain (`d7f9` → aggregator → `d344` → `aa23` → 0x8031 ACC/DCC controller) and a SET
  edge matching the measured arm edge. The other cells in the §Q2 table are general EGAS torque/speed
  monitors, not ACC. **Edit #208's 15+7 →0, checksum-correct, and verify the read-back.**
  See `maps/l2_monitors.md`.
