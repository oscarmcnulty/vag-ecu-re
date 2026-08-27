# 8R0909144F EPS — CAN transmission + the AFCAN mailbox ID map

Recovered from the gp/tp-resolved V850 decompile **and bus-validated against a live capture**
(comma route `35258b7bb90057ff/00000005--af6565b8cb`). This is the TX counterpart to
`can_rx.md`, and it also documents the hardware mailbox ID table that finally pins the RX
CAN-ID map (see the correction note at the end of `can_rx.md`).

> **Address convention.** Firmware *const-data* absolute addresses are **0x12000 higher** than
> their offset in `firmware/8R0909144F_0507.bin` (loaded at base 0x0). So a table the code
> references at address `0x125c0` is read from **file offset `0x5c0`** (`file = addr − 0x12000`).
> See `RE_findings.md` → "Const-data load offset". Code addresses are 1:1 (base 0x0); only the
> const/rodata *data* references carry the +0x12000. All addresses below are given as the
> firmware (Ghidra-decompile) address unless a file offset is stated.

## TX path
`FUN_0000ec2c(slot)` is the transmit entry: it looks the slot up in the mailbox# table, copies
the RAM frame into the AFCAN hardware buffer (`FUN_0000ed00`, mailbox regs at `0x8400700 +
mb*0x20`), and triggers TX. Each periodic status message has a small builder that increments the
rolling counter, computes the E2E checksum, and calls `ec2c`:

| builder | slot | RAM frame (byte0=cksum) | CRC magic | → CAN ID | DBC name |
|---|---|---|---|---|---|
| `FUN_0000d916` | `0xb` | `…b6e4` (cksum `…b6e4`, cnt `…b6e5`) | `0x29` | **0x32A** (810) | **LH_EPS_01** |
| `FUN_0000d97e` | `0xc` | `…b6ec` | `0x1c` | **0x11D** (285) | **LH_EPS_02** |
| `FUN_0000d9e2` | `0xd` | `…b6f4` | `0xf5` | **0x9F** (159) | **LH_EPS_03** |

Slots `0..0xa` are non-E2E frames (diagnostics / other), built without a `FUN_0000c67e` CRC call.

### E2E checksum = VAG CRC8H2F, per-message magic
`FUN_0000c67e(buf, len=7, magic)` is the standard VW **CRC8H2F** (poly 0x2F, init 0xFF, final
`table[magic ^ crc] ^ 0xFF`). The 256-byte table is at **address 0x12474 (file 0x474)**. The
`magic` is a single per-message constant (not counter-indexed) — exactly why opendbc models it
as `[0xF5]*16` etc. The three firmware magics `{0x29, 0x1c, 0xf5}` map 1:1 onto opendbc's
`VOLKSWAGEN_MQB_MEB_MLB_CONSTANTS` for `{0x32A, 0x11D, 0x9F}`, and **validate the live bus 40/40**
for LH_EPS_01 and LH_EPS_03. This is how each TX slot's CAN ID was pinned without an A2L: the
CRC seed *is* a per-message address key.

### LH_EPS_03 (0x9F) carries the assist-mode status
Slot `0xd` (`FUN_0000d9e2`) is the assist-status frame. `assist_mode_a`/`_b` (the internal HCA
mode, values `{0,1,2,3,4,8}` and the raw `5`/`7` echo — see `hca_vs_pla.md`) are packed here by
`FUN_0000cf32`/`FUN_0000d012` and shipped as **LH_EPS_03**, whose `EPS_HCA_Status` signal is the
one openpilot's carstate reads (`lkas_fault_route.md`). So the reported-mode 5-vs-7 divergence is
observable in exactly this frame.

## AFCAN mailbox ID/config table — the hardware CAN-ID map
Address **0x125c0** (file **0x5c0**), 64 entries × 4 bytes. Each entry is the AFCAN message-buffer
ID register value; the 11-bit standard ID sits in bits [28:18], i.e. **`stdID = (word >> 18) &
0x7FF`**. This is the physical bus acceptance/transmit ID per mailbox. Decoded (named vs the MLB
DBC):

| mb | word (file off) | stdID | message |
|---|---|---|---|
| 10 | `0x0ca80000` (0x5e8) | 0x32A | LH_EPS_01 **(TX)** |
| 11 | `0x04740000` (0x5ec) | 0x11D | LH_EPS_02 **(TX)** |
| 12 | `0x027c0000` (0x5f0) | 0x09F | LH_EPS_03 **(TX)** |
| … | | | (mb 0–9,13–51: diag/extended/masked buffers, IDs 0x6ff/0x6c9/0x2xx …) |
| 52 | (0x690) | 0x440 | Motor_06 (RX) |
| 53 | (0x694) | 0x3C0 | Klemmen_Status_01 (RX) |
| 54 | (0x698) | 0x39C | Gateway_05 (RX) |
| 55 | (0x69c) | 0x392 | ESP_07_FR (RX) |
| 56 | (0x6a0) | 0x385 | Charisma_01 (RX) |
| 57 | (0x6a4) | 0x30B | Kombi_01 (RX) |
| 58 | (0x6a8) | 0x130 | **PLA_01** (RX) |
| 59 | (0x6ac) | 0x126 | **HCA_01** (RX) |
| 60 | (0x6b0) | 0x105 | Motor_03 (RX) |
| 61 | (0x6b4) | 0x103 | ESP_03 (RX) |
| 62 | (0x6b8) | 0x100 | ESP_01 (RX) |
| 63 | (0x6bc) | 0x08A | (unnamed in DBC) (RX) |

The TX slot → mailbox# table is at **0x1281c** (file 0x81c), one byte per slot; the TX data-buffer
pointer table is at **0x12604** (file 0x604), 4 bytes per slot (points at the `…b6xx` RAM frames).

## Why this matters
- **TX map is fully solved and bus-verified** — no A2L needed. LH_EPS_01/02/03 = 0x32A/0x11D/0x9F,
  and LH_EPS_03 is the status carrier.
- **RX CAN-ID map is now recoverable from firmware.** HCA_01 (0x126) and PLA_01 (0x130) are
  hardware mailboxes 59/58 — the const-data offset (0x12000) is why an earlier pass, reading the
  table at the wrong offset, concluded the per-11-bit-ID map "wasn't in the firmware." The
  signal→torque propagation from those mailboxes is traced separately in `can_rx.md`/`can_to_torque.md`.
