# MED17.1.1 — findings & ACC target status

Bosch MED17.1.1, Audi Q5 8R 2.0 TFSI, `8R0907115N_0006`. Infineon TC1797 TriCore, 4 MB flat image at
`0x80000000`. Goal: openpilot longitudinal control, including low speed and standstill.

## The headline: the 15 km/h floor is not in this ECU

The MED17 has **no internal 15 km/h ACC threshold**. It relays `ESP_05` (CAN `0x106`) frame bit 33
`ECD_nicht_verfuegbar` — the ESP/ABS declaring that Externally Controlled Deceleration is unavailable.
Below ~15 km/h the ESP refuses, and the engine withdraws ACC authority in response.

Full chain, on-car evidence and the calibration consequences: **`maps/ecd_relay.md`**.

The practical implication is blunt: **no MED17 calibration edit lifts the floor on its own.** The
decision is made in another module. Any bench validation must check that `TSK_Verzoeg_Anf` actually goes
non-zero below 15 km/h, not merely that TSK_04 grants.

Two ECU-side gates remain real and would still need attention for sub-15 operation:

- **EGAS-L2 cal #208** (`maps/l2_monitors.md`) compares the independent monitor-path speed
  `veh_speed_MON_128` against `0x80389809`=15 / `0x8038980e`=7 and feeds the L2 fault path. It can
  enforce its own boundary regardless of the ESP.
- A **low-speed engage lock** exists (`d00049ca` bit 7 → `FUN_80143b34` → engage state machine) but is
  wired to `ESP_05` bit 36 `ESP_HDC_Standby`, which is 0 on these cars — a real lock that never fires
  here.

## Capability achieved

- **Reproducible labelled project.** `ecus/med17/reproduce.sh` rebuilds from committed metadata only:
  6,406 functions, decompile `ok=6404 degraded=1 bogus=0 fail=1` (100.0% clean), 92.2% of live bytes
  accounted. Firmware-derived output is never committed.
- **Calibration is addressable.** The `a9` cal-object table is resolved (`maps/a9_resolution.md`), so
  every ACC cal read folds to a concrete address.
- **CAN bindings are complete and validated.** 107 messages / 970 bindings
  (`core/maps/decode_can_table.py`). Joined against `vw_mlb.dbc`, **522 of 548** bindings on
  DBC-known messages are exact `start_bit|bit_len` matches (95.3%); ESP_05 is 25/25.
- **The scratchpad library is decodable.** Mapping the boot-copied segment-0xC image turned ~1,900
  previously-unmapped `calla` sites into readable calls and exposed the Kennlinie/Kennfeld
  interpolator family (`maps/kennlinie_interpolators.md`).

## ① Calibration object table — solved

MED17 addresses calibration through an object table at `0x80103464`, reached via `a9`. `*(a9+off)` is
the cal object at table index `off/4`. See `maps/a9_resolution.md`. `core/ghidra/ResolveCalReadsA9.java`
resolves accesses through it, including runtime-indexed ones a regex cannot see.

## ② ACC longitudinal path ACC_01 → TSK — traced

openpilot is ACC master, transmitting `ACC_01` (`0x109`); the engine relays via `TSK_01` (`0x10A`),
`TSK_02` (`0x10C`) and `TSK_04` (`0x10E`). See `maps/acc_flow.md`.

The mechanism that rails all three at once is a single internal flag, **`0xd00049c9` bit 2**, which is
both transmitted (as TSK_01 frame bit 23) and consumed (as the ACC abort request). One transition
produces three observable consequences — status withdrawn, gearbox accel channel substituted to the
cal-0 value, deceleration request hard-zeroed.

Signal identities worth pinning, because earlier work had some of them wrong:

| signal | binding | RAM |
|---|---|---|
| `TSK_Verzoeg_Anf` | 0x10C 56\|8 | `0xd0008d5a` |
| `TSK_Radbremsmom` | 0x10C 40\|12 | `0xd0005de0` |
| `TSK_Status_GRA_ACC_02` | 0x10E 62\|2 | `0xd000ab01` |
| `TSK_Anhalten` | 0x10C 12\|1 | `0xd000a33d` |
| `ACC_Anhalten` | 0x109 57\|1 | `0xd000a59b` |

## ③ Standstill — the hold path is a direct gated relay

`TSK_Anhalten` sources `0xd000a33d`, whose sole writer is `FUN_801405d4:174`:

    d000a33d = (a362 in {1,5} && a454 == 2) ? (d0000113 >> 4 & 1) : 0

and `0xd0000113` bit 4 comes from `0xd000a59b` bit 0 = **`ACC_01` frame bit 57 = `ACC_Anhalten`**. So the
MED17 relays openpilot's hold request directly, subject to a state gate — structurally identical to
Simos 8.5. See `maps/anhalten_compare.md`.

## CAN architecture

The controller is the **TC1797's internal MultiCAN**, two nodes — not an external companion chip over
the MLI, which earlier documentation asserted. Node 0 is the powertrain bus (126 message objects, 52 TX
/ 74 RX); node 1 carries 3 TX objects on 29-bit private identifiers. MO registers at
`0xF0005000 + MO*0x20`, `MOAR = id<<18`. Bit numbering is LSB-first/Intel throughout. See
`maps/can_signal_map.md` and `maps/com_group_direction.md`.

## Two methodology traps that cost real time

Both produced confident false negatives, and both are cheap to avoid once named:

1. **`FindEffectiveAddr` could not see TriCore ABS-mode accesses** (now fixed). ABS encodes
   `EA = {off18[17:14], 14'b0, off18[13:0]}`, so it reaches only the low 16 KB of a segment — exactly
   `0xd0000000..0xd0003fff`, where this ECU keeps its bit-flag block. A live relayed bit was therefore
   mistaken for static variant coding.
2. **Grepping decompiles for `DAT_<addr>` returns nothing once an address is named** in
   `symbols_merged.csv`, because the decompiler emits the assigned symbol instead. A cross-check that
   looked independent was not.

A third, structural one: the COM message table was decoded with the wrong base *and* an off-by-one
boolean pointer, which attributed every single-bit binding to the wrong message. That is what hid the
ECD relay and sent the search after an internal threshold that does not exist.

## Next steps

1. **The lever is not in this ECU.** Target the ESP/ABS, or an actuator path that does not need ECD —
   note `ESP_Verzoeg_EPB_verf` (ESP_05 bit 60) stays 1 on both sides of the floor.
2. If pursuing an engine-side change anyway, EGAS-L2 **#208** must be handled or it will reimpose a
   15/7 boundary from the monitor path. Cal edits need a checksum recompute (`core/checksum`).
3. The standstill path (§③) is a relay and looks tractable independently of the floor.
