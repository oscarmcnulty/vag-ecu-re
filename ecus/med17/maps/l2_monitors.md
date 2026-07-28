# EGAS Level-2 monitors — which actually gate ACC (8-agent investigation, 2026-07-27)

Empirically: openpilot commanding ACC (ACC_01, 0x109) below **15 km/h** latches a **non-volatile fault**
(ACC inhibited until key-off-on). We characterised every L2 monitor that reads the monitor speed
`veh_speed_MON_128` (DAT_d0007b8a, 1/128 km/h) with one subagent each, reading the full decompile and
tracing outputs. Result: **only ONE monitor is the genuine ACC min-speed floor**; the rest are general
EGAS torque/speed/plausibility supervision that merely *use* vehicle speed. This corrects the earlier
mechanical "28 speed-floor cells" count — most `* 0x80` operations are **torque scaling (×0x40/×0x80), not
speed compares**, and most of these monitors never touch ACC.

Load base 0x80000000; file off = addr & 0x1FFFFFFF. All speed cells u8 km/h, compared `cal*0x80` vs
`veh_speed_MON_128`. Recompute the cal-block checksum after any edit (core/checksum).

## The ONE genuine ACC min-speed floor  ⭐

**`FUN_800f006c`/`FUN_800f027c` — cal #208 @0x803896ec — `EGAS_L2_cru_speed_monitor_A`/`_B`.**
The EGAS-L2 cruise/ACC speed-control plausibility monitor (`C_VS_MIN_CRU_MON`). **Gated on
`cru_acc_active_flag` (d000a113)** — its floor/latch runs only when cruise/ACC is the active controller
(this is what makes it ACC-specific, unlike every torque monitor). 

- **Operative floor = 15-SET / 7-CLEAR hysteresis pair → `MON_cru_permit_flags` (d000d7d1) bit7:**
  | cell | km/h | role |
  |---|---|---|
  | **`0x80389809`** (+0x11d) | **15** | ARM-from-scratch edge. With the permit memory `dc87`=0 (key-on init, or after it cleared), speed must exceed 15 to set `dc87`=1 and arm the engaged-latch. |
  | **`0x8038980e`** (+0x122) | **7** | RE-ARM / memory-clear edge — **LIVE, not dead.** `dc87` (SET at 15, CLEAR at 7) is a *persistent, never-reset* hysteretic memory. Once =1 it stays 1 down to 7, so ACC can drop and **re-engage anywhere down to 7**; below 7 (while un-latched) `dc87` clears → must exceed 15 to re-arm. |
- Secondary arming windows (NOT the operative floor, generally leave stock): 17/15 band
  (`0x8038980a`=17, `0x80389808`=2-width), 5 band (`0x8038980f`), [10,65] window (`0x80389811`/`0x80389810`),
  17/14 window (`0x80389812`/`0x80389813`).

**The fault mechanism (resolved 2026-07-27, two subagent passes — supersedes the "bit7=0 is the fault" reading):**
- **The permit floor is a latch-gated feedback loop over a PERSISTENT permit memory; the trigger is the
  engaged-latch FAILING TO ARM.** `MON_cru_permit_floor_flag` (`dc87`) is a hysteretic memory — SET at >15,
  CLEARED at <7 — that is **written only in the floor block (`800f006c:742` / `800f027c:656`) and reset
  NOWHERE** (persists across latch cycles and ACC on/off; zeroed only at key-on). The 15/7 block runs only
  while `MON_cru_speed_engaged_latch`==0 (`800f006c:728`) — the *arming phase*. When ACC is active and
  `dc87`=1 → `bit7`=1 → the latch ARMS and then HOLDS until ACC-off or a `d000d240` 0x8f→8 recovery
  (frozen while latched). So **both cells are live, for different engagements:**
  - **`0x80389809`=15 (arm-from-scratch):** with `dc87`=0, speed must exceed 15 to set it.
  - **`0x8038980e`=7 (re-arm floor):** once `dc87`=1 it stays 1 down to 7, so ACC can drop and **re-engage
    down to 7** and re-arm immediately; below 7 (un-latched) `dc87` clears → must exceed 15 again.
  **Behaviour:** continuous engage from >15 → holds to 0; re-engage at 7-15 with `dc87`=1 → re-arms (works
  to 7); **engage with `dc87`=0 (fresh key-on below 15, or after dropping below 7) → latch never arms = the
  sub-15 lockout.** The discriminator is the un-armed latch, which the (out-of-corpus) ACC-availability
  coordinator stores + enforces = the key-off-on lockout `[G]`. (`bit7` itself is read by nothing outside the
  monitor; it's internal state, not a downstream fault bit.)
- **`MON_cru_speed_engaged_latch` (d00148be) is NOT the fault — it is a monitor-*engaged* latch** (⚠ corrects
  the earlier claim here). Proof: it is unconditionally cleared the instant ACC deactivates
  (`800f006c:791` `if (a113==0 || recovery) latch=0`), and its set-term `d7f2` includes permit-bit7-*SET*
  (= permitted) — the polarity of an arm, not a "too-slow" fault. `EGAS_mon_diag_status` (d00000e1) bit 0x10
  is a per-cycle mirror of it, with **zero internal readers** — so it is engaged-state, not the lockout.
- **Non-volatility (key-off-on) = a Dem operation-cycle event** (heals per ignition cycle). The exact **DTC
  id is NOT in the decompiled corpus** (flash Dem descriptor + diagnostic-library code); a status-descriptor
  table exists at ~`0x803d75a4–0x803d7660` but does not include d00000e1. `[G]` — bench-read the DTC to pin it.
- **The ACC re-engage inhibit is Dem-gated in the upstream ACC-availability coordinator** — the OS-message
  *sender* that packs `cond[0x1c]` (the ACC-mode field): it refuses ACC (packs ≠2) while the L2 cruise Dem
  event is active. `FUN_800accac` only *relays* `cond[0x1c]`; the sender is **not in the corpus** (inter-task
  OS message, `a9` unresolved) — same `[G]` as `engage_state.md`. Inference: re-enable gated on the event
  being absent → clears on the next ignition cycle = "until key-off/on".

**openpilot edit: set `0x80389809` (15→0) AND `0x8038980e` (7→0) — both are meaningful.** 15→0 makes `dc87`
arm at any speed > 0 (so a fresh engage below 15 arms instead of faulting); 7→0 makes `dc87` never clear
(clear test `speed < 0` never fires), so the permit memory stays armed through standstill and any re-engage.
Together: `dc87` is permanently set after any motion → the latch arms at any speed → the sub-15 lockout
cannot occur regardless of engagement/re-engagement pattern. **Confirmed cycle-by-cycle.** Note: **if
openpilot keeps ACC continuously engaged from above 15, stock cal already permits control to 0** — so the
observed sub-15 lockout means openpilot is (re-)engaging ACC *below* 15 with `dc87`=0 (fresh first-engage, or
re-asserting at low speed). The 15→0 edit makes arm-speed irrelevant; separately, keeping openpilot's ACC
engagement continuous from above 15 would avoid the trigger even on stock cal. Bench-confirm after the edit.

## ACC-relevant, secondary (indirect)

- **`FUN_800f4abe` — cal #213 @0x8038a3c8 — `EGAS_L2_ACC_longsetpoint_band_213`.** Bounds the ACC
  longitudinal setpoint (`MON_acc_long_setpoint` d000d5aa) inside speed/dwell rails; its faults FEED #208
  and the aggregator → `d344`→`aa23`→ 0x8031 ACC/DCC controller. **Genuine speed edges: `0x8038a4ec`=0 and
  `0x8038a4ed`=25 km/h.** (The 16/18/16 and 12 cells I earlier listed are torque/accel rail coefficients,
  NOT speed floors.) The 25 km/h edge only enables one sub-check; watch it if you fault near 25.
- **`FUN_800f5d68` — cal #215 @0x8038a568 — `EGAS_L2_cru_lowspeed_crawl_215`.** Cruise/ACC low-speed crawl
  monitor; fault severity → cruise fault-reaction manager `800dca9c` (can force off) + aggregator. Crawl
  arming windows `0x8038a5c9`/`ca`=6, `0x8038a5cd`=5. **BUT the crawl trip runs only in the failsafe branch
  (when internal signal 0x3fc is stale — at startup / on message-loss).** Whether it fires in normal
  operation depends on whether 0x3fc's source PDU is on the Q5 bus (`[G]`, table-decode). `0x8038a5cb`=0
  disables one transition. Validate on the bench before editing.

## NOT ACC monitors (general EGAS L2 — do NOT edit for openpilot)

All read `veh_speed_MON_128` but reference **zero** ACC variables; outputs go to the EGAS torque-limp path
(`EGAS_L2_fault_aggregator` FUN_800d9936 → verdict d344 → aa23), not the ACC engage/permit path.

| fn | cal | why it's not ACC |
|---|---|---|
| `800f25e2` | #209 | engine-torque plausibility; 8/5/0 = torque-check windows; 255/254 disable gates |
| `800f5982` | #214 | torque-vs-speed; 10 = low-speed *suppression* term |
| `800df26a` | #173 | torque-corridor; **15 is a [15,105] torque-window bound — NOT the ACC floor** (coincidence) |
| `800f40bc` | #211 | channel/pedal voting; 255 = disabled over-speed ceiling |
| `800fb796` | — | torque coordinator, enabled only 25-130 km/h |
| `800e0a66` | — | accel/torque model (speed = map axis); holds the monitor twin of the ±500000 rail |
| `800f9520` | — | road-load model (v² drag); speed = physical axis |
| `800e759e` | #193 | step/DTC sequencer; 6 suppresses itself at low speed |
| `800d5828` | #148 | torque plausibility; **provably no low-speed fault** (self-disables below ~12 km/h) |

## The reaction architecture (now understood)

All L2 monitors → **`EGAS_L2_fault_aggregator` (FUN_800d9936)** → fault dwords `d000d32c/d334/d338` →
verdict `EGAS_L2_fault_verdict` (d000d344, 0-3) → `EGAS_L2_reaction_level` (d000aa23) read by the 0x8031
ACC/DCC controller = the EGAS-3 torque-limitation/limp reaction. The cruise-specific monitors (#208, #215)
additionally feed cruise fault managers (`800dca9c`). The non-volatile ACC lockout is a **Dem operation-cycle
event** from the #208 plausibility fault (§"The fault mechanism" above) — `d00000e1.b4` is only a per-cycle
*engaged-state* mirror (zero internal readers), not the DTC route.

## Bottom line for openpilot control to 0

Edit **`0x80389809` (15) + `0x8038980e` (7)** in #208 — the one genuine ACC floor and the confirmed lockout.
Test; if the fault reappears lower, the next candidates are #213's 25 km/h (`0x8038a4ed`) and the #215
crawl window (`0x8038a5c9/ca`=6, only if its failsafe branch is active on your bus). Everything else in the
earlier 28-cell list was a general EGAS torque/speed monitor and should be left stock.
