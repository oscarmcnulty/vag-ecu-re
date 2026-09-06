# ESP8 8R0907379BG — full CAN rx/tx message inventory

Complete, code-derived list of every CAN message the ESP8 handles, decoded from the on-chip
routing tables and named against opendbc `vw_mlb.dbc`. Reproduce: `python3
decode/can_routing_tables.py` (writes `decode/can_inventory.csv`). 334 distinct CAN-ids.

## The routing tables (all static, decoded)
| table | addr | role |
|---|---|---|
| `msg_cfg` | `0xa9fc0` | 239 RX records `{canid, timeout, mode, routine, state_ram}` (stride 0x14). state_ram = `0x404558 + 4*i` (4-byte status slot). Covers the `0x117+` and `0x0xx/0x1xx/0x2xx` sets. |
| `can_id_array` | `0xafae0` | 136-id flat array = the core powertrain/chassis cluster `0x080–0x116` (high-rate). Mixes the ESP's own TX (ESP_0x) with RX (EPB/ACC/TSK/Motor/Getriebe). |
| `gateway_fwd` | `0xb1da6` | 19 records `{canid, target, flag}` (6 bytes) — messages the ESP forwards (targets `0x167`/`0x168`). |
| `hw_mailbox` | `0xaea38` | 31 HW RX mailbox filters `{hwreg, filter, dlc, canid, handle, mask, type}` (stride 0x18). handle↔mailbox; EPB_01 `0x104`→handle `0x25b` (anchor). |
| `signal_desc` | `0xb6a44–0xb7800` | flat signal-descriptor stream `{count, buffer, bit-spec}` — per-signal RAM buffer + bit position/length for the explicitly-handled signals. |

## RX routines (msg_cfg field 4) — 4 message classes
`0x8e3ec` (generic copy-to-state_ram, 222 msgs), `0x91898` (8), `0x908d4` (3), `0x9036c` (6).

## TX (composed and sent by the ESP)
ESP_01 `0x100`, ESP_02 `0x101`, ESP_03 `0x103`, **ESP_05 `0x106`** (packed by `esp_msg_pack_525c`
/`com_signal_compose` from `esp05_sig_*` `0x405e81-98`), ESP_08 `0x11e`. ESP_05 carries the brake
feedback (`ESP_Bremsdruck`, `ESP_Verz_EPB_aktiv`, `ESP_Status_Bremsdruck`).

## Received longitudinal / brake-relevant messages (named)
| canid | msg | carries (DBC) |
|---|---|---|
| `0x104` | **EPB_01** | `EPB_Verzoeg_Anf` (0.048, −7.968), `EPB_Freig_Verzoeg_Anf` |
| `0x109` | **ACC_01** | ACC status/basic |
| `0x10a` | TSK_01 | drivetrain-coordinator |
| `0x10c` | **TSK_02** | `TSK_Verzoeg_Anf` |
| `0x111` | TSK_05 | |
| `0x117` | **ACC_10** | `ANB_Zielbrems_Teilbrems_Verz_Anf` (0.024, −20.016) + `ANB_*_Freigabe` |
| `0x126` | HCA_01 | front-sensor (Frontsensorik) |
| plus | Motor_01/02/03/04/10, Getriebe_01/02/03 | powertrain torque/state |

## Correction: the comfort-ACC messages are NOT received
`ACC_05` (`0x10d`, carries `ACC_Verz_anf` 0.005/−7.22 + `ACC_Freigabe_Verzanf`), `ACC_02` (`0x30c`)
and `ACC_04` (`0x324`) appear in **neither** RX table — the ESP8 does not receive them. So the
type2/comfort decel channel is **not** fed by ACC_05 (the pack's earlier assumption is retracted).
The ESP's CAN-sourced decel requests are limited to: **EPB_01, ACC_10 (ANB), TSK_01/02/05, ACC_01**.
Comfort ACC braking value is not received here — consistent with ACC longitudinal being handled by
the engine (Simos) and the ESP doing ANB/EPB/TSK-coordinated braking.

## Cross-map to the decel channels (`four_channels_source_binding.md`)
- type4/ANB decel magnitude is internal/wheel-derived (`anb_target_filter`), CAN gives the ANB
  freigabe (from ACC_10 `0x117`).
- type1 internal; type5 inactive.
- type2/comfort request `0x405462` is CAN-sourced but ACC_05 is ruled out; its source is among the
  received longitudinal set (TSK/ACC_01), pending the object-table signal→buffer resolution.
