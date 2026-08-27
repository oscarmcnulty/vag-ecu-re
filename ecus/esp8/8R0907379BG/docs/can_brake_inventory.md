# CAN messages that can command ESP braking — 8R0907379BG

Definitive, code-derived inventory of every CAN message the ESP8 receives, and which of them
can drive brake pressure. Sourced from the two on-chip receive tables (not the DBC, which is
sparse for MLB — only 3/214 IDs are even named in `vw_mlb.dbc`).

## Two receive subsystems (VERIFIED)
1. **`0xafae0` id-array** — a flat *index→CAN-id* array for the hardware message objects of the
   "core" powertrain/chassis cluster **0x100–0x116**: ESP_01–05 (TX), **TSK_01/02/04/05**,
   ACC_01, **ACC_05 (0x10d)**. Routed by message-object index through parallel index-keyed tables.
2. **`0xa9fc0` config table** — 223 records ×0x14 `{id, timeout_pair, flags, routine=can_rx_indication,
   state_ram}`, covering **214 further IDs** incl. **ACC_10 (0x117)**. `state_ram(i)=0x404554+4*i`
   is a per-message 4-byte status slot (`can_msg_state_ram_base`); the frame payload is copied by
   `can_rx_indication` (0x8e3ec) and signals are extracted by the index-driven COM layer.

Full received-ID set (0xa9fc0 table, 214 IDs): see `docs/msgtab.txt` dump reproducer below.

## Which messages can actually trigger brake pressure
Braking is commanded only through the **4 typed decel channels → arbitrate → ecd_mode → executor**
pipeline (`docs/decel_paths.md`). Of all received messages, the ones carrying a *deceleration
request* that reaches that pipeline are:

| CAN id | msg | signal (DBC) | channel/type | executor | speed-gated? |
|---|---|---|---|---|---|
| **0x10d** | ACC_05 | `ACC_Verz_anf` (0.005, −7.22) + `ACC_Freigabe_Verzanf` | comfort/**type2** (via COM) | `ecd_decel_pressure_calc` (ramp) | **YES — off <15 km/h** |
| **0x117** | ACC_10 | `ANB_Zielbrems_Teilbrems_Verz_Anf` + `ANB_*_Freigabe`, `AWV1_ECD_Anlauf` | ANB/**type4** (via COM) | `ecd_emergency_pressure` (flat) | **NO — works <15 km/h** |
| 0x10c | TSK_02 | `TSK_Verzoeg_Anf` (0.024, −3.984) | drivetrain coordinator → engine torque, **not** ESP hydraulics | — | n/a |

Notes / honest bounds:
- The exact `CAN-id → type` binding is made by the **index-driven AUTOSAR COM signal layer** and is
  not resolvable by static xref (the raw ACC_10 buffer 0x404588 occurs once — in the config table —
  with zero payload xrefs). `type2=comfort`/`type4=ANB` are proven by their *producers*
  (`decel_src_comfort_calc`, `anb_decel_request_build`); the CAN-side edge is naming-inference.
- type1 and type5 are two further internal decel requesters (per-corner ECD substates); no
  distinctive CAN switch appears in their producers, so they are **not** confirmed as HDC/hold.
- ACC_06/ACC_07 (0x120/0x121/0x122 are present in the table) may carry ACC status/accel; not traced
  to a decel channel. If openpilot needs them, bench-confirm.

## Practical answer for openpilot (below 15 km/h)
- **The below-15 brake command is ACC_10** (ANB/type4 → `ecd_emergency_pressure`), which is *not*
  speed-gated. ACC_05 comfort is hard-gated off below 15 km/h.
- That path applies a **flat pressure step** (all 6 setpoints equal), so it is inherently rough.
- Smoothing must happen upstream (openpilot) — see `docs/decel_paths.md` §6.

## Reproduce
```
analyzeHeadless <proj> ESP8 -process 8R0907379BG_0030.bin -noanalysis \
  -scriptPath ecus/esp8/ghidra_scripts -postScript EspDumpTable.java a9fc0 223 20 5
```
