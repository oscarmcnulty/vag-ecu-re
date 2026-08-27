# 8R0909144F EPS — CAN reception: consumed messages + propagation

Recovered from the gp/tp-resolved V850 decompile. The reception stack is a generated COM
layer over the on-chip AFCAN controller.

## Hardware
- **AFCAN** controller, message buffers at `0xFFFFFD00` (stride `0x20`); driver = `FUN_0000ffb6`
  (buffer control), `FUN_0001024c`/`FUN_00010040`/`FUN_000100c0` (config), `FUN_00010326` (TX).
- **Two channels**, set up in `FUN_0002929a` (crt0 init): **ch1 @ 500 kbps**, **ch2 @ 1 Mbps**
  (`FUN_0001024c(handle, 500000/1000000, 128000000 fosc, …)`).
- Acceptance is **mask-based** (masks at `0xfffff1d6/d8`): the HW accepts a broad range into a
  few buffers, and software demultiplexes by CAN ID.

## Software demux + the consumed message set
`FUN_0002c044` registers every received PDU into the COM router `0xfffece9c` via
`FUN_00018b00(pdu_struct, channel, buffer, CAN_ID, start_bit, size_bits)`. PDU structs are a
`0x18`-strided array from `0xfffede90`. The distinct **consumed CAN IDs**:

| primary ID | redundant twin | Δ | RX buffer | size | processor | superv. tag |
|---|---|---|---|---|---|---|
| `0x000` | `0x169` | +0x169 | `0xfffe8038` | 8b  | `FUN_0002c50c` | `0x80` |
| `0x009` | —      |        | `0xfffe804c` | 160b| `FUN_0002c706` | `0x40` |
| `0x0AA` | `0x172` | +0xC8 | `0xfffe8190` | 104b| `FUN_0002c5d2` | `0x20` |
| `0x113` | `0x1DB` | +0xC8 | `0xfffe8264` | 4b  | `FUN_0002c832` | `0x100`|
| `0x118` | `0x1E0` | +0xC8 | `0xfffe8270` | 80b | `FUN_0002c76e` | `0x02` |
| `0x231` | —      |        | `0xfffe8314` | 32b | `FUN_0002c8f8` | `0x200`|
| `0x252` | `0x355` | +0x103| `0xfffe8358` | 46b | `FUN_0002c960` | `0x04` |
| `0x281` | `0x384` | +0x103| `0xfffe8418` | 26b | `FUN_0002ca94` | `0x08` |
| `0x29C` | (×3)   |        | `…8488/85fc/8770` | 184b | (2nd group) | |
| `0x39F` | (×2)   |        | `…88e4/9190` | 1108b/340b | (2nd group) | |

Notes:
- **Redundant pairs**: most messages have a twin ID at a fixed offset (+0xC8 or +0x103); the
  processor takes whichever copy is fresh (ASIL redundant reception). `0x29C`/`0x39F` are
  registered 2–3× on separate buffers = received on **both** CAN channels.
- `0x39F` is large (138 B / 42 B) → a multi-frame / segmented PDU.
- IDs are the raw registration values; mapping to VW signal names needs the `EV_RCEPSAU48X` DBC.

## Propagation (per received message)
1. **HW RX** (mask-filtered) → frame queued to the router `0xfffece9c`.
2. **Per-cycle processing** — `FUN_0002c4d6` fans out to the per-message processors
   (`FUN_0002c50c`, `…c5d2`, `…c706`, `…c832`, …). Each:
   - checks freshness of the primary and redundant twin (`FUN_00018b70`),
   - unpacks whichever is fresh (`FUN_00018ccc`) with an **E2E/CRC check** (`FUN_00018f04`
     compares a stored checksum),
   - writes the value into an **ASIL-protected buffer** as *value + bitwise-inverse*
     (e.g. `uRamfffe8264` / `uRamfffe8268 = ~value`, via `FUN_00011fd6`),
   - reports validity to the **supervision/DTC layer** `FUN_0002ce4a(status, group_tag)`
     (tags `0x02/0x04/0x08/0x20/0x40/0x80/0x100/0x200` = the per-message fault groups).
3. **Consumers** read the protected signal RAM (`0xfffe80xx`) — the steering-control code.

## Open / next
- ID→name mapping (needs the DBC/A2L).
- The `0x29C`/`0x39F` second-bus group's processors (`FUN_0002ce08`/`…cbc8` were stubs in the
  first pass) and whether a separate fast-path exists for any periodic signal.

## RX frame format (fully decoded)
Receive is FIFO-only (`can_rx_fifo_read` drains `0xFFFFFD42`); no code reads message-buffer
IDs/data directly. The FIFO carries a **checksum-protected, sequenced, multiplexed transport**,
walked by `can_rx_frame_reassemble` as **4-word (8-byte) records**:
- word0: marker/length context
- word1: header — `seq` (bits 0-3, incrementing, continuity-checked), `source` (bits 4-5, vs
  expected `*(ch+0x1302c)`), `type` (bits 6-7: 0=data, 1=partial, 3=length/EOB)
- word2: payload
- word3: checksum (`can_rx_record_checksum`: `0x12 + w0 + w1 + w2 == w3.lo`)
Payload is reassembled by `seq` into per-source blocks at `can_rx_reasm_buf` (0xfffec614+ch*0xc);
downstream reads signals by byte offset within a block.

## CORRECTION: the per-11-bit-ID CAN map IS in the firmware
An earlier version of this doc concluded "there is no per-11-bit-ID frame path" and that
`0x126`/`0x130` "never appear as acceptance IDs." **That was wrong** — it was an artifact of the
const-data load offset (`RE_findings.md` → "Const-data load offset"): the AFCAN mailbox ID table
was being read at the literal address instead of `addr − 0x12000`, so it decoded as garbage.

At the corrected offset, the **AFCAN mailbox ID/config table** (address `0x125c0`, file `0x5c0`,
64 × 4 bytes, `stdID = word >> 18`) plainly lists the physical bus IDs, including the RX ones this
ECU consumes: **HCA_01 `0x126` (mailbox 59)** and **PLA_01 `0x130` (mailbox 58)**, alongside
ESP_01 `0x100`, ESP_03 `0x103`, Motor_03 `0x105`, Kombi_01 `0x30B`, Charisma_01 `0x385`,
ESP_07_FR `0x392`, Gateway_05 `0x39C`, Klemmen_Status_01 `0x3C0`, Motor_06 `0x440`. The full
table (with the LH_EPS TX entries) is in `can_tx.md`.

So the hardware CAN-ID → mailbox binding is recovered. What still needs tracing is the propagation
from the HCA_01/PLA_01 mailbox through the COM unpack into the protected signal RAM and on to the
torque/angle limiters — the multiplexed-transport / E2E-Data-ID layer described above is a *second*
(internal/reassembly) stage that sits on top of these hardware mailboxes, which is what made the
two layers easy to conflate. The mode/status path from HCA_01 is already traced end-to-end in
`hca_vs_pla.md`; the torque-limit constants are the remaining open item (`can_to_torque.md`).
