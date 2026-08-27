# CAN dispatch and E2E across the four images — and how it maps to `vw_mlb.dbc`

Traced 2026-08-20. Sources: each variant's `symbols.csv`; DBC =
`/home/om/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc` (154 messages, 147 standard 11-bit).

## 1. Load-base correction — applies to ALL THREE C7 images

**Every C7 image loads at `0x18000`, not `0x0`.** Proven the same way in each: the IRQ vector
(offset 0x18) leads to a handler that reads the interrupt source byte from MMIO `0xFFFFFE03` and
branches through a pointer table; that table's 24 entries resolve to valid code **only** under
base `0x18000`.

| image | handler-table pointer | entries valid @base 0 | @base 0x18000 |
|---|---|---|---|
| `4G0907379_0190` | `0x1aa05c` | 0/24 (all `0xb6` fill) | **24/24** |
| `4G0907379H_0361` | `0x179eb4` | 3/24 | **24/24** |
| `4G0907379AD_0400` | `0x133ff8` | 0/24 | **24/24** |

The Q5 `8R0907379BG` **is** base `0x0` — its flash-pointer literals cluster in `0xa0000–0xb0000`,
exactly where its CAN id array (`0xafae0`) and descriptor table (`0xb33cc`) live.

⚠ Any C7 address quoted before this correction (including in `c7_comparison.md` §4) is a **file
offset**; add `0x18000` for the load address.

All three C7 images also share the same interrupt controller (source byte at `0xFFFFFE03`) — the
Q5 does not use this scheme.

## 2. The E2E library is IDENTICAL across the whole C7 family

The oldest C7 image follows the newest one exactly. Same five functions, same order, same body
sizes, same signatures — despite `0190` and `AD` being different Bosch projects (`AUDI_B6.01.005`
vs `BEG_VAG.02.002`) that share ~0 % of code bytes:

| role | `0190` (2011) | `0361` (2011) | `AD` ESP9 (2015+) | size |
|---|---|---|---|---|
| XOR checksum | `0x14b720` | `0x15e23c` | `0x118038` | 0x1a |
| CRC8H2F | `0x14b74c` | `0x15e268` | `0x118064` | 0x30 |
| verify XOR | `0x14b77c` | `0x15e298` | `0x118096` | 0x22 |
| verify CRC8H2F | `0x14b7a0` | `0x15e2bc` | `0x1180b2` | 0x22 |
| CRC table (+copy) | `0x1a24d4`/`0x1a25d4` | `0x1728a8`/`0x1729a8` | `0x134304`/`0x134404` | 0x100 |

Both algorithms skip byte 0 and fold a per-frame constant in last. TX wrappers everywhere have the
identical shape:

```
ctr = e2e_counter_next(state)
sig_pack(frame, ctr, startBit=8, len=4, 1, 8)     ; byte1 low nibble
chk = <xor | crc8h2f>(frame, 8, seed)
sig_pack(frame, chk, startBit=0, len=8, 1, 8)     ; byte0
```

## 3. Seeds — stable on TX, evolving on RX

**TX is byte-for-byte identical in all three C7 images:**

| algorithm | seeds / data IDs | `0190` | `0361` | `AD` |
|---|---|---|---|---|
| CRC8H2F | `0xD4`, `0xAC` | ✔ | ✔ | ✔ |
| XOR | `0x91`, `0x02`, `0xAA` | ✔ | ✔ | ✔ |

Via the verified MLB rule `seed = (addr>>8) ^ (addr&0xFF)`: XOR `0x02` → **0x103 ESP_03**,
`0xAA` → **0x101 ESP_02** (a known magic Startwert). `0x91` → `0x190` or `0x091`. CRC data IDs do
not follow the rule.

**RX is where the family diverges:**

| image | CRC8H2F | XOR seeds |
|---|---|---|
| `0190` (oldest) | `0xF5` | `0x10`, `0x82`, `0x1A`, **`0x8B`** — 4 frames |
| `AD` (ESP9) | `0xF5` | `0x10`, `0x82`, `0x1A`, **`0xC3` (DLC 4)**, **`0x86`** — 5 frames |
| `0361` | (2 CRC TX wrappers) | 5 RX handlers, seeds not yet extracted |

So the ESP9 **dropped** the `0x8B` frame and **added** two (`0xC3`, the only DLC-4 protected frame,
and `0x86`). The protected TX set never changed.

## 4. Two different CAN architectures

| | Q5 `8R0907379BG` (ESP8) | C7 family (ESP-Premium and ESP9) |
|---|---|---|
| dispatch | flat u32 CAN-id array `0xafae0` + `{u16 id, u16 ptr}` descriptors `0xb33cc`; TX scheduler `0x5bfc` → trampoline `0xa2428` → per-message pack handler | per-frame signal composer → shared E2E wrapper → checksum library |
| signal bit-work | `com_signal_compose 0x6b00`, one big table-driven function | generic `sig_pack` / `sig_unpack` primitives |
| E2E | CRC8H2F table present (`0xb4800`) but **no code reference found** — the checksum site is still unlocated | explicit 5-function library, per-frame wrappers |
| interrupts | different scheme | vectored controller, source byte `0xFFFFFE03` |

**Open item:** the Q5's checksum computation site. Its bus frames definitely carry MLB XOR
checksums (verified on-car), and the image contains the CRC8H2F table, but neither a literal
pointer to that table nor an E2E-library-shaped function has been found. The likely explanation is
that the ESP8 computes the seed from the CAN id (`hi^lo`) inside the table-driven composer instead
of hardcoding per-frame constants — which would also explain why the magic-Startwert immediates
(`0xAB`, `0xAA`) appear nowhere near CAN code in that image. Not yet proven.

## 5. Handled CAN ids vs the DBC

Full cross-reference: `../analysis/can_id_vs_dbc.csv`. Each ECU's id table was extracted from its
message-handle array (Q5: u32 @`0xaf91c`, 248 entries; C7: u16 runs of 200–234 entries).

⚠ **These tables are not pure CAN-id lists.** Only ~12–18 % of their entries match a DBC message;
the rest are low values (`0x07`–`0x90`) that are not MLB frame ids — internal handles, or ids on
another bus segment. Read the table below as "which known MLB frames each ECU references", not as
a complete bus matrix.

32 DBC-known frames appear in at least one image:

| id | DBC name | ESP8 Q5 | 0190 | 0361 | ESP9 AD |
|---|---|---|---|---|---|
| 0x40 | Airbag_01 | ✔ | ✔ | ✔ | ✔ |
| 0x80 | Motor_01 | ✔ | | | |
| 0x81 | Motor_02 | ✔ | ✔ | | |
| 0x82/0x83 | Getriebe_01/02 | ✔ | ✔ | ✔ | |
| 0x84 | ESP_06 | | ✔ | ✔ | ✔ |
| 0x85 | SCU_01 | ✔ | ✔ | ✔ | |
| 0x86 | LWI_01 | ✔ | ✔ | ✔ | |
| 0x9f | LH_EPS_03 | | ✔ | ✔ | |
| 0x100/0x101 | ESP_01 / ESP_02 | ✔ | | | ✔ |
| 0x102 | Getriebe_03 | ✔ | ✔ | | ✔ |
| 0x103 | ESP_03 | ✔ | ✔ | ✔ | ✔ |
| 0x104 | EPB_01 | ✔ | ✔ | ✔ | ✔ |
| 0x105 | Motor_03 | ✔ | ✔ | ✔ | ✔ |
| **0x106** | **ESP_05** | ✔ | ✔ | ✔ | ✔ |
| 0x107 | Motor_04 | ✔ | ✔ | ✔ | ✔ |
| **0x109** | **ACC_01** | ✔ | ✔ | ✔ | ✔ |
| 0x10a | TSK_01 | ✔ | ✔ | ✔ | ✔ |
| 0x10b | LS_01 | ✔ | ✔ | ✔ | |
| 0x10c | TSK_02 | ✔ | ✔ | ✔ | |
| **0x10d** | **ACC_05** | ✔ | ✔ | ✔ | |
| 0x10e | TSK_04 | ✔ | ✔ | ✔ | |
| 0x111 | TSK_05 | ✔ | ✔ | ✔ | ✔ |
| 0x114 | Motor_10 | ✔ | | ✔ | ✔ |
| **0x117** | **ACC_10** | | | | **✔** |
| 0x11d | LH_EPS_02 | | | | **✔** |
| 0x11e | ESP_08 | | | | **✔** |
| 0x126 | HCA_01 | ✔ | | | |
| 0x1e1/0x1e8 | CCP_MOS_CRO_01 / CCP_MO_DTO_01 | ✔ | | | |
| 0x21e | TPS_SCU | ✔ | | | |

Points worth noting:

- **The ACC/brake core is common to all four**: ESP_05 (0x106), ACC_01 (0x109), EPB_01 (0x104),
  Motor_03/04, TSK_01. Whatever differs about stop&go, it is not the frame set at this level.
- ~~Only the ESP9 references ACC_10 (0x117), LH_EPS_02 (0x11d) and ESP_08 (0x11e).~~
  **RETRACTED 2026-08-20.** Wrong — an artifact of reading only ONE of the Q5's message tables
  (`can_id_array` @0xafae0, which happens to exclude 0x117). The Q5 ESP8 **does** reference
  ACC_10, LH_EPS_02, ESP_08 and LH_EPS_03: they live in a second 223-record configuration table
  at `0xa9fc0` (ACC_10 = record #13, state RAM 0x404588) plus two further id lists
  (`0xb1b82`, `0xb2370`). Counting all four tables, the Q5 references **31** DBC frames, not 27.
  This matches the on-car result that the B8 Q5 responds to ACC_10. `0x117` also occurs in all
  three C7 images. **The per-image counts in the table below are single-table lower bounds and
  must not be read as "this ECU does not handle frame X".**
- **Only the Q5 ESP8 references the CCP frames** (`0x1e1`, `0x1e8`) — i.e. the B8 ESP carries a CCP
  calibration channel the C7 images do not. Relevant to the earlier CCP work (see the
  `ccp-gateway-only` finding, which concerned the TCU, not this ECU).
- The ESP9's table lacks TSK_02/ACC_05/TSK_04/LS_01, which every older image has. Given the ESP9
  table is the shortest (200 vs 234–248) and ~38 % of that image is encrypted, treat this as
  "not found in the analysable part", not as proof of removal.
