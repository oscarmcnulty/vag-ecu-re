# EGAS Level-2 monitors — which ones gate ACC

Of the ~13 EGAS Level-2 ("Überwachung") monitors that read the monitor ego-speed `veh_speed_MON_128`
(`DAT_d0007b8a`, 1/128 km/h), **cal #208 is the one that gates ACC** — it is the only ACC-specific member
(gated on `cru_acc_active_flag`) and it has a live path into the ACC reaction level. The rest are general
torque/speed/plausibility supervision that merely *use* vehicle speed (as a map axis, a plausibility
window, or a disabled ceiling) and never touch the ACC engage/permit path. Not every `cal * 0x80` in these
monitors is a speed compare — torque/accel values are scaled `×0x40`/`×0x80` too.

Load base 0x80000000; file off = addr & 0x1FFFFFFF. Speed cells are u8 km/h, compared `cal*0x80` vs
`veh_speed_MON_128`. Recompute the cal-block checksum after any edit (`core/checksum`).

Confidence tags: **[C]** read the code/bytes · **[M]** measured on-car · **[I]** inferred · **[G]** gap.

## The ACC min-speed floor as the car actually enforces it  ⭐ **[M]**

Measured on the engine's own grant signal `TSK_04` (0x10E) `TSK_Status_GRA_ACC_02` (mirrored by `TSK_02`
(0x10C) `TSK_Status`), with openpilot as ACC master transmitting `ACC_01` (0x109) at a clean 20 ms period:

| property | measurement |
|---|---|
| Arm edge | grant issued **within one 20 ms frame** of the request, at 15.8–16.5 km/h |
| Drop edge | **14.93 km/h**, while continuously engaged from 48 km/h and still commanding `ACC_Status_ACC=3` |
| Granted-speed range | **14.90 – 48.25 km/h** |
| Denied-while-requesting | 0 – 9.15 km/h (7.8 s continuous at 4.6–6.2 km/h, again at 8.5–9.2 km/h) |
| Fault signalling | none — `TSK_04` never reaches 3, no DTC, no limp |
| Authority below the floor | **exactly zero** — `TSK_Verzoeg_Anf` = 0.000 and `TSK_Radbremsmom` = 0 |
| Authority above the floor | full — `TSK_Verzoeg_Anf` tracks `ACC_Sollbeschleunigung` to one 0.024 m/s² quantum |

So the floor is **symmetric at 15 km/h, with no hysteresis, no armed-permit persistence, and no fault**:
a silent withhold that arms and disarms on the same threshold, in both directions, within one frame. The
drop at 15 km/h is not driver-induced — it occurs with `LS_Abbrechen=0`, `ESP_Fahrer_bremst=0`
(0.0–0.3 bar), main switch on and `LS_Fehler=0`.

### How #208 reaches the ACC command — the output path  **[C]**

The permit state is **not** consumed as a permit by the ACC code. It leaves #208 as a *fault contributor*
into the EGAS-L2 aggregator, which is what ultimately throttles ACC:

```
veh_speed_MON_128 vs cal 0x11d(=15) / 0x122(=7)
   -> MON_cru_permit_floor_flag (dc87)          800f006c:~742
   -> MON_cru_permit_flags bit7                 800f006c:LAB_800f10b8
   -> DAT_d000d7f9                              800f006c:728   (set when bit7 is CLEAR and d7f6/dc8b == 0)
   -> FUN_800d9936  EGAS_L2_fault_aggregator    800d9936:71    (d7f9 -> fault contributor uVar18)
   -> EGAS_L2_fault_verdict   d000d344
   -> EGAS_L2_reaction_level  d000aa23
   -> 0x8031 ACC/DCC controller (80312f70 / 803147dc / 80315a54)
```

`800f006c` also feeds the aggregator through `d7e1` (:97), `d7e8` (:182), `d7e7` (:183 → `d000d342`) and
`d7ef` (:201). So the "below the floor" condition — permit bit7 clear, i.e. speed under the 15 cell with the
memory unarmed — is exactly what raises the contributor, and the reaction lands on the ACC controller. The
withhold is silent because it is a reaction *level*, not a latched DTC.

Two corrections to the older reading of this block, both from the code:

- **bit7 is an arming pulse, not a sustained permit.** `bVar23` is re-initialised to `false` every cycle and
  only assigned inside the `MON_cru_speed_engaged_latch == 0` block, so once the latch arms, bit7 reads back
  0. The suppression that keeps `d7f9` low during normal engaged driving comes from `d7f6` (= `dc8b`), not
  from bit7 staying set.
- **The "re-engage anywhere down to 7 km/h" behaviour does not follow from this shape.** The 7 cell only
  clears `dc87`; it does not hold a permit open. That is consistent with the measured drop at ~15 rather
  than at 7.

### The `dc8b` suppression term — resolved  **[C]**

`dc8b` is what holds `d7f9` low during normal engaged driving. Its full condition, with the config word
`cal #208 +0x148 = 0x1bf3` (@`0x80389834`) collapsing terms 1 and 2 to unconditionally true:

```
dc8b = cru_acc_active_flag(d000a113) && d000d240 <= 8 && d000a0a9 && (state == 6 || state == 8)
```

The state test is the live term. Chain, all read from flash:

```
state = iVar25 = FUN_8010295e(cal+0x49, cal+0x36, d0009f76)
        cal+0x49 LUT @0x80389735 is an IDENTITY map over 0..17  ->  state == d0009f76
d0009f76  = shadow copy of d000a89a          (802c4942:155 / 802c4ee8:28, the L1->L2 shadow block)
d000a89a  = tbl[d000a6c3]                    (80087a70, sole writer)
    tbl @0x800453b4 = identity[0..14]        when (d0008c80 & 0x610)==0 && (d0008c80 & 0x1000)==0
    tbl @0x80045395 = [0,0,0,0,0,8,7,6,5,12,17,0,0,14,14]   otherwise (5->8, 6->7, 7->6, 8->5)
```

`FUN_80087a70` itself computes `a89a == 6 || a89a == 8` at its tail — the same pair. **[C]**

**What the state actually is: the GEAR SELECTOR, not a cruise state.** `d000a6c3` is bound by the COM
descriptor table (record `@0x80039c08`, desc `0x42c` = bit 44 len 4) inside the **`Getriebe_03` (0x102)**
PDU group `@0x80039be0` — 75% DBC geometry match — i.e. **`GE_Waehlhebel`**. The on-car log proves it: the
field steps `5 -> 6 -> 7 -> 8` (P→R→N→D) as the driver moves the lever at drive start and reverses the
sequence at drive end, sitting constant at **8 (D)** in between. So `{6,8}` means **selector in R or D**,
and `d7ed`/`d7f1` are debounced "in R" / "in D". This is why `80087a70` and the `80143b8a` state machine
contain no speed reference at all — they are gear logic. **[C]/[M]**

**Consequence: `dc8b` cannot explain the ~15 km/h drop.** The selector was constant at D from t=124.6 to
t=181.9, spanning the entire ACC engagement and both 15 km/h transitions, so `dc8b`'s state term held
throughout. The earlier reading — that `dc8b` drops because a *cruise* state machine left its controlling
states — was wrong, and with it the cause-vs-effect question it raised. #208's `d7f9` path stays real
(§ above), but this particular suppression term is eliminated as the mechanism. **[M]**

**Where the static trace ends `[G]`.** The record→PDU grouping is now solved: records for one message are
contiguous at 40-byte stride with **descending** bit positions, so a message boundary is where the bit
position resets upward — that segments the 560 records into 133 PDU groups, which match the DBC by
geometry. What remains open is the ACC *mode* arbitration feeding `d000a3c1` → `d000a454`, which is the
gate that survives (see `min_speed_l2.md` §Q1).

**Status of the 15 as the observed floor:** #208's SET edge is the strongest candidate and has a mechanism
end-to-end. It matches the measured arm edge (first grant above 15; re-arm at 15.80–15.90 after a drop)
exactly. Corroborating negative: a sweep of all 5918 decompiles for a 15 km/h literal in ten encodings
(1500 @0.01, 1920 @1/128, 3840 @1/256, 960, 480, 240, 150, 15, 417, 4167) finds **no** speed compare
anywhere in the ACC cluster, so a hard-coded 15 elsewhere is unlikely; if the floor is anywhere, it is a
cal, and #208 holds the only 15. **[C]/[M]**

The remaining alternative, if #208 is ever ruled out, is the table-driven ACC master engage precondition
(`FUN_800accac`, descriptor `0x8003f374`, `[G]` in `min_speed_l2.md` §Q1). Against it: `800accac`'s
condition table provably contains no speed variable or cal, its conditions arrive pre-computed through an OS
mailbox (`FUN_800ad364` over `d0009b48`), and the literal sweep above finds no 15 anywhere. **[C]/[I]**

## Cal #208 — the ACC gate

**`FUN_800f006c`/`FUN_800f027c` (`EGAS_L2_cru_speed_monitor_A`/`_B`) over cal #208 @0x803896ec** — the
EGAS-L2 cruise/ACC speed-control plausibility monitor (`C_VS_MIN_CRU_MON`). It is **gated on
`cru_acc_active_flag` (d000a113)**: its logic runs only when cruise/ACC is the active longitudinal
controller — which is what makes it ACC-specific, unlike every torque monitor. Its cell inventory is read
directly from flash and is sound; what is *not* established is that it ever gates ACC in practice. **[C] on
cells / [G] on whether it has any observable effect.**

### The permit floor — a persistent memory with a latch-gated feedback  **[C]**

`MON_cru_permit_floor_flag` (`dc87`) is a **persistent hysteretic memory** — SET when speed > 15, CLEARED
when speed < 7 — written only in the floor block (`800f006c:742` / `800f027c:656`) and reset nowhere (it
persists across latch cycles and ACC on/off; zeroed only at key-on). The floor block runs only while
`MON_cru_speed_engaged_latch` (d00148be) == 0 — the *arming phase*. When ACC is active and `dc87`=1 →
`MON_cru_permit_flags` (d000d7d1) bit7 = 1 → the latch arms, and holds until ACC-off or a `d000d240` 0x8f→8
recovery.

| cell | km/h | role in the static model |
|---|---|---|
| `0x80389809` (+0x11d) | 15 | ARM-from-scratch edge — with `dc87`=0, speed must exceed 15 to set `dc87`=1 |
| `0x8038980e` (+0x122) | 7 | RE-ARM floor — once `dc87`=1 it stays 1 down to 7 |

Secondary arming windows in the same object (leave stock): 17/15 band (`0x8038980a`=17, `0x80389808`=2-width),
5 band (`0x8038980f`), [10,65] window (`0x80389811`/`0x80389810`), 17/14 window (`0x80389812`/`0x80389813`).

The measured drop edge (14.93 km/h) rules out the 17/14 and 17/15 windows as the operative gate too: ACC was
granted at 15.80–15.90 km/h, below 17. **[M]**

### Why there is no persistent lockout  **[C]**

Every element in the #208 → reaction chain is volatile RAM recomputed each cycle: `dc87` re-arms by speed,
the engaged latch clears the instant ACC deactivates (`800f006c:791`), and `EGAS_L2_fault_verdict` is
overwritten at `800d9936:260`. `d00148be` is a monitor-*engaged* latch (its set-term `d7f2` requires bit7
*SET* = permitted — the polarity of an arm, not a "too-slow" fault), and `EGAS_mon_diag_status` (d00000e1)
bit 0x10 is a per-cycle mirror of it with zero internal readers. `#208` writes none of the torque-limp
aggregator's inputs — its outputs are pure cruise-permit state (`d7d1`/`d7d2`/`dc8b`…). The corpus contains
no `Dem/eeprom/nvram/WriteBlock` symbols, so nothing here stores a key-cycle fault. This is corroborated
on-car: the floor is fully self-recovering, with no key-cycle memory and no DTC. **[M]**

## ACC-relevant, secondary (indirect)

- **`FUN_800f4abe` — cal #213 @0x8038a3c8 (`EGAS_L2_ACC_longsetpoint_band_213`).** Bounds the ACC longitudinal
  setpoint (`MON_acc_long_setpoint` d000d5aa) inside speed/dwell rails; its sub-faults feed #208 and the
  aggregator → `d344`→`aa23`→ the 0x8031 ACC/DCC controller. Genuine speed edges: `0x8038a4ec`=0 and
  `0x8038a4ed`=25 km/h (the 16/18/16 and 12 cells are torque/accel rail coefficients, not speed floors). The
  25 km/h edge only enables one sub-check. Not the floor — ACC is granted and fully authoritative from
  14.90 km/h upward, straight through 25. **[M]**
- **`FUN_800f5d68` — cal #215 @0x8038a568 (`EGAS_L2_cru_lowspeed_crawl_215`).** Cruise/ACC low-speed crawl
  monitor; severity → cruise fault-reaction manager `800dca9c` + aggregator. Crawl arming windows
  `0x8038a5c9`/`ca`=6, `0x8038a5cd`=5. Its crawl trip runs only in the failsafe branch (when internal signal
  0x3fc is stale — at startup / on message-loss); whether it fires in normal operation depends on whether
  0x3fc's source PDU is on the Q5 bus (`[G]`, table-decode). `0x8038a5cb`=0 disables one transition. Validate
  on the bench before editing.

## NOT ACC monitors (general EGAS L2 — leave stock)

All read `veh_speed_MON_128` but reference zero ACC variables; their outputs go to the EGAS torque-limp path
(`EGAS_L2_fault_aggregator` FUN_800d9936 → verdict d344 → aa23), not the ACC engage/permit path.

| fn | cal | role |
|---|---|---|
| `800f25e2` | #209 | engine-torque plausibility; 8/5/0 = torque-check windows; 255/254 disable gates |
| `800f5982` | #214 | torque-vs-speed; 10 = low-speed suppression term |
| `800df26a` | #173 | torque-corridor; 15 is a `[15,105]` torque-window bound, not the ACC floor |
| `800f40bc` | #211 | channel/pedal voting; 255 = disabled over-speed ceiling |
| `800fb796` | — | torque coordinator, enabled only 25-130 km/h |
| `800e0a66` | — | accel/torque model (speed = map axis); holds the monitor twin of the ±500000 rail |
| `800f9520` | — | road-load model (v² drag); speed = physical axis |
| `800e759e` | #193 | step/DTC sequencer; 6 suppresses itself at low speed |
| `800d5828` | #148 | torque plausibility; no low-speed fault (self-disables below ~12 km/h) |

## Reaction architecture

The general L2 monitors → `EGAS_L2_fault_aggregator` (FUN_800d9936) → fault dwords `d000d32c/d334/d338` →
verdict `EGAS_L2_fault_verdict` (d000d344, 0-3) → `EGAS_L2_reaction_level` (d000aa23), read by the 0x8031
ACC/DCC controller = the EGAS-3 torque-limitation/limp reaction. #208 does **not** feed this aggregator; its
outputs are cruise-permit state only. Consistent with the on-car picture, in which the sub-15 withhold
carries no fault, no DTC and no torque limp. **[M]**

## Bottom line for openpilot control to 0

1. **Cal #208 stays the primary edit.** Set `0x80389809` (15→0) and `0x8038980e` (7→0), then recompute the
   cal-block checksum (`core/checksum`). It is the only ACC-gated L2 monitor, it holds the only 15 in the
   ACC path, it has an end-to-end mechanism to the ACC reaction level (§ above), and its SET edge matches
   the measured arm edge exactly.
2. **Flash a checksum-corrected image and verify it landed.** A cal edit with a stale block checksum is the
   single most likely reason for an edit that appears to do nothing. Read the two bytes back over UDS after
   flashing before drawing any conclusion from a test drive.
3. **Pin `d7f6`/`dc8b` before assuming one flash is enough** — the drop at ~15 km/h while already engaged is
   not explained by the SET edge alone and needs the `dc8b` conditions traced (`[G]`).
4. **Then re-measure, and expect a possible new number.** If a floor reappears at a different speed, the next
   candidates are #213's 25 km/h edge (`0x8038a4ed`) and the #215 crawl window (`0x8038a5c9`/`ca`=6, only if
   its failsafe branch is active) — both listed above.

Everything else in this file is general EGAS torque/speed supervision — leave stock.
