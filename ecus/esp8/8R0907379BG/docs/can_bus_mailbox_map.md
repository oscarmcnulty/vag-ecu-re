# ESP8 CAN controllers + full mailbox map (which messages on which bus, RX/TX)

Byte-exact decode of the mailbox-config table `0xaea38` (62 records, stride 0x18), cross-checked
against the RX ISR (`can_rx_isr` 0x8f708) and resolver (`rx_mailbox_resolver` 0x501d4). Goal: list
every message the ESP sends/receives per physical CAN controller, to plan the EPB MITM.

## Two HECC controllers = two physical buses
- **Module A**: mailbox RAM base `0xfff7e400`, control block `0xfff7e800`, ctrl-sel 1.
- **Module B**: mailbox RAM base `0xfff7e600`, control block `0xfff7ea00`, ctrl-sel 2.
Mailbox address = base + slot*0x10 (32 mailboxes/module). `can_rx_isr` handles both.

Record fields (verified): +0x00 mailbox-RAM addr, +0x04 handler (0=COM-masked RX / 0x126xx-0x127xx
island=dedicated RX / 0xea68 island=TX-confirm), +0x08 ctrl block, +0x0c {byte0=ctrl-sel, byte1=DLC},
+0x10 arb=id<<18, +0x14 CANRMP pending bit. One masked mailbox can serve several ids (listed per slot).

## MODULE B — the ESP's main powertrain / chassis + diagnostics bus
This bus carries ALL three braking inputs **and** the ESP's own status TX → the single MITM target.

| slot | dir | handler | CAN ids (DBC name, best-effort) |
|---|---|---|---|
| 0 | RX | 0x127ed | 0x6b4 0x6b7 0x6b8 0x6d9 (UDS/diag) |
| 1 | RX | 0x12771 | 0x6c0 0x6c7 0x6d0 (diag), **0x110** (radar/AEB, event-only) |
| 2 | RX | 0x1274d | 0x641 0x062 |
| 3 | RX | COM | 0x39c |
| 4 | RX | 0x12729 | 0x395 0x441 |
| 5 | RX | COM | **0x040 Airbag_01** |
| **6** | RX | COM | **0x10c TSK_02** — engine's `TSK_Verzoeg_Anf` decel request (comfort/mode-2 lane) |
| **7** | RX | 0x12701 | **0x117 ACC_10** (ANB/mode-4), 0x102 Getriebe_03 |
| 8 | RX | 0x126dd | 0x11d LH_EPS_02, 0x114 Motor_10 |
| **9** | RX | 0x126bb | **0x104 EPB_01**, 0x105 Motor_03, 0x086 LWI_01 |
| 10 | RX | 0x127ad | 0x085 SCU_01, 0x09f LH_EPS_03 |
| 11/12 | RX | 0xa43f5 | 0x4a3, 0x203 |
| 13/15/16 | RX | COM/fn | 0x6ff, 0x200, 0x019 (diag/test) |
| 17-20 | RX | COM | 0x082 Getriebe_01, 0x080 Motor_01, 0x081 Motor_02, 0x084 ESP_06 |
| 21 | RX | 0x126a9 | 0x6ff 0x6c3 (diag) |
| 22 | RX | 0x9b369 | 0x394 |
| 23 | RX | COM | 0x632 0x64a |
| 24 | RX | COM | 0x308 ESP_04 |
| 25 | RX | 0x12697 | 0x392 ESP_07, 0x11e ESP_08 |
| **26-29** | **TX** | 0xea68 island | **0x101 ESP_02, 0x103 ESP_03, 0x106 ESP_05, 0x100 ESP_01** |
| 30 | TX | 0xea68 | 0x08b |
| 31 | TX | 0xea68 | 0x7e0 (UDS response) |

## MODULE A — secondary bus (smaller set)
| slot | dir | ids |
|---|---|---|
| 0-6 | RX(COM) | 0x061, 0x065, 0x071, 0x072, 0x066, 0x661 (trailer), 0x604 |
| 14/15 | RX(COM) | 0x7e8, 0x7e1 (ISO diag) |
| 29 | TX | 0x6ff |
| 30/31 | RX(COM) | 0x060, 0x08a |

## Key conclusions (verified)
- **EPB_01 (0x104), ACC_10 (0x117) and TSK_02 (0x10c) are all on Module B** — the same bus the ESP
  transmits ESP_01/02/03/05 (0x100/0x101/0x103/0x106) on. So the MITM interposer goes in series on
  **Module B** (between the EPB ECU and the ESP), and from that one bus you can both read ACC_10/TSK
  and rewrite EPB_01.
- **ACC_01 (0x109) is NOT received by the ESP** (no mailbox) — consistent with the engine/ACC master
  consuming ACC_01 and sending the ESP a decel request via **TSK_02**. Only ACC_10 is consumed
  directly by the ESP.
- The ESP's **TX** set on Module B is exactly ESP_01/02/03/05 (+0x08b, +UDS 0x7e0) — so an interposer
  must forward those outbound untouched.

## Honest limits (NOT verified — do not treat as fact)
- **Acceptance masks**: `rx_mailbox_resolver` indexes per-slot data at 0xb71d4 (B) / 0xb7154 (A) for
  masked matching, but those values do not parse as clean CAN masks, so the full set of ids each
  masked mailbox accepts is unresolved. Reception of ids with **no dedicated record** (ACC_05 0x10d,
  Motor_04 0x107, TSK_01 0x10a, etc.) is therefore **not statically verified**.
- **DBC names** are best-effort from opendbc `vw_mlb.dbc` (a newer Audi MLB matrix); the diagnostic
  range (0x6b4/6b7/6b8/6c0/…) are UDS addresses and the newer-matrix names (VIN_01/Kombi_0x) are
  likely not literal for this B8 image — treat ids as authoritative, names as hints.
- **Direction**: TX of 0x100/0x101/0x103/0x106 is cross-verified (pack/TX-scheduler + DBC). Other
  entries in the 0xea68 island (0x08b, 0x7e0, module-A 0x6ff) are TX by that handler-cluster + protocol,
  not individually re-traced.
- Which module is physically the "sensor" vs "powertrain" wire is an inference from the id sets
  (Module B = powertrain/chassis+diag by its contents); the firmware proves the controller split and
  id assignment, not the harness label.

Reproduce: decode 0xaea38 (stride 0x18, 62 recs) + the handlers; `can_rx_isr` 0x8f708 / resolver
0x501d4; E2E verifier `e2e_xor_rx_verify` 0x5f57c; DBC opendbc `vw_mlb.dbc`.
