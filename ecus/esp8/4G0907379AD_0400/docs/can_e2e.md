# 4G0907379AD (ESP9) — how CAN frames are received and sent

Traced 2026-08-20 in `ghidra_proj` (`ARM:BE:32:v7`, **load base 0x18000**, RAM 0x08000000).
All addresses are load addresses. Names/comments are in `../symbols.csv` (`source=re-trace`).

## 0. Prerequisites that were wrong at first — fix these before reading anything

- **Load base is `0x18000`, not `0x0`.** Proof: the IRQ handler table at `0x133ff8` resolves
  24/24 entries to code only under this base (with a default handler repeated in 14 unused slots),
  and the header at file+0x20 names `0x1ffee0` / `0x1ffef0`, which are the padding end and the
  signature block — file `0x1e7ee0` / `0x1e7ef0`. So base = `0x200000 − 0x1e8000` = `0x18000`.
  Imported at 0 the tables read as noise and the analysis is worthless.
- **The image is only ~62 % analysable.** `0x147000–0x200000` (~756 KB) sits at entropy
  7.99–8.00 — encrypted or compressed, not code. A second opaque region is `0x18040–0x19f00`.
  Everything below is from the plaintext region `0x1a000–0x147000`.
- ARMv7 + Thumb-2 (3357 MOVW/MOVT vs 30 in the Q5), with an ARM outer layer for vectors and
  IRQ entry. 3310 functions recovered (auto-analysis + `EspThumbSweep2`).

## 1. Interrupt plumbing

```
vectors@0x18000 ──IRQ(0x18)──> irq_handler 0x100834      (MSR CPSR_c mode switch, save state)
                                    └─> irq_dispatch 0x102f90
                                          src = *(u8*)0xFFFFFE03            (controller @0xFFFFFE04)
                                          *(u16*)(0xFFFFFE04+0x3e) = irq_prio_table[src]   @0x136594
                                          irq_handler_table[src]()                          @0x133ff8
```

Every category-2 ISR is an OS-wrapped stub — `os_isr_enter(0x10d7a0)` / body / `os_isr_exit(0x10d7de)`
around a nesting counter. That is an **AUTOSAR/OSEK OS**, which the Q5's ESP8 image does not show.

## 2. The E2E library — 5 functions, self-contained at `0x118038–0x1180b2`

| addr | what |
|---|---|
| `0x118038` | `e2e_xor_checksum(buf, len, _, _, seed)` → `chk = seed; for i in 1..len-1: chk ^= buf[i]` |
| `0x118064` | `e2e_crc8h2f(buf, len, _, _, dataID)` → `crc=0xFF; for i in 1..len-1: crc = tab[crc^buf[i]]; return ~tab[crc^dataID]` (table `0x134304`, copy at `0x134404`) |
| `0x118096` | `e2e_verify_xor` — recompute, compare against byte 0 |
| `0x1180b2` | `e2e_verify_crc8h2f` — same, CRC flavour |
| `0x118058` | thin wrapper on the XOR routine |

Both algorithms **skip byte 0** (the checksum byte) and fold a **per-frame constant** in last.
The XOR one is exactly the VAG MLB checksum we verified on the Q5 bus; the CRC one is AUTOSAR
CRC8H2F. Both verifiers have the same quirk: they write the *computed* value back into byte 0
before returning the match flag.

Bit handling is done by two generic primitives, not per-signal code:
`sig_pack(0x10129c)` / `sig_unpack(0x10138a)`, both `(buf, value, startBit, bitLen, msbFirstFlag, frameLen)`.

## 3. Sending

```
com_pack_frame_* (e.g. 0x6b7ac, 0x6b5f6)
   │  per signal: pick live value or replacement value on a status byte's bit 7
   │              (AUTOSAR COM invalid/substitute), write via read-modify-write into
   │              a double-buffered frame buffer (+0xe8 / +0x174)
   └─> e2e_tx_* wrapper:
         ctr = e2e_counter_next(state)          ; per-frame counter byte
         sig_pack(frame, ctr, startBit=8,  len=4, 1, 8)     ; byte1 low nibble
         chk = <xor|crc8h2f>(frame, 8, seed)
         sig_pack(frame, chk, startBit=0,  len=8, 1, 8)     ; byte0
```

Five TX-protected frames exist in the plaintext region:

| wrapper | algorithm | seed / data ID | back-solved id (MLB rule `hi^lo`) |
|---|---|---|---|
| `0x106494` | CRC8H2F | `0xD4` | n/a — CRC data IDs don't follow the XOR rule |
| `0x1064d6` | CRC8H2F | `0xAC` | n/a |
| `0x10651a` | XOR | `0x91` | `0x190` (or `0x091`) |
| `0x106562` | XOR | `0x02` | **`0x103` = ESP_03** |
| `0x1065a6` | XOR | `0xAA` | **`0x101` = ESP_02** (known magic Startwert) |

## 4. Receiving

```
e2e_rx_* (0xd842a, 0xd82a4, 0xd8508, 0xd85c8, 0xd8694, 0xd8764)
   sig_unpack(frame, 0, 8)                      ; byte0 = received checksum
   ok = e2e_verify_<xor|crc8h2f>(frame, len, seed)
   if (!ok)      status |= 0x04                 ; checksum error
   else {
        ctr = sig_unpack(frame, startBit=8, len=4)
        if (!e2e_counter_check(ctr, expected))  status |= 0x08   ; counter/sequence error
   }
   (*callback)(...)                              ; notify the application either way
```

Six RX-protected frames:

| handler | algorithm | DLC | seed | back-solved id |
|---|---|---|---|---|
| `0xd842a` | CRC8H2F | 8 | `0xF5` | n/a |
| `0xd82a4` | XOR | 8 | `0x10` | `0x111` (or `0x010`) |
| `0xd8508` | XOR | **4** | `0xC3` | `0x1C2` (or `0x0C3`) |
| `0xd85c8` | XOR | 8 | `0x82` | `0x183` (or `0x082`) |
| `0xd8694` | XOR | 8 | `0x1A` | `0x11B` (or `0x01A`) |
| `0xd8764` | XOR | 8 | `0x86` | `0x187` (or `0x086`) |

The id back-solve uses the verified MLB rule `seed = (addr>>8) ^ (addr&0xFF)`; it is **ambiguous
between `hi=0` and `hi=1`** and is therefore a candidate, not a fact. `0x103`/`0x101` are called
out because they match independently-verified Q5 values.

## 5. Honest limits

- These 11 frames are **only the E2E-protected ones reachable from the two checksum primitives**
  in the plaintext region. Unprotected frames, and anything living in the encrypted `0x147000+`
  region, are not covered. Notably **ESP_05 (0x106, seed 0x07) does not appear here** — so either
  more packers exist outside the analysable region, or this ECU protects a different frame set.
  Do not read the table above as "the C7 ESP's complete CAN matrix".
- Frame ↔ CAN-id binding is inferred from seeds only. Pinning it properly needs the CAN driver's
  message-object configuration, which has not been located yet.
- The `0x113b8a–0x113d20` table (file offsets) contains runs of plausible ids (`0xf5–0x10a`,
  `0x115–0x11f`, …) mixed with descending index triples, so it reads more like a handle/priority
  map than a raw id list. Unresolved.
