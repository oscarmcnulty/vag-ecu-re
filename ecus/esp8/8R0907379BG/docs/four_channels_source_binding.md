# The 4 decel channels the ESP actuates on — source-side binding (8R0907379BG)

Companion to `decel_paths.md` (which maps the **executor** side: arbitrate → `ecd_mode` →
pressure). This doc pins the **source** side: for each of the 4 typed decel channels, what writes
its value, and how far the CAN-frame origin is statically knowable. Everything here is re-checked
against the raw flash by `decode/four_channel_source_verify.py` (no emulation).

## The staging → current model (VERIFIED)

`com_decel_double_buffer` (0x64ce4) snapshots **all four** channels once per cycle, copying each
one's CURRENT value (what the pipeline reads) from a STAGING address (what the producer writes):

| channel | staging (producer writes) | current = `decel_src` (pipeline reads) | len |
|---|---|---|---|
| **type1** | 0x403fa4 | 0x403fac | 8 |
| **type2** (comfort) | 0x403a6c block | 0x403a7c → `decel_src_comfort` 0x403a40 | 16 |
| **type4** (ANB) | 0x407bac | 0x407bb4 | 8 |
| **type5** | 0x403d6e | 0x403d76 | 8 |

The producer of a channel = whatever writes its **staging** address. This is the clean test that
separates an active channel from an inactive one and the internal-vs-CAN question.

## Per-channel result

### type1 — internal per-corner ECD request (not a single CAN channel)
Staging 0x403fa4 is written by **four in-image functions**: 0x2b568, 0x43228, 0x45060, 0x474bc
(`status_assembler_474bc`, which also feeds type4 staging). type1 is an internally **assembled**
request from status/plausibility flags around 0x403f9e–0x403fac — not a decode of one received
frame. (COM signal 0x037f, buffer 0x403fa2, is unrelated: 0x403fa2 is read only by 0x8ff88 /
0xa0400, outside the decel pipeline, and merely sits ~10 bytes from `decel_src_type1` in RAM.)

### type2 — comfort / ECD (ACC comfort request, CAN origin index-driven)
Producer `decel_src_comfort_calc` (0x88a88) computes 0x403a40 from 0x403a80 / 0x403a86, which
arrive in the current block via the double-buffer from staging 0x403a6c (writers 0xa904, 0x98a6e).
Gated off below 15 km/h by `ecd_speed_gate` (`decel_paths.md` §3).

The comfort CAN request itself is **0x405462** — a field with **zero code stores** and **no dataset
config pointer**, referenced only by 14 reader literal-pools. It is written solely by the
index-driven AUTOSAR COM layer, so the CAN-frame → 0x405462 edge is **not** statically resolvable
(the same COM-indirection wall as the rest of the pack). The adjacent field **0x405460** is a
different quantity — the ECU's internal wheel-speed-derived measured deceleration (5-tap history at
0x4053c8, written by `veh_ref_wheel_estimator` 0x5ee10 and `decel_mode_state_set` 0x8c1e8) used as
controller feedback, not the request.

### type4 — ANB / emergency (AEB, the below-15 km/h brake path)
Staging 0x407bac is written by the **ANB builder `anb_decel_request_build` (0x4bf3c)** (also 0x474bc,
0x4c56c). Inputs are the multi-stage plausibility chain `radar_msg_signal_proc` (0x2c554) →
`anb_signal_conditioning` (0x3bf58) → 0x4bf3c, operating on already-extracted COM signals (0x405abe,
0x40553b, 0x405cac, 0x4055b4) via base pointers. Executor is the flat-step emergency profile, **not**
speed-gated → this is the channel that brakes below 15 km/h (`decel_paths.md` §3,
`can_brake_inventory.md`). CAN origin (ACC_10 / 0x117) is naming-inference; the signal-extraction
edge is index-driven, same wall as type2.

### type5 — inactive on this variant (VERIFIED)
Staging 0x403d6e has **no producer**: the only reference is the double-buffer's own read. Nothing in
the image ever writes it, so `decel_src_type5` is always 0. type5 is a defined-but-unused channel
slot on 8R0907379BG.

## What is and isn't closable statically

- **Closed:** the staging→current→pipeline structure for all 4; which channels are active (1,2,4)
  vs inactive (5); which producer writes each active channel; that type1 is internal and type4 is
  the ANB path.
- **The COM extraction code was hidden, not absent.** The CAN-frame → buffer edge looked
  "index-driven / runtime-only" only because the AUTOSAR-COM deserialization stack lives in a
  **second code region above `0xa2000`** that the pipeline excluded as DATA (see
  `second_code_segment.md`). With that region disassembled (`EspSeg2.java`, now in `reproduce.sh`),
  the extraction functions decompile and the binding is a normal static xref walk — **no bench
  required**.
- **Comfort (type2) traced inward:** request `0x405462` = control block `0x40545a` + 8; message
  block `0x40542c`; deserialized by `FUN_000f9948` (4-phase) → `FUN_000fa23c` from received pool
  `0x405668`. `decel_stage_writer` (0x57044) then reads `0x405462`.
- **Remaining (bounded, static):** the last hop from each COM message (control block / pool slot /
  handle) to the exact CAN-id, via the RX-indication → mailbox config `0xaea38` (`{CAN-id, handle}`,
  decoded). DBC candidates to confirm: type2 = ACC_05 (0x10d) `ACC_Verz_anf`; type4 = ACC_10 (0x117)
  `ANB_Zielbrems_*`. `f9948` is scheduler-dispatched (indirect), so the trace climbs the COM RX
  scheduler rather than an absolute handler table.

## Reproduce
`python3 decode/four_channel_source_verify.py` (uses `firmware/…bin` + `analysis/decompiles_r`).
Executor side: `docs/decel_paths.md`. CAN inventory: `docs/can_brake_inventory.md`.
