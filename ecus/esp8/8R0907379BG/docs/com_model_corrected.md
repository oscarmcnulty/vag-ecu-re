# ESP8 COM model — CORRECTED (2026-08-23)

Supersedes the `0xb6a44` "descriptor" decode (INVALIDATED — see signal_map.txt header).
This is the code-verified picture of how the ESP moves CAN signals.

## RX path (received messages → internal signals)
1. **`can_rx_indication` (0x8e3ec)** — msg-config `f3` for every record. Generic RX
   indication: copies the received frame payload into a per-message RX buffer (dest ptr
   passed by the dispatcher; the 4-byte `state_ram`=0x404554+4i is the per-message
   status/handle, not the payload).
2. Signal extraction is **table-driven at runtime**: `can_rx_indication` indexes a
   signal-descriptor table via `*DAT_0008e540 = *(0x4069b4)` (stride 0x10, nested lookup).
   **0x4069b4 is RAM** — the table is BUILT AT INIT (populated in the FUN_0006b936 /
   FUN_0006b908 COM-init cluster), so it is NOT statically dumpable from flash.
3. Actual signal values are then pulled by **consumer functions** with hardcoded frame
   offsets (e.g. the decel path: raw ACC_10 → decel_src_comfort via com_decel_double_buffer
   memcpy → arbitration). These per-consumer traces are the trustworthy RX facts and are
   already captured in symbols.csv (re-trace).
=> There is **no single static RX "signal → buffer" table** to extract. A full RX map needs
   either (a) tracing the RAM-table init (FUN_0006b936 area) to recover the flash source, or
   (b) per-consumer traces for the signals of interest. For openpilot, only the decel/brake
   consumers matter and those are already traced.

## TX path (internal status → transmitted messages)  [statically clean]
- **`com_signal_compose` (0x6b00)** — packs internal status words into per-signal TX storage
  bytes with HARDCODED destination addresses (table/pointer driven, 1859 lines, one block per
  signal group, each with its own outgoing-checksum call FUN_0005f57c). This IS statically
  extractable. Verified TX signal-storage regions (the 162 addresses it writes):
  | region | bytes | note |
  |--------|-------|------|
  | 0x405e42-0x405ebd | 124 | **contains ESP_05 (0x106) storage esp05_sig_base 0x405e81** (verified) |
  | 0x406cd2-0x406d4a | 94  | (0x406cd2-ee + 0x406d0a-4a) |
  | 0x408ef1-0x408f06 | 22  | |
  | 0x40902d-0x409034 | 8   | |
  | 0x405edc-0x405ee3, 0x4058ea-ee, 0x40800a, 0x408740 | — | small groups |

## Bottom line
- `com_signal_compose = TX composer` (NOT RX unpack; earlier assumption wrong). Its writes are
  the ESP's OUTGOING signal storage — useful for reading ESP state (ESP_05/08) from the bus.
- The RX signal config is runtime-assembled (RAM table @0x4069b4); no shortcut table exists.
- UNAFFECTED / still valid: all code-traced findings (decel/ANB chain, 15km/h gate, mailbox
  arbitration-ID table, ESP_05 storage). Only the 0xb6a44-derived signal_map.txt was wrong.

## RX map — the recoverable/relevant part (2026-08-23)
Full static RX table does NOT exist (COM routing is runtime-built via allocators
FUN_000a29dc; table @0x40a1a8 accessed by computed address only — no xref, no flash form).
Getting it whole needs either emulating COM init or per-consumer traces. Done for the
openpilot brake path (per-consumer, verified):

  ACC_10 (rx) -> decel_stage_writer (0x57044) + FUN_00098a6e  [extract+stage]
             -> staging 0x403a6c -> com_decel_double_buffer (0x64ce4) -> 0x403a7c
             -> decel_src_comfort_calc (0x88a88) -> decel_src_comfort (type2)
             -> decel_req_assemble -> decel_req_arbitrate -> ecd_state_machine -> pressure.

The decel/ECD signal buffers are enumerated in decode/decel_buffer_map_VERIFIED.txt
(31 groups from com_decel_double_buffer's literal pool). type1/2/4/5 sources all confirmed.

## COM-init emulation attempt (2026-08-23) — see decode/rx_map_VERIFIED.txt
Tried to emulate COM init (Unicorn) to materialize the runtime RX routing table @0x40a1a8.
FAILED: the three init orchestrators (FUN_0006bb22/892a0/6b936) run to completion but only
write small queue-state (0x4069d0-e7); the real table-builder is behind the handle-based RTOS
allocator (FUN_000a29dc, LR-relative computed dispatch) which had to be stubbed. Static side
confirms the wall: ACC_10 signal 0x405462 has NO static writer (deposited by runtime COM at a
computed address). So a per-ID {CAN->buffer} RX table is NOT statically recoverable. Delivered
instead: 214-ID RX/COM inventory, RX signal-buffer ID method (read-by-consumer + no-static-writer
= 259 buffers in 0x405400-0x405fff), and the fully-traced ACC_10 brake chain. Full RX per-ID
attribution needs per-consumer traces (one message at a time).

## RX-routing emulation (#3) verdict — 2026-08-23
Attempted materializing the runtime routing via a recording/backing allocator. DID NOT converge.
PROVEN blocker: COM allocator FUN_000a29dc (Thumb->ARM veneer, LR-relative dispatch) returns a
2-BYTE HANDLE stored as a 2-byte field (FUN_0006b908: `*(undefined2*)puVar1 = FUN_000a29dc(2)`).
A backing allocator returning a 32-bit address truncates to 16 bits -> tables are handle-indexed;
materializing needs the full handle-alloc + resolve machinery, not an identity stub. Boot-from-reset
yields 0 writes (needs peripheral bring-up). can_rx_indication copies to a dispatcher-passed dest
(doesn't self-derive the buffer). Flash group table 0xb6a44's buffer records are the already-
invalidated internal work vars, not raw RX buffers, and its type/sel fields don't match
FUN_000501d4's runtime expectations. Full detail: decode/rx_routing_emulated.txt.
