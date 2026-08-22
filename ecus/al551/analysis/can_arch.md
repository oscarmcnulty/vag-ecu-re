# AL551 TCU — CAN stack architecture (RE notes)

All addresses from the 4H1927158AD bench image (`benchdump/R5F72519R_...flash...bin`),
Renesas SH72519 (SH-2A, big-endian). RAM addresses need re-verification vs the 8R image.

## Tables (flash)
| what | addr | layout |
|------|------|--------|
| CAN-ID master table | `0x044760` | flat `u32` CAN IDs, stride 4 (RX+TX). Mirror @`0x05dd26`. |
| Message descriptor table | `0x04248c` | 44× 20-byte records (below) |
| TX mailbox descriptors | `0x05dd20` | 16-byte records, ID@+6, DLC@+10 |
| RX data-buffer table | `0x044870` | 24× 12-byte records: {flags_ptr, databuf_ptr, msg_index} |

### Descriptor record (20 bytes, @0x04248c)
```
+0x00 u32  &ID_table_entry     -> deref = CAN ID
+0x04 u32  acceptance mask     (0x7ff full, 0x7c0 for NM group)
+0x08 u8   flag1
+0x09 u8   DLC
+0x0a u8   flag3
+0x0b u8   flag4
+0x0c u32  handler (TX pack thunk, or 0 = generic RX buffer copy)
+0x10 u16  msg_index
+0x12 u16  pad
```
Records 0x01–0x26 = RX acceptance list (handler 0). Records 0x27–0x2c = periodic-TX
list with pack-thunk handlers. → `al551_can_descriptors.csv`.

## TX path
Each periodic-TX message has a thunk (e.g. `0x074314` for Getriebe_01):
```
mov.l  #pack_fn, r5        ; r5 = per-message pack function
mov.l  #0x074ae0, r2       ; r2 = common TX driver
jmp    @r2                 ; -> FN_74ae0(can_id_in_r4, pack_fn_in_r5)
```
`FN_74ae0(id, pack_fn)`: scans the TX slot table (`iRam0074b28`, stride 0x50) for the
message, prepares the slot (`FN_74ac2`), then calls `pack_fn()`.

Each `pack_fn` copies the 8-byte payload from a **working buffer** into the **frame
buffer**, and writes the bitwise-**inverted** copy into a mirror buffer (integrity check),
then fixes up the COUNTER/CHECKSUM nibble (e.g. Getriebe_01 counter/alive @`0xfff9397e`).

### Confirmed TX frame buffers (`al551_can_tx_buffers.csv`)
| ID | msg | frame | working src | inverted |
|----|-----|-------|-------------|----------|
| 0x082 | Getriebe_01 | `0xfff91c88` | `0xfff91c90` | `0xfff91c98` |
| 0x083 | Getriebe_02 | `0xfff91cb0` | `0xfff91cb8` | `0xfff91cc0` |
| 0x390 | WBA_01 | `0xfff91e60` | `0xfff91e68` | `0xfff91e70` |

The full TX/RX frame-buffer pool spans `0xfff91c00`–`0xfff91f00` (frame/working/inverted
triples per message). Getriebe_03/04 are **not** in this image's periodic-TX list — the 4H
bench dump is an A4/A5 application; the 8R (Q5) image must be checked for its own TX set.

## RX path
Generic messages (handler 0) are copied into their `databuf_ptr` (`0xfff91ae8`…`0xfff91bb8`,
8 bytes each) by the receive routine; consumers read signals out of those buffers. The
descriptor `msg_index` (0x01–0x2c) and the RX-buffer `msg_index` (0x4c–0x62) are distinct
index spaces — consistent with the SH72519 RCAN-ET having multiple channels/mailbox banks.

## Not yet pinned
- RCAN-ET peripheral register base (driver uses a RAM-held base pointer, no literals).
- Per-signal RAM source addresses feeding the TX working buffers (upstream of the packers).
- msg_index ↔ RX-databuf join for the 0x4c–0x62 space.

## 8R (Q5) rebase — VERIFIED (2026-08-20)
Assembled `tcu_8R_plaintext/8R_full_flash.bin` from the decoded 8R0927158AM (SW1003) blocks
at their flash bases (ASW 0x040000, blk2 0x006000, CBOOT 0x020000, CAL 0x180200 — bases
located by matching the shared 4H blocks in the bench dump).

**Result: 8R and 4H share the AL551 application byte-for-byte in RAM layout.** The CAN-ID
table (0x044760), descriptor table (0x04248c), RX-buffer table (0x044870) and every TX/RX
frame-buffer RAM address are at identical offsets/values on the 8R. Only (a) CAL data content
(0x180200+) and (b) packer code addresses differ (e.g. Getriebe_01 packer 0x074314 on 4H →
0x075aee on 8R). **So all `al551.a2l` ECU_ADDRESS values are correct for the Q5 car as-is.**

### Firmware-truth TX set (corrects DBC node attribution)
Only these carry a real packer + frame buffer, i.e. are actually transmitted by this ECU:
`0x082 Getriebe_01`, `0x083 Getriebe_02`, `0x390 WBA_01`, `0x393`, `0x088` (+ NM 0x6c2, UDS
resp). **Getriebe_03 (0x102) and Getriebe_04 (0x441), though DBC-attributed to the AL551
node, have NO packer/frame buffer in either image — they sit in the RX acceptance list
(descriptor idx 0x03/0x04, handler 0).** On this AL551 8HP platform they are received, not
sent (the DBC's `Getriebe_AL551_951_D4_C7` node lumps several gearbox variants together).
