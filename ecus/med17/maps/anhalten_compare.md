# `ACC_Anhalten` → `TSK_Anhalten`: Simos 8.5 vs MED17.1.1

Both ECUs sit on the same MLB powertrain CAN, receive **ACC_01 (`0x109`)** and transmit
**TSK_02 (`0x10C`)** with identical wire layout (`ACC_Anhalten` = ACC_01 57\|1;
`TSK_Anhalten` = TSK_02 12\|1). This file compares how each one gets the hold bit from one to the
other, and what that means for driving standstill from openpilot.

Tags: **[C]** read code/bytes · **[M]** measured on-car · **[I]** inferred · **[G]** gap.

## The answer: both are direct, gated relays of the same received bit

### Simos 8.5 [C, from `simos85/maps/acc_flow.md` §7]

```
ACC_01 (0x109) byte7·bit1  ->  decoder 801383e8 (E2E seed 0x08)
  ->  d000a7ae
  ->  8013ef46:937-943   a58d = a7ae while the gate holds
  ->  d000a58d
  ->  packer 80137a00    ->  TSK_02 byte2·bit4
```

Forward gate: `ad0f != 0` (compute-enable) ∧ `a757 != 0` (Basic-ACC coded) ∧ `a5a8 == 0`
(cal-fixed 0 on the Q5) ∧ **`b28e ∈ {1,5}`** (cruise actively regulating).

### MED17.1.1 [C]

```
ACC_01 (0x109) frame bit 57  ACC_Anhalten
  ->  boolean descriptor 0x80034a04            ->  0xd000a59b bit 0
  ->  FUN_800b0e94 :65-72 / :102-109           ->  0xd0000113 bit 4
  ->  FUN_801405d4 :167-174                    ->  0xd000a33d
          d000a33d = (a362 in {1,5} && d000a454 == 2) ? (d0000113 >> 4 & 1) : 0
  ->  boolean descriptor 0x80034b58            ->  TSK_02 (0x10C) frame bit 12  TSK_Anhalten
```

Forward gate: `d000a454 == 2` (ACC mode) ∧ **`a362 ∈ {1,5}`** (ACC actively regulating) — the direct
analog of Simos's `b28e ∈ {1,5}`.

The ingress binding is read out of the COM message table (`can_signal_map.md`): ACC_01's boolean
descriptor at frame bit 57 targets `0xd000a59b` bit 0, and TSK_02's boolean descriptor at frame bit 12
sources `0xd000a33d` bit 0. `FUN_800b0e94` is dispatched per ACC sub-frame (`0x55`, `0x29`, `0x2a`,
`0x56`) and every branch that touches the hold bit copies `a59b` bit 0 into `d0000113` bit 4.

**ACC_05 (`0x10d`) frame bit 62 writes the same `0xd000a59b` bit 0**, so a platform that sends the ACC
command on `0x10d` uses the identical downstream path.

> `d0000113` sits in the `0xd0000000..0xd0003fff` bit-flag block, which TriCore reaches with ABS-mode
> `st.t`/`ld.t`. Address-resolution tools that do not model ABS addressing see none of these writes.

### Net comparison

| | Simos 8.5 | MED17.1.1 |
|---|---|---|
| source bit | ACC_01 57\|1 | ACC_01 57\|1 (also ACC_05 62\|1) |
| intermediate | `d000a7ae` → `d000a58d` | `d000a59b`.0 → `d0000113`.4 → `d000a33d` |
| gate | compute-enable, ACC-coded, `a5a8==0`, `b28e ∈ {1,5}` | `a454 == 2`, `a362 ∈ {1,5}` |
| output | TSK_02 byte2·bit4 (= 12\|1) | TSK_02 12\|1 |

Same signal, same destination, structurally the same gate. **openpilot, as the ACC command source,
owns `TSK_Anhalten` on both ECUs**: transmit ACC_01 with bit 57 set and a valid MLB E2E (XOR checksum
with seed `0x08`, rolling counter in byte 1's low nibble), stay ACC-coded, and keep the controller
actively regulating.

## Low-speed barriers per ECU

| barrier | Simos 8.5 | MED17.1.1 |
|---|---|---|
| **ECD availability** | `ESP_05` bit 33 `ECD_nicht_verfuegbar`, declared by the ESP/ABS on the shared bus | same — **proved on MED17**, `ecd_relay.md`. Not an engine calibration in either ECU. **[C]** on MED17, **[I]** on Simos |
| EGAS-L2 min-speed monitor | `C_VS_MIN_CRU_MON` = 15 km/h @ `0x800794ef/f2` | cal #208 `0x80389809` = 15 / `0x8038980e` = 7 (`l2_monitors.md`) |
| low-speed creep/permission state | CRUC state machine (`8013ef46`/`8013e8aa`) with several sub-15 permission flags (a 2.34 km/h cal, a `1000` ≈ 7.81 km/h launch latch `d000118a`, a `d0007e84` hysteresis) | none — the decel/hold path is cal-map driven with no hardcoded speed literal (`min_speed_l2.md` §3) |
| creep hysteresis cals | ~7.8 km/h @ `0x800439f8/fa` | none identified as a gate |
| regulating gate | `b28e ∈ {1,5}` | `a362 ∈ {1,5}` |
| hold enable | runtime `a5a8` (cal-fixed 0) / `a757` / `ad0f` | `a454 == 2` |

## Would both send the same low-speed signals with the L2 monitors zeroed?

**Not necessarily, and for a reason that has nothing to do with the hold bit.**

1. **Zeroing the L2 monitor does not remove the floor on either car.** The dominant constraint is the
   ESP's ECD declaration, which is external to both engine ECUs. On MED17 this is proved end to end
   (`ecd_relay.md`); on Simos the same `ESP_05` bit is on the same bus from the same ESP, so the same
   constraint is expected to apply. **[C]/[I]**
2. **The low-speed *decel* behaviour still diverges by construction.** Simos gates hold and decel
   behind the CRUC state machine (`STATE_CRU_CTL ∈ {1,5}`) fed by several sub-15 permission/creep
   flags; MED17's hold/decel path is cal-map driven to standstill with no equivalent state machine.
   Whether Simos brakes to true 0 is decided by the CRUC state machine as a whole, which is untraced —
   **do not assume a one-literal fix.** **[C mechanism / G on Simos engaged-to-0]**
3. **The hold bit itself is no longer a source of divergence.** Same wire bit, same destination bit,
   analogous gate. Confirm bit-exactness on a bus capture if it matters, but there is no structural
   reason for the two to differ here.

## To make them match

- **MED17:** the ESP-side ECD constraint is the real barrier (`ecd_relay.md`). Zero the #208 permit
  pair (`0x80389809` = 15 → 0 and `0x8038980e` = 7 → 0) so the monitor does not reimpose its own 15/7
  boundary, recompute the cal-block checksum (`core/checksum`), and verify `TSK_Verzoeg_Anf`
  (`0xd0008d5a`) actually goes non-zero below 15 km/h rather than only checking that TSK_04 grants.
- **Simos 8.5:** zero `C_VS_MIN_CRU_MON`; the sub-15 CRUC creep/permission flags feed a state machine
  rather than acting as one removable floor, so matching engaged-to-0 behaviour needs the CRUC machine
  understood (`8013e8aa`/`8013e47c`), not just the `1000` literal patched.
- **Both:** neither edit addresses the ESP. Below ~15 km/h the ESP declares ECD unavailable, and the
  engine — either engine — obeys.

## Key addresses

- **Simos:** `801383e8` (ACC_01 decode), `8013ef46` (relay + `STATE_CRU_CTL ∈ {1,5}` gate, `1000`
  launch-latch literal), `80137a00` (TSK_02 packer), `C_VS_MIN_CRU_MON` `0x800794ef/f2`, creep
  `0x800439f8/fa`.
- **MED17:** boolean descriptors `0x80034a04` (ACC_01 57\|1) and `0x80034b58` (TSK_02 12\|1);
  `FUN_800b0e94` (`a59b`.0 → `d0000113`.4); `FUN_801405d4` (`d000a33d`, `d0008d5a`); `FUN_80140922`
  (internal standstill flag `d000a35c`, cal #780 `0x803dba70[0x13]` = 1); L2 floor `0x80389809`;
  `a9` = cal-object table `0x80103464`.
