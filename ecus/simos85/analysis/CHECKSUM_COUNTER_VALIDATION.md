# Simos8.5 — how CAN RX handles checksum & counter validation

Engine ECU `8R0907551F` (Continental Simos 8.5, TC1796). Cross-referenced against openpilot
`opendbc/car/volkswagen/mlbcan.py` + `mqbcan.py` + `crc.py`. All firmware addresses verified against
the 2 MB image.

## TL;DR
- The firmware contains **three** integrity primitives, used for **different purposes**:
  1. **CRC-8 / AUTOSAR E2E** (poly 0x2F) — `checksum8_autosar_fn @0x800a5a18`, table `@0x80080aec`.
  2. **CRC-16** — `@0x800a59f0`, 16-bit table `@0x800808ec` — used **only for UDS diagnostics** (flash
     transfer-block validation), NOT for periodic signals.
  3. **XOR checksum** — openpilot's method for most periodic messages (incl. ACC_01). No dedicated XOR
     function has been located, and where ACC_01's validator lives is **still open** (see the
     "dynamically assigned?" section — it most likely runs on the CAN-RX interrupt path, or is done by
     the gateway). NOTE: an earlier draft's claim that "ACC_01 checksum is a stub / not enforced" was
     based on a MIS-identified Com record field and is retracted.
- **Correction:** `process_ecu_command_800af8bc` (the "generic RX" I chased earlier) is actually the
  **ISO-TP / ISO-15765-2 segmentation handler** for diagnostic channels (SF/FF/CF), NOT the periodic
  signal unpacker. That is why the earlier index-sweep wrote no signal mirrors.

## openpilot's two VW-MLB methods (the reference)
From `mlbcan.py::volkswagen_mlb_checksum`:
- **CRC8-H2F** for `{0x9F LH_EPS_03, 0x117 ACC_10, 0x126 HCA_01}` (`crc8h2f_checksum`, AUTOSAR E2E,
  poly 0x2F, per-message 16-entry magic byte constant XORed by the counter `d[1]&0x0F`).
- **XOR** for everything else: `checksum = initial_value; for i!=cksum_byte: checksum ^= d[i]`, with
  `initial_value = (address & 0xFF) - 1`, plus adjustments:
  - `0x397 LDW_02`: seed-2
  - `0x102/0x106/0x10E` (Getriebe_03/ESP_05/TSK_04): seed+2
  - `0x30C/0x324` (ACC_02/ACC_04): seed+4
  - **`0x109 ACC_01`: no adjustment → seed = 0x09-1 = 0x08**, checksum byte = byte 0:
    `byte0 = 0x08 ⊕ d1 ⊕ d2 ⊕ … ⊕ d7`.

## 1) CRC-8 / AUTOSAR E2E — `checksum8_autosar_fn @0x800a5a18`
```c
uint checksum8_autosar_fn(byte *data, int len, uint crc) {   // crc seeded 0xFF by caller
  for (; len != 0; len--) crc = CRC8_AUTOSAR_TABLE[crc ^ *data++];   // table @0x80080aec (poly 0x2F)
  return crc ^ 0xff;
}
```
- Byte-for-byte the CRC-8/H2F openpilot uses (`crc8h2f_checksum` inner loop). The 256-entry table at
  `0x80080aec` is the exact poly-0x2F table (verified by regenerating it and matching).
- **Status in THIS image: zero callers and zero stored function-pointers.** So the engine ECU does not
  invoke CRC8-H2F for any RX path here — the CRC8 E2E messages (0x9F/0x117/0x126) are validated by the
  gateway, not the engine, and/or this is library code retained but unused in this variant.
- The per-message magic-byte constant tables (openpilot `VOLKSWAGEN_MQB_MEB_MLB_CONSTANTS`) were NOT
  found verbatim in flash → consistent with CRC8-H2F being unused here.

## 2) CRC-16 — `@0x800a59f0` (16-bit table `@0x800808ec`)
```c
d5 = (d5 >> 8) ^ table16[(byte ^ d5) & 0xff];   // per byte; table16 @0x800808ec
```
- Callers are all **UDS diagnostics**: `uds_validate_xfer_block@801d1ebe`, `uds_crc16_caller_a/c/d`,
  `handle_ecu_command_801d2da0`. i.e. CRC-16 protects UDS/flash transfer blocks (RequestDownload /
  TransferData), NOT periodic CAN signals.

## 3) XOR checksum (periodic messages) — NOT enforced by this ECU
- openpilot computes an XOR checksum for ACC_01 and most periodic messages, but:
  - There is **no dedicated XOR-checksum function** in the firmware (searched the CAN driver + Com
    clusters; only the two CRC primitives above exist).
  - The Com per-message hooks that WOULD validate it are **stubs** for 0x109 (see below).
- Conclusion: **the Simos8.5 does not validate the XOR checksum (nor an alive-counter) on periodic RX
  signal messages like ACC_01 at the application layer.** Bus-level E2E is the gateway's job; the
  engine consumes the decoded signals.

## Per-message Com record fields — CORRECTION: record+0x20 is NOT the checksum
An earlier draft called the record `+0x20` field the "CHKSUM fn". That is WRONG: reading the 3 records
that hold non-stub values there (0x801b63fc/0x801b6534/0x801c6110) shows they are message
**receive-notification / state hooks** (set a RAM flag, call `check_and_process_map`, snapshot state) —
not checksum routines. So there is **no static per-message checksum function** in the Com records, and
the fact that 75 records share `0x801d0360` there just means "no notification hook."
- (`0x801d3160`, previously mis-attributed as an 0x109 handler, is actually
  `compare_firmware_block` vs "111S85P0L200" — a flash-ID check, not a checksum.)

## Are the checksum/counter validators DYNAMICALLY assigned? (the right question)
This firmware assigns almost every important handler at runtime via computed-pointer stores invisible
to static xref (c03fc37c, DAT_d00072c4, the RX dispatch table, …). So the natural hypothesis is that
the E2E checksum/counter validators are runtime-assigned too. Tested so far:
- **RAM scan after full-init boot for `0x800a5a18` (CRC8) / `0x800a59f0` (CRC16)**: NOT present in any
  runtime table (c0xxxxxx / d0xxxxxx). So those two specific CRC fns are not dynamically installed as
  RX validators during boot. (CRC8-H2F remains only-defined-never-referenced; CRC16 stays UDS-only.)
- ACC_01 uses **XOR**, not CRC8 — and no dedicated XOR-checksum function has been located, so a scan
  for "its" pointer isn't yet possible. The XOR path (if the engine runs it) is still unlocated.
- Most likely reality: the ACC_01 checksum/counter check runs on the **CAN-RX interrupt path**, reading
  the raw frame that `8011e8f8` stages to **d000d40a** — which is exactly the still-unlocated consumer
  of d000d40a (read-watch = 0 cyclic reads; it only runs on the IRQ we can't fire). i.e. the checksum
  validator and the signal-unpack are the SAME IRQ-gated chain. Alternatively the engine trusts the
  gateway's E2E (common in VW: the gateway validates/forwards, powertrain ECUs consume) — which would
  explain why no engine-side XOR validator exists.
=> Open, and the decisive next step is the same as for the unpack: reproduce the CAN-RX interrupt (or
find who reads d000d40a) — that chain is where any checksum/counter check for ACC_01 lives.

## Counter / sequence handling that DOES exist
- **ISO-TP** (`process_ecu_command_800af8bc`): validates the frame's PCI nibble `d[0]>>4`
  (0=SingleFrame, 1=FirstFrame, 2=ConsecutiveFrame), the 12-bit FF length
  `(d[0]&0xF)<<8 | d[1]`, and sequence via the per-channel state (`puVar15`) — the diagnostic
  transport counter, not a signal alive-counter. Reached from `canmo_<id>` handlers (0x10a→6, 0x10b→5,
  0x10f→4, …) for the diagnostic/TP channels.

## Implication for openpilot (honest, current)
- CRC-8/AUTOSAR-E2E is present (`0x800a5a18`) and matches openpilot's `crc8h2f` exactly, but is not
  referenced for RX in this image; CRC-16 is UDS-only. So the ONLY confirmed application of a message
  checksum in this ECU is UDS diagnostics.
- Whether the engine validates ACC_01's XOR checksum/counter is **not yet resolved**. The two live
  hypotheses: (a) it runs on the CAN-RX interrupt path (reading the raw frame staged at d000d40a — the
  unlocated d000d40a consumer), or (b) the gateway enforces E2E and the engine consumes decoded
  signals. Resolving it requires reproducing the CAN-RX IRQ or locating the d000d40a reader.
- Practical takeaway for now: correct alive-counter + checksum on ACC_01 is still the safe assumption
  for openpilot (some node on the bus enforces it); we have NOT proven the Simos ignores them.

## The real RX chain for 0x109 (traced end-to-end) — confirms the "dynamically assigned" hypothesis
The per-message handling IS runtime-dispatched, exactly as suspected; static Com-record fields are the
wrong place to look. The chain:
1. **CAN-RX interrupt** -> a RAM-resident ISR at flash **0x801f8382** (copied to 0xd4000000 scratchpad;
   RAM code region = flash 0x801f7478 mapped to 0xd4000000). The ISR atomically reads-and-clears the
   CAN interrupt-pending mask (`swap.w` @0x800a5a5e) on a **second CAN controller @0xf0050800**, then
   for each pending message-object bit does `calli` on that object's handler.
2. For 0x109 the object handler is **8011e8f8** (`canmo_109_ACC_01`): copies the 8 mailbox bytes to
   **d000d40a**, sets d000d408=1/d000d412, then **enqueues** the frame (via `0x801f8b70`) onto a
   deferred RX queue at **0xd4001970**.
3. A **deferred queue processor** (0x801f8494) pops nodes by priority and `calli`s each node's runtime
   handler `*(node+8)` = a jump-table veneer **0x800b0a20** -> per-message process fns **8011e67c /
   8011e69c**, which manage the 0x109 flags/buffers (clear d000d408, copy via 800b15cc/800b15ea).
So the process handlers are **runtime-assigned pointers in RAM queue nodes** (flash node 0x80082a18
has +4 = a count, not a handler) — dynamic dispatch, invisible to static xref.

## Did tracing the DYNAMIC chain reveal a checksum/counter check? (thorough negative, so far)
Searched everywhere the frame could be validated:
- The staged frame **d000d40a is referenced ONLY by 8011e8f8** in the entire decompiled corpus; the
  deferred process fns (8011e67c/69c) do flag/buffer work, not a checksum.
- Disassembled the ENTIRE RAM-resident RX region (flash 0x801f7478-0x801f9000, 2644 insns): every
  `xor` is the interrupt-priority critical-section pattern (`mfcr/xor d15,d8/mtcr`); **no byte-XOR fold
  over frame data**.
- CRC8-H2F (0x800a5a18) has zero callers/pointers; CRC16 is UDS-only; RAM scan found neither installed
  in any runtime table.
- The generic engine extracts ACC_01's CHECKSUM/COUNTER (bytes 0/1) to mirrors **d000d458/d000d457**,
  and **nobody reads those mirrors** (FindRefsTo = none).
=> Across every REACHABLE path, no ACC_01 checksum/counter recompute is performed by the engine.
HONEST RESIDUAL: the final generic-engine signal-scatter for 0x109 is a computed-pointer step that
only executes on the real CAN-RX interrupt (never fired in emulation). A CRC/counter gate INSIDE that
unpack (validate-then-scatter) cannot be 100% excluded until that exact code path is executed. The
decisive test remaining is to fire the RAM-resident ISR (0x801f8382) with a 0x109 message object set
up on the 2nd CAN controller (0xf0050800), and watch the full chain.
- Most-probable interpretation: E2E is enforced at the **gateway** (ACC_01's DBC sender is Gateway_B8,
  and it forwards to the powertrain bus); the engine consumes forwarded signals. This is the standard
  VW split and matches all the evidence — but is not yet proven against the IRQ-only scatter.

## DECISIVE TEST — fired the RX chain in the emulator (EmulBoot arg[5]=8011e8f8)
Reproduced the real RX path: bridged to run-mode (CAN+Com initialized), loaded the 0x109 message
object, invoked **8011e8f8** (stage+enqueue), then the **deferred queue processor 0x801f8494**, then
resumed the run-mode scheduler for ~5M steps. Watched: reads of the staged frame, calls to any
checksum primitive (0x800a5a18/0x800a59f0/0x800a5a5e/the RAM XOR region), and ACC mirror writes.
Findings:
- The staged frame d000d40a **IS consumed** — by a transport/status state machine at 0x8011e5c4+
  (`lea a15,[a0]0x540a` = d000d40a): it reads frame bytes, checks a message-TYPE byte
  (`frame[0]==1/5`, `[frame+8]<4`), sets status bits in d000d3ec, and RE-ENQUEUES via halt_baddata.
  This is an ISO-TP-like transport SM, not a signal decoder.
- **ZERO checksum-function calls** anywhere in the fired chain + the ~5M-step scheduler run.
- **ZERO ACC mirror writes** (d000d5xx/d6xx never leave their 0x55 init pattern).
So even with the RX path actually executing, the engine performs no checksum recompute, and the
generic-engine ACC-signal scatter still does not fire (it has yet another trigger not reproduced).
=> Strong, now emulation-backed evidence that **the Simos does not validate ACC_01's checksum/counter**;
consistent with gateway-enforced E2E (DBC sender Gateway_B8). The only residual is the ACC-signal
scatter itself, which never executes in-emulator — but nothing around it (before, during dispatch, or
after in the scheduler) ever touches a checksum primitive.

## Addresses (quick reference)
| item | addr |
|---|---|
| CRC8-H2F fn (AUTOSAR E2E, poly 0x2F) | `0x800a5a18` |
| CRC8-H2F 256-byte table | `0x80080aec` |
| CRC16 fn (UDS) | `0x800a59f0` |
| CRC16 table (16-bit) | `0x800808ec` |
| Com record +0x20 = receive-notification hook (NOT checksum) | `0x801d0360` default |
| ISO-TP handler (NOT signal unpack) | `0x800af8bc` |
| 0x109 raw-frame staging buffer (checksum validator's likely input) | `0xd000d40a` |
