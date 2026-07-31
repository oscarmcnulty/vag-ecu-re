# EGAS Level-2 monitors — which ones gate ACC

Of the ~13 EGAS Level-2 ("Überwachung") monitors that read the monitor ego-speed `veh_speed_MON_128`
(`DAT_d0007b8a`, 1/128 km/h), **exactly one gates ACC**: cal #208. The rest are general
torque/speed/plausibility supervision that merely *use* vehicle speed (as a map axis, a plausibility window,
or a disabled ceiling) and never touch the ACC engage/permit path. Not every `cal * 0x80` in these monitors
is a speed compare — torque/accel values are scaled `×0x40`/`×0x80` too.

Load base 0x80000000; file off = addr & 0x1FFFFFFF. Speed cells are u8 km/h, compared `cal*0x80` vs
`veh_speed_MON_128`. Recompute the cal-block checksum after any edit (`core/checksum`).

## The one genuine ACC min-speed gate — cal #208  ⭐

**`FUN_800f006c`/`FUN_800f027c` (`EGAS_L2_cru_speed_monitor_A`/`_B`) over cal #208 @0x803896ec** — the EGAS-L2
cruise/ACC speed-control plausibility monitor (`C_VS_MIN_CRU_MON`). It is **gated on `cru_acc_active_flag`
(d000a113)**: its logic runs only when cruise/ACC is the active longitudinal controller — which is what makes
it ACC-specific, unlike every torque monitor.

**Behaviour: a self-recovering, speed-gated permit — not a fault.** Below the floor the ECU **withholds the
ACC command** (it is not applied); the moment speed rises back above **15 km/h** the permit re-arms and ACC
works again. A MED17 openpilot user observes exactly this — ACC re-enables at ~15 km/h, which is the #208 SET
edge `0x80389809`=15. (The hard key-off-on lockout behaviour belongs to the Simos, which has a hardcoded
barrier at `8013ef46:258`; the MED17 has no such barrier and no non-volatile store in this path.)

### The permit floor — a persistent memory with a latch-gated feedback

`MON_cru_permit_floor_flag` (`dc87`) is a **persistent hysteretic memory** — SET when speed > 15, CLEARED when
speed < 7 — written only in the floor block (`800f006c:742` / `800f027c:656`) and reset nowhere (it persists
across latch cycles and ACC on/off; zeroed only at key-on). The floor block runs only while
`MON_cru_speed_engaged_latch` (d00148be) == 0 — the *arming phase*. When ACC is active and `dc87`=1 →
`MON_cru_permit_flags` (d000d7d1) bit7 = 1 → the latch arms, and holds until ACC-off or a `d000d240` 0x8f→8
recovery. So the two cells are live for different engagements:

| cell | km/h | role |
|---|---|---|
| **`0x80389809`** (+0x11d) | **15** | ARM-from-scratch edge. With `dc87`=0 (key-on, or after it cleared), speed must exceed 15 to set `dc87`=1 and arm the latch. |
| **`0x8038980e`** (+0x122) | **7** | RE-ARM floor. Once `dc87`=1 it stays 1 down to 7, so ACC can drop and re-engage anywhere down to 7; below 7 (un-latched) `dc87` clears → speed must exceed 15 again to re-arm. |

Secondary arming windows in the same object (leave stock): 17/15 band (`0x8038980a`=17, `0x80389808`=2-width),
5 band (`0x8038980f`), [10,65] window (`0x80389811`/`0x80389810`), 17/14 window (`0x80389812`/`0x80389813`).

### Why there is no persistent lockout

Every element in the #208 → reaction chain is volatile RAM recomputed each cycle: `dc87` re-arms by speed,
the engaged latch clears the instant ACC deactivates (`800f006c:791`), and `EGAS_L2_fault_verdict` is
overwritten at `800d9936:260`. `d00148be` is a monitor-*engaged* latch (its set-term `d7f2` requires bit7
*SET* = permitted — the polarity of an arm, not a "too-slow" fault), and `EGAS_mon_diag_status` (d00000e1)
bit 0x10 is a per-cycle mirror of it with zero internal readers. `#208` writes none of the torque-limp
aggregator's inputs — its outputs are pure cruise-permit state (`d7d1`/`d7d2`/`dc8b`…). The corpus contains
no `Dem/eeprom/nvram/WriteBlock` symbols, so nothing here stores a key-cycle fault.

### openpilot edit

**Set `0x80389809` (15→0) and `0x8038980e` (7→0).** 15→0 makes `dc87` arm at any speed > 0 (so a fresh
sub-15 engage arms instead of being withheld); 7→0 makes `dc87` never clear (the `speed < 0` test never
fires), keeping the permit armed through standstill and any re-engage. Together `dc87` is permanently set
after any motion, so the permit is granted at any speed regardless of engagement pattern. (If openpilot keeps
ACC continuously engaged from above 15, stock cal already permits control to 0 — the sub-15 withhold only
occurs when ACC (re-)engages below 15 with `dc87`=0.)

## ACC-relevant, secondary (indirect)

- **`FUN_800f4abe` — cal #213 @0x8038a3c8 (`EGAS_L2_ACC_longsetpoint_band_213`).** Bounds the ACC longitudinal
  setpoint (`MON_acc_long_setpoint` d000d5aa) inside speed/dwell rails; its sub-faults feed #208 and the
  aggregator → `d344`→`aa23`→ the 0x8031 ACC/DCC controller. Genuine speed edges: `0x8038a4ec`=0 and
  `0x8038a4ed`=25 km/h (the 16/18/16 and 12 cells are torque/accel rail coefficients, not speed floors). The
  25 km/h edge only enables one sub-check.
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
effect is the self-recovering cruise permit above, not a limp.

## Bottom line for openpilot control to 0

Edit **`0x80389809` (15→0) + `0x8038980e` (7→0)** in #208 — the one genuine ACC min-speed permit gate. Below
it the ECU withholds the ACC command (no fault, self-recovers above 15); the edit arms the permit at any
speed and holds it through standstill/re-engage. If a new symptom appears at a lower speed, the next
candidates are #213's 25 km/h (`0x8038a4ed`) and the #215 crawl window (`0x8038a5c9/ca`=6, only if its
failsafe branch is active). Everything else is a general EGAS torque/speed monitor — leave stock.
