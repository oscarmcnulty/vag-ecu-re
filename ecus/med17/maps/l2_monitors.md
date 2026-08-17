# EGAS Level-2 monitors — which ones touch ACC

The EGAS "Überwachung" (Level-2) cluster is ~20 functions at `0x800d_xxxx … 0x8010_xxxx` that
supervise the functional path from an independent side: they recompute vehicle speed
(`veh_speed_MON_128`, `0xd0007b8a`, 1/128 km/h) instead of reading the functional shadow, and they
reach their calibration through a disjoint set of cal objects in `0x80384xxx … 0x8038axxx` rather
than the functional ACC objects at `0x803b_xxxx`. Same twin-architecture idea as Simos8.5.

Of that cluster, **one member is ACC-specific: cal #208** (`FUN_800f006c` / `FUN_800f027c`). The rest
are torque, plausibility and road-load supervision that merely *use* speed — as a map axis, a
plausibility window or a disabled ceiling.

Load base `0x80000000`; file offset = `addr & 0x1FFFFFFF`. Speed cells are u8 km/h compared as
`cal * 0x80` against `veh_speed_MON_128`. **Not every `* 0x80` here is a speed compare** — torque and
accel values are scaled `×0x40`/`×0x80` too, so each site has to be resolved individually.

Confidence: **[C]** read the code/bytes · **[M]** measured on-car · **[I]** inferred · **[G]** gap.

> **This is not where the ~15 km/h ACC floor comes from.** That floor is `ESP_05` frame bit 33
> `ECD_nicht_verfuegbar`, declared by the ESP/ABS and relayed by the engine — see `ecd_relay.md`.
> #208 is a **second, independent** constraint that happens to sit at the same speed. It is real, it
> is calibratable, and because it runs on the monitor-path speed it can enforce its own 15/7 boundary
> no matter what the ESP says. Treat it as a necessary companion edit, never as the cause.

## Cal #208 — `EGAS_L2_cru_speed_monitor_A`/`_B` [C]

`FUN_800f006c` / `FUN_800f027c` over **cal object #208 `@0x803896ec`** (reached as `*(a9+0x340)`,
folded in the decompiles as `PTR_WORD_ARRAY_801037a4`). It is the cruise/ACC speed-control
plausibility monitor — the MED17 analog of Simos8.5's `C_VS_MIN_CRU_MON` — and it is **gated on
`cru_acc_active_flag` (`d000a113`)**, i.e. it only runs when cruise/ACC is the active longitudinal
controller. That gate is what makes it ACC-specific, unlike every torque monitor.

### The permit floor

```c
// FUN_800f006c :737-745, inside the arming block (runs only while the engaged latch is 0)
if (cal[0x11d] * 0x80 < veh_speed_MON_128)        MON_cru_permit_floor_flag = 1;   // 15 km/h
else if (veh_speed_MON_128 < cal[0x122] * 0x80)   MON_cru_permit_floor_flag = 0;   //  7 km/h
...
MON_cru_permit_flags = (MON_cru_permit_flags & 0x7f) | (permitted << 7);
```

| cell | flash | value | role |
|---|---|---|---|
| `#208 +0x11d` | **`0x80389809`** | **15 km/h** | SET edge — with `dc87` = 0, speed must exceed 15 to set it |
| `#208 +0x122` | **`0x8038980e`** | **7 km/h** | CLEAR edge — once `dc87` = 1 it stays 1 down to 7 |

`MON_cru_permit_floor_flag` (`d000dc87`) is a **persistent hysteretic memory**: written only in this
block and reset nowhere, so it survives latch cycles and ACC on/off and is zeroed only at key-on. The
floor block itself runs only while `MON_cru_speed_engaged_latch` (`d00148be`) is 0 — the arming
phase. Bit 7 of `MON_cru_permit_flags` is therefore an **arming pulse**, not a sustained permit: it
is re-initialised false each cycle and only assigned inside the un-latched branch, so once the latch
arms it reads back 0.

Secondary bands in the same object (leave stock): the 17/15 band (`0x8038980a` = 17 with width
`0x80389808` = 2, driving the separate flag `d000dc78`/`d000d7de`), the 5 band (`0x8038980f`), the
`[10,65]` window (`0x80389811`/`0x80389810`) and the 17/14 window (`0x80389812`/`0x80389813`).

### How #208 reaches the ACC command — the output path [C]

The permit state is **not** consumed as a permit. It leaves #208 as a *fault contributor* into the
EGAS-L2 aggregator:

```
veh_speed_MON_128 vs cal 0x11d (=15) / 0x122 (=7)
   -> MON_cru_permit_floor_flag  d000dc87           800f006c:~742
   -> MON_cru_permit_flags bit7  d000d7d1           800f006c:LAB_800f10b8
   -> MON_cru_floor_fault        d000d7f9           800f006c:728
        set when: latch engaged && cal[0x148] bit0 && d000d240 == 8
                  && retry counter < cal[0xec] && permit bit7 CLEAR && d7f6 == 0
   -> FUN_800d9936  EGAS_L2_fault_aggregator        800d9936:71  (-> fault contributor uVar18)
   -> EGAS_L2_fault_verdict      d000d344           800d9936:260
   -> EGAS_L2_reaction_level     d000aa23           written by FUN_802c51c2
   -> read by FUN_80312f70 / FUN_803147dc / FUN_80315a54  (the 0x8031 controller/marshaller block)
```

`FUN_800f006c` also feeds the aggregator through `d7e1` (:97), `d7e8` (:182), `d7e7` (:183 →
`d000d342`) and `d7ef` (:201). Because the consequence is a reaction *level* rather than a latched
DTC, a #208 trip is silent — no DTC, no limp.

### The `dc8b` suppression term — resolved, and it is the gear selector [C]

`dc8b` is what holds `d7f9` low during normal engaged driving. With the config word
`#208 +0x148 = 0x1bf3` (`@0x80389834`) collapsing two terms to unconditionally true:

```
dc8b = cru_acc_active_flag(d000a113) && d000d240 <= 8 && d000a0a9 && (state == 6 || state == 8)
```

The state term is the live one, and the chain resolves entirely to gear logic:

```
state    = FUN_8010295e(cal+0x49, cal+0x36, d0009f76)
           cal+0x49 LUT @0x80389735 is an IDENTITY map over 0..17  ->  state == d0009f76
d0009f76 = shadow copy of d000a89a          (802c4942:155 / 802c4ee8:28, the L1->L2 shadow block)
d000a89a = tbl[d000a6c3]                    (FUN_80087a70, sole writer)
    tbl @0x800453b4 = identity[0..14]                        when (d0008c80 & 0x1610) == 0
    tbl @0x80045395 = [0,0,0,0,0,8,7,6,5,12,17,0,0,14,14]    otherwise (5↔8, 6↔7)
```

**`d000a6c3` is `GE_Waehlhebel`** — Getriebe_03 (`0x102`) frame bits 44\|4, bound by COM signal
descriptor `0x80039c08`. That is now read directly out of the message table, not matched by
geometry (`can_signal_map.md`). On-car the field steps `5 → 6 → 7 → 8` (P→R→N→D) as the driver moves
the lever and sits constant at **8 (D)** while driving, so `{6, 8}` means **selector in R or D**, and
`d7ed`/`d7f1` are debounced "in R" / "in D". This is why `FUN_80087a70` and the `0x80143b8a` state
machine contain no speed reference at all. **[C]/[M]**

### Why there is no persistent lockout [C]

Every element of the #208 → reaction chain is volatile RAM recomputed each cycle: `dc87` re-arms by
speed, the engaged latch clears the instant ACC deactivates (`800f006c:791`), and
`EGAS_L2_fault_verdict` is overwritten at `800d9936:260`. `d00148be` is a monitor-*engaged* latch (its
set term `d7f2` requires bit 7 SET = permitted — the polarity of an arm, not of a "too slow" fault),
and `EGAS_mon_diag_status` (`d00000e1`) bit `0x10` is a per-cycle mirror of it with zero internal
readers. The corpus contains no `Dem`/`eeprom`/`nvram`/`WriteBlock` symbols on this path, so nothing
stores a key-cycle fault. Corroborated on-car: the low-speed withhold is fully self-recovering, with
no DTC and no torque limp. **[C]/[M]**

## ACC-adjacent, secondary [C]

- **`FUN_800f4abe` — cal #213 `@0x8038a3c8`** (`EGAS_L2_ACC_longsetpoint_band_213`). Bounds the ACC
  longitudinal setpoint (`MON_acc_long_setpoint`, `d000d5aa`) inside speed/dwell rails; its sub-faults
  feed #208 and the aggregator. Genuine speed edges: `0x8038a4ec` = 0 and `0x8038a4ed` = 25 km/h. The
  25 km/h edge enables one sub-check only. The nearby `0x8038a4d7/d8/d9` (16/18/16) and `0x8038a4ee`
  (12) are torque-rail coefficients, not speeds.
- **`FUN_800f5d68` — cal #215 `@0x8038a568`** (`EGAS_L2_cru_lowspeed_crawl_215`). Cruise/ACC low-speed
  crawl monitor; severity goes to the cruise fault-reaction manager `FUN_800dca9c` and the aggregator.
  Crawl arming windows `0x8038a5c9`/`ca` = 6, `0x8038a5cd` = 5. Its crawl trip runs **only in the
  failsafe branch** (internal signal `0x3fc` stale — at startup or on message loss); whether that
  branch is ever entered on the Q5 bus is **[G]** (a table-decode question). `0x8038a5cb` = 0 disables
  one transition. Validate on the bench before editing.

## Not ACC monitors — leave stock

All read `veh_speed_MON_128` but reference zero ACC variables; their outputs go to the EGAS
torque-limp path, not to any ACC permit.

| fn | cal | role |
|---|---|---|
| `800f25e2` | #209 | engine-torque plausibility; 8/5/0 = torque-check windows; 255/254 disable gates |
| `800f5982` | #214 | torque-vs-speed; 10 = low-speed suppression term |
| `800df26a` | #173 | torque corridor; its 15 is a `[15,105]` **torque**-window bound |
| `800f40bc` | #211 | channel/pedal voting; 255 = disabled over-speed ceiling |
| `800fb796` | — | torque coordinator, enabled only 25–130 km/h |
| `800e0a66` | — | accel/torque model (speed = map axis); holds the monitor twin of the ±500000 rail |
| `800f9520` | — | road-load model (v² drag); speed = physical axis |
| `800e759e` | #193 | step/DTC sequencer; 6 suppresses itself at low speed |
| `800d5828` | #148 | torque plausibility; provably self-disables below ~12 km/h |

## Cell inventory

| flash | cal obj | value | site → latch | note |
|---|---|---|---|---|
| **`0x80389809`** | #208 `0x803896ec` +0x11d | **15 km/h** | `800f006c:740` → `d000dc87` → `d000d7d1` b7 | permit SET / arm edge |
| **`0x8038980e`** | #208 +0x122 | **7 km/h** | `800f006c:745` → `d000dc87` | permit CLEAR edge |
| `0x8038980a` | #208 +0x11e | 17 km/h | `800f006c:130` → `d000dc78` | separate 17-band set edge |
| `0x80389808` | #208 +0x11c | 2 km/h | `800f006c:135` | width of the 17-band |
| `0x80389812` / `0x80389813` | #208 +0x126/+0x127 | 17 / 14 km/h | `800f006c` → `d000dc88` | window |
| `0x80389810` / `0x80389811` | #208 +0x124/+0x125 | 65 / 10 km/h | `800f006c:1499` | monitor band |
| `0x80389834` | #208 +0x148 | `0x1bf3` | `800f006c:714` | config word gating the `dc8b` terms |
| `0x8038a4ed` | #213 `0x8038a3c8` +0x127 | 25 km/h | `800f4abe:500` | enables one sub-check |
| `0x8038a5c9` / `0x8038a5ca` | #215 `0x8038a568` +0x61/+0x62 | 6 km/h | `800f5d68:56/108` | failsafe-branch crawl arming |
| `0x80384761` / `0x80384760` | #148 `0x8038436a` +0x3f7/+0x3f6 | 5 / 7 | `800d5828:191` → `d000d867` | general torque monitor |
| (literal) | — | 3.01 km/h (`< 0x181`) | `800dc570:30` | hardcoded monitor creep |

## Bottom line for openpilot

1. **The floor itself is not here.** Removing it means addressing `ESP_05` bit 33 on the ESP side, or
   using an actuator path that does not need ECD. `ecd_relay.md` §"Where the lever actually is".
2. **Edit #208 anyway.** Set `0x80389809` (15 → 0) and `0x8038980e` (7 → 0) and recompute the
   cal-block checksum (`core/checksum`). Leaving it stock re-imposes a 15/7 boundary from the monitor
   side even if the ESP constraint is solved. Editing it alone will change nothing, because the ESP
   will still refuse ECD.
3. **Verify what actually moved.** Read the two bytes back over UDS after flashing — a stale block
   checksum is the most likely reason an edit appears to do nothing — and then check
   `TSK_Verzoeg_Anf` (`0xd0008d5a`, TSK_02 56\|8) actually goes non-zero below 15 km/h, not merely
   that `TSK_04` grants.
4. **If a boundary reappears at a different speed**, the next candidates are #213's 25 km/h edge
   (`0x8038a4ed`) and the #215 crawl window (`0x8038a5c9`/`ca`, only if its failsafe branch is
   active).

Everything else in this file is general EGAS torque/speed supervision — leave stock.
