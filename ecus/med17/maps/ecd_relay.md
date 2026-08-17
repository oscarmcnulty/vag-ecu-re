# The 15 km/h ACC floor: the ECU relays it, it does not impose it

## The finding

The MED17 has **no 15 km/h ACC threshold on the functional path**. It relays a declaration made by the
ESP/ABS:

    ESP_05 (CAN 0x106) frame bit 33 = ECD_nicht_verfuegbar

`ECD` = **Externally Controlled Deceleration** — the ESP function that executes braking commanded by
another ECU rather than by the driver. Below ~15 km/h the ESP declares it unavailable, and the engine
withdraws ACC authority in response. Siblings in the same frame corroborate the reading: `ECD_Fehler`
and `ECD_Bremslicht` (the ESP lighting the brake lamps during externally-commanded braking).

This matters operationally: **no MED17 calibration edit can lift the floor by itself.** The decision is
made in another module and the engine is obeying it.

## The propagation path

Every arrow below is proved at instruction level.

    ESP_05 (0x106) frame bit 33
      -> boolean descriptor 0x80034784   (target 0xd000ab42, srcBit 33, destBit 5)
      -> 0xd000ab42 bit 5                COM staging
      -> 0xd000a60a bit 5                whole-byte copy ab42 -> a60a, FUN_80317ea8 @0x80318152/58
      -> 0xd0000179 bit 5                FUN_800a5a3a @0x800a5b12-0x800a5b1a
                                         (substituted to 1 when FUN_800a06f2 != 0; force-set @0x800a5756)
      -> 0xd000017a bit 4                three ABS-mode mirror engines:
                                         FUN_80313d20 @0x80313e52/58
                                         FUN_803151fc @0x80315316/1c
                                         FUN_80316310 @0x8031642a/30
      -> condvec bit 0                   TSK02_producer FUN_80140922:
                                         (d000017a.b4 && d000a14d), selected by cal 0x803dba7d = 0x01
      -> 0xd000a346 bit 5                0x80140d10 insert d15,d9,d8,#5,#1; sole writer 0x80140d3c
      -> 0xd0004930 bit 5                entry snapshot 0x80144846
      -> 0xd00049c9 bit 2                packer FUN_80143a68 @0x80144d4a slot 2; AND cal 0x803b50bf = 0xFF
      -> 0xd0004938 bit 7                packer @0x80144fb4 slot 7; 2-cycle stretched by latches
                                         d00049bc/d00049c4 under cal mask 0x803dc15c = 0x000040c2
      -> 0xd0005e38 -> 0xd0005e34 bit 7  0x801453ee / 0x801454b6
      -> TSK_01 (0x10A) frame bit 23     descriptor 0x80039460, start_bit 16, bit_len 24

## The common flag: `0xd00049c9` bit 2

`0xd00049c9` (`ACC_abort_request`) is the reason all three TSK signals move together. It is **both
transmitted and consumed** — the same bit that becomes TSK_01 frame bit 23 is also the engine's internal
ACC abort request. The chain above forks there:

    d00049c9 bit 2   (packer 0x80144d4a slot 2; mask cal 0x803b50bf = 0xFF, so bit 2 passes)
      |
      +-- TX leg       0x80144f9a/fa4 extract bit 2 -> packer 0x80144fb4 slot 7 -> d0004938 bit 7
      |                 (2-cycle stretch via latches d00049c4/d00049bc, cal 0x803dc15c = 0x40c2)
      |                 -> d0005e38 -> d0005e34 -> TSK_01 0x10A frame bit 23
      |
      +-- CONTROL leg  FUN_80143b26 returns (d00049c9 != 0), called from 5 sites in
                       ACC_engage_state_machine -> FUN_80143954 / FUN_801439fc
                       -> d0004936 = 0 AND d0004941 = 0 in one transition
                          -> a350 -> TSK_04 0x10E 62|2  TSK_Status_GRA_ACC_02
                          -> a350 -> TSK_ax_Getriebe gate -> cal 0x803b508a = 0 substitution
                          -> a362 -> TSK_02 0x10C 56|8   TSK_Verzoeg_Anf hard-zeroed
                          -> a350/a362 -> TSK_02 frame bits 54 and 12, also railed

That is why the on-car data shows TSK_04 bit 62 dropping at the *same* lag as TSK_01 bit 23 (15 clean
cases matching to 0.1 ms) and `TSK_Verzoeg_Anf` at exactly 0 throughout: one internal flag, one
transition, three observable consequences.

**`FUN_801455ae` is a seven-line copier on this calibration.** At `0x801455b6/bc` it tests
`cal_obj(a9+0x3ec)[0x21]` and `[0x24]` — objectial `0x803b5230`, both **0** in this image — so the short
branch is taken unconditionally and `0x801455e4/ee` does `d000ab01 = d000a350`. TSK_04's status is a
direct copy of `d0004936`. The entire long body (a368-derived status, DSM fault word, the case 0-3
switch, the `d0000121` bit-5 suppressor) is **dead code here**, which is worth knowing before spending
time reading it.

Signal identities, confirmed from the descriptors: `0xd0008d5a` = 0x10C **56|8** `TSK_Verzoeg_Anf`
(descriptor `0x800392f8`); `0xd0005de0` = 0x10C **40|12** `TSK_Radbremsmom` (descriptor `0x80039320`).
The same RAM is *also* bound to **CAN 0x111** (`d0008d5a` 56|8, `d000ab01` 16|2, plus the same three
booleans) — whether 0x111 is actually transmitted on this vehicle has not been checked against a log.

`0xd000ab42` is the ESP brake/ECD **status byte** — eight ESP_05 bits are packed into it:

| ESP_05 bit | signal | -> d000ab42 bit |
|---|---|---|
| 13 | ESP_QBit_Fahrer_bremst | 7 |
| 26 | ESP_Fahrer_bremst | 3 |
| 27 | ESP_Verz_TSK_aktiv | 0 |
| 29 | ESP_Konsistenz_TSK | 4 |
| 32 | ECD_Fehler | 6 |
| **33** | **ECD_nicht_verfuegbar** | **5** |
| 34 | ESP_Status_Bremsentemp | 1 |
| 61 | ESP_Status_Bremsdruck | 2 |

## The on-car evidence

8.11 h across two Q5 8R cars, 1,460,262 ESP_05 frames, 260 ECD transitions.

- **The engine never leads.** 0 of 257 matched lags are negative. Mean lag 56.6–85.7 ms depending on car
  and direction, with a consistent +16 to +20 ms extra delay on *release* (an asymmetric debounce).
- **Fixed-lag beats an engine-side threshold by 3.3x to 31x** (RMS of predicted vs actual edge time,
  threshold fitted per car and direction to give the competing model its best case).
- **Decisive discriminator:** the engine's edge *speed* slides with acceleration exactly as a delay
  predicts, while the ESP's does not. Over a 200x range of |dv/dt|, `corr(v_engine_edge, |dv/dt|)` =
  -0.88 (lock) / +0.70 (permit) versus -0.38 / +0.15 for the ESP; the measured slope is -0.079/+0.092
  km/h per km/h/s against -0.070/+0.070 predicted by a ~70 ms delay and **0.000** predicted by a fixed
  engine threshold.
- **Steady-state agreement is bit-exact:** TSK_01 bit 23 differs from ESP_05 bit 33 in 52 of 1,452,791
  frames (0.0036%), all inside propagation windows.
- **ESP chatter is swallowed:** three events where the ESP glitched for 1-2 frames produced exactly one
  engine transition, 60-140 ms after the ESP's final stable edge.
- `TSK_02.TSK_Verzoeg_Anf` is **exactly 0** in 178,913 of 178,994 frames where ECD is unavailable; all 81
  exceptions lie within 200 ms of an edge. The engine never even *attempts* a request below the floor —
  it knows in advance, which is what a relayed permit looks like and a reactive timeout does not.
- The floor value is a **per-vehicle ESP constant**, not a route property: 14.90 km/h on one car, 15.18
  on the other, sd <= 0.13 km/h across routes within a car.

The ESP's own threshold has **no hysteresis** — it chattered three times in 40 ms at a dead-constant
15.18 km/h, the signature of a bare compare.

## Why this took so long to see

Two independent errors pointed the same way, and each produced a confident false negative.

1. **The COM message table was decoded with the wrong base and an off-by-one boolean pointer.** The base
   was recorded as `0x800312d0` (a 48-record sub-window of a 113-record table at `0x80030c38`), and the
   boolean pointer was read at `+0x2c` from that base = `true_record + 0x34`, i.e. the *next* message's
   pointer. Every boolean binding was attributed to the wrong message, which made ESP_05 bit 33 look
   like it belonged to CAN 0x101. An on-car check then "confirmed" 0x101's bit was inert — a correct
   measurement of the wrong signal.

2. **`FindEffectiveAddr` could not see TriCore ABS-mode accesses.** ABS encodes
   `EA = {off18[17:14], 14'b0, off18[13:0]}`, so it reaches only the low 16 KB of a segment — exactly
   `0xd0000000..0xd0003fff`, where this ECU keeps its bit-flag block. `0xd000017a` bit 4 has three
   `st.t` writers that were invisible, so a live relayed bit was mistaken for static variant coding, and
   the whole chain was written off as carrying a constant.

A third trap compounded it: once an address is named in `symbols_merged.csv`, grepping the decompiles
for `DAT_<addr>` returns nothing, because the decompiler emits the assigned symbol name instead. A
cross-check that looked independent was not.

## What was ruled out, and stays ruled out

These sweeps were exhaustive and their negatives remain valid — they are the reason the answer had to be
external:

- **No 15 km/h scalar** in any calibration on the functional path: 5,877 regex-resolved cal reads, plus
  30,199 reads resolved properly through the `a9` object table (including 904 runtime-indexed accesses
  over 518 arrays that the regex could not see).
- **No 15 km/h breakpoint** in any reachable characteristic curve or map: 29 1-D Kennlinien and 10 2-D
  Kennfelder decoded axis by axis. The three tables that do contain 1500 are inert (all-zero or
  constant Z).
- **No literal `1500` compare anywhere in the image.**
- The "symmetric fifteen" (`-1500/+1500` at cal `0x803c2d34 +0x356/+0x358` and `+0x366/+0x368`) is a
  **saturation clamp** passed as (lower, upper) to the integrators `FUN_8007ca62`/`FUN_8007c9f2` — not a
  gate.

## The one internal 15: EGAS-L2 cal #208 (a shadow monitor, not the functional gate)

Distinct from the ECD relay and **not** superseded by it. `FUN_800f006c` / `FUN_800f027c`
(`EGAS_L2_cru_speed_monitor_A`/`_B`) compare the monitor speed `veh_speed_MON_128` (`0xd0007b8a`,
1/128 km/h) against cal #208 `@0x803896ec`:

    +0x11d = 0x80389809 = 15      +0x122 = 0x8038980e = 7

Its output is a **fault contributor**, not a permit:

    -> 0xd000d7f9  (800f006c:728)  -> FUN_800d9936 EGAS_L2_fault_aggregator (:71)
    -> 0xd000d344  fault verdict   -> 0xd000aa23 reaction level

Because it is a Level-2 monitor operating on the independent monitor-path speed, it can enforce its own
15/7 boundary regardless of what the ESP declares. **Any attempt to operate ACC below 15 km/h will
likely need #208 edited as well as the ESP-side constraint addressed.** Editing it alone will not lift
the floor — the ESP will still refuse ECD — but leaving it stock may reintroduce the limit from the
monitor side. Validate by checking `TSK_Verzoeg_Anf` actually goes non-zero below 15 km/h, not merely
that TSK_04 grants. Cal edits need a cal-block checksum recompute (`core/checksum`).

## A real but inert low-speed engage lock

`ESP_05` frame bit **36** (`ESP_HDC_Standby`, hill-descent) follows a parallel path:

    -> boolean descriptor 0x800347ac -> 0xd000ab6a -> 0xd000a6c7 -> 0xd000015f b7
    -> 0xd00000e0 b7 -> 0xd0004985 -> ON-delay debounce (cal 0x803b50e6 = 6)
    -> 0xd00049ca bit 7 -> FUN_80143b34 -> ACC_engage_state_machine (4 call sites)

`FUN_80143b34` is three instructions returning `(0xd00049ca != 0)`, and while set it forces states 1 and
5 to state 2 and blocks both re-engage chains; the default case then calls `FUN_801439fc`, zeroing
`0xd0004936` and `0xd0004941` and railing both TSK channels in one transition.

This is a genuine low-speed engage lock, but it is wired to hill-descent standby, which is constant 0 on
these vehicles — so it never fires here. Do not conflate it with the ECD path. Its mask
(`0x803b50c1 = 0xFE`) and ON-delay (`0x803b50e6 = 6`) are calibratable if that ever changes.

## Where the lever actually is

Not in this ECU. The ESP/ABS enforces ECD availability autonomously. The alternatives are the ESP
itself, or an actuator path that does not require ECD — note that `ESP_Verzoeg_EPB_verf` (ESP_05 bit 60)
stays **1 on both sides of the floor**, i.e. EPB deceleration is still advertised as available when ECD
is not.
