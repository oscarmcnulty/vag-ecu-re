# MED17.1.1 — the CAN layer (8R0907115N_0006)

How this ECU gets bits on and off the wire: the controller, the message table, the descriptor
formats, the bit-numbering convention, and the E2E protection. `acc_flow.md` sits on top of this;
`com_group_direction.md` is the per-message directory that falls out of it.

Load base `0x80000000`; `0xa00xxxxx` = uncached mirror; file offset = `addr & 0x1FFFFFFF`;
RAM = `0xd00xxxxx`. Confidence tags: **[C]** read the code/bytes · **[I]** inferred · **[G]** gap.

Everything below is reproduced by `core/maps/decode_can_table.py`:

```bash
python3 core/maps/decode_can_table.py ecus/med17/firmware/8R0907115N_0006.bin --csv /tmp/can_map.csv
# 107 messages, 970 bindings
```

## The controller: TC1797 internal MultiCAN [C]

There is **no external CAN companion chip.** Frames are moved by the TriCore's own MultiCAN
module. The init routine `FUN_800a3ae4` writes `CAN_CLC`, `CAN_PANCTR`, `CAN_NBTR0`, `CAN_NECNT0`,
`CAN_NIPR0`, `CAN_NSR0`, `CAN_SRC1/2/5`, `CAN_MSIMASK` and `CAN_NCR0`, and the message-object
registers live at **`0xF0005000 + MO*0x20`** (`MOFCR +0x00`, `MOIPR +0x08`, `MOAMR +0x0c`,
`MODATAL/H +0x10/+0x14`, `MOAR +0x18`, `MOCTR +0x1c`).

`MLI0` *is* driven (`FUN_8009319e` / `FUN_80093318`, `MLI0_TP0BAR/TRSTATR/TCBAR/RDATAR`) but it
carries no CAN payload — nothing in the CAN path touches it. **[I]** it is an inter-processor link.

### MO configuration table `0x8003e640 .. 0x8003f270` — 130 records × `0x18` [C]

Record 0 is a header; records 1..129 are the configured message objects. The driver indexes the table
from `DAT_d0007314 = 0x8003e654`, i.e. as `0x8003e654 + msgidx*0x18` with `msgidx = record − 1`;
addresses below are given from the **record start** `0x8003e640 + record*0x18`.

| offset (from record start) | field |
|---|---|
| `+0x00` | **pointer to** the 32-bit CAN identifier |
| `+0x04` | acceptance mask (`0x7ff` standard, `0x1fffffff` extended) |
| `+0x08` | extended-identifier flag (1 = 29-bit) — selects `MOAR = id` + IDE over `MOAR = id<<18` |
| `+0x09` | **direction: 1 = TX, 2 = RX** |
| `+0x0e` | interrupt-enable flag |
| `+0x10` | per-MO callback |
| `+0x14` | u16 record index (high half carries flags) |

Counts: **129 configured objects — 126 on node 0 (52 TX / 74 RX) plus three extended-identifier TX
objects `0x1BFC0C00`, `0x1BFC0C01`, `0x1BFC0C03` on node 1.** (A fourth extended id `0x1BFC0C02`
sits in the identifier pool at `0x80027fc0` but no record references it in this image.)

`MOAR = id << 18` is proved in both directions: the transmit setup `FUN_800a3798` writes
`MOAR = (MOAR & 0xe003ffff) | id*0x40000`, and the receive reader `FUN_800a393c` recovers
`id = (MOAR & 0x1fffffff) >> 0x12` unless the extended bit `0x20000000` is set. The MO number for a
message index is assigned at init and stored in `DAT_d000b814[msgidx]`.

> ### Hazard: `0x80027fd4` is not `id_table[MO]` [C]
> The identifiers live in a **pointer-addressed constant pool** at `0x80027fc0..0x800281b4`, and the
> `+0x00` pointers *descend* as the record index ascends. Reading that pool as a flat array indexed by
> MO number therefore reverses the mapping and yields wrong MO numbers for every message — e.g. it
> makes `0x106` look like MO 52 when it is record 71. Always dereference `record+0x00`.

Selected records:

| CAN id | msg | record | dir | | CAN id | msg | record | dir |
|---|---|---|---|---|---|---|---|---|
| `0x100` | ESP_01 | 30 | RX | | `0x10a` | TSK_01 | 54 | **TX** |
| `0x102` | Getriebe_03 | 42 | RX | | `0x10c` | TSK_02 | 55 | **TX** |
| `0x106` | **ESP_05** | **71** | RX | | `0x10e` | TSK_04 | 56 | **TX** |
| `0x109` | ACC_01 | 64 | RX | | `0x111` | TSK_05 | 57 | **TX** |
| `0x10d` | ACC_05 | 65 | RX | | `0x10b` | LS_01 | 47 | RX |

## The COM message table `0x80030c38 .. 0x80032168` — 113 records × `0x30` [C]

This is the table that says which signals belong to which message. **111 records carry a valid
11-bit identifier** (two are variant-disabled and hold `0xffffffff`), covering **107 distinct CAN
ids** — `0x092` and `0x560` each appear twice.

| offset | field |
|---|---|
| `+0x00` | u8 — the record's own index |
| `+0x01` | u8 **`n_bool`** — number of boolean descriptors owned by this record |
| `+0x02` | u8 **`n_sig`** — number of signal-block entries owned by this record |
| `+0x03` | u8 extraction mode (0 everywhere here = the inline LSB-first path) |
| `+0x04` | → first **boolean descriptor** (20-byte records, contiguous, `n_bool` of them) |
| `+0x08` | → **signal block** (12-byte entries, `n_sig` of them) |
| `+0x0c` | u32 **CAN identifier** (`0xffffffff` = variant-disabled) |
| `+0x10` | → expected DLC. Every record points into the descending byte table at `0x80029652` (`8,7,6,…`); all of them at the `8` entry |
| `+0x14` / `+0x18` / `+0x1c` | → error-status records `{→u16 signal handle, →u32 timestamp}` for timeout / checksum / counter |
| `+0x20` | → per-message callback (`0x800b9250` across the TSK TX set, `0x80089c22` on ESP_01) |
| `+0x24` | → 8-byte raw-frame snapshot buffer (RX only; 0 if the message keeps no snapshot) |
| `+0x28` | → counter-indexed checksum-seed table (0 = derive the seed from the identifier) |
| `+0x2c` | u16 **index into the MO configuration table** — the link to the hardware |

**Signal block entry** (`0x0c` stride): `+0x00` points at **descriptor + 0x18**, straight at the
descriptor's `target` field, not at the record start. Subtract `0x18` to get the record.

**40-byte signal descriptor** — `+0x18` RAM target, `+0x1c` start_bit, `+0x1d` bit_len, `+0x1e` type.
The 580 owned descriptors form an almost perfectly contiguous `0x28`-stride array,
`0x80035d10 .. 0x8003b8a0` (578 of the 579 gaps are exactly `0x28`; one 8-slot hole).

**20-byte boolean descriptor** — `+0x00` RAM target, `+0x04` = `0xffff | (destBit << 8) | srcBit`,
where `srcBit` is the **frame** bit and `destBit` selects the bit inside the target
(`byte = destBit>>3`, `bit = destBit&7`). The 390 owned records form a `0x14`-stride array,
`0x80033d48 .. 0x80035c24`, with one 7-slot hole.

Totals: **970 bindings = 580 signals + 390 booleans.**

### Self-checks

- `n_bool`/`n_sig` are explicit fields, so the decoded runs must match the declared counts — they do,
  for all 113 records.
- Joined against `vw_mlb.dbc`, **522 of 548 bindings on messages the DBC knows land on an exact
  `start_bit|bit_len` match — 95.3%.** ESP_05, ESP_01, ACC_01, ACC_05, TSK_04, TSK_05 and
  Getriebe_03 match 100%. Random or misaligned decoding does not do that.

## Bit numbering is LSB-first / Intel, everywhere [C]

> frame bit *n* = payload byte `n>>3`, bit `n&7`. A signal of length *L* at start_bit *S* occupies
> frame bits *S..S+L-1*, with value bit *k* at frame bit *S+k*. **There is no MSB-first path.**

Proved on both sides:

- **TX assembler `FUN_8008a3f8`** (`0x8008a6be-0x8008a706`) builds a 64-bit `frame`, OR-ing in
  `(v & ((1<<len)-1)) << start_bit` per signal — with a second branch that shifts into the high word
  once `start_bit >= 32` — and stores it with `st.d` on a little-endian core.
- **RX extractor `FUN_80089dac`** (`0x80089dc6-0x80089dec`) computes `byte = start_bit>>3`,
  `bit = start_bit&7` and masks with `(1<<bit_len)-1`.
- **RX distributor `FUN_8008a75e`** does the same for every signal in the block, and for booleans
  sets or clears bit `destBit&7` of `target[destBit>>3]` from frame bit `srcBit`.

## The two ends of the pipe [C]

**RX** — `FUN_8008a75e(record_index)`: pull the frame with `FUN_800a393c` using the record's `+0x2c`
MO index, run the `+0x20` callback, then walk the signal block (extract → range-check against the
descriptor's limit/SNA pointers → store by type into the RAM target) and the boolean list. Callers
`FUN_80088daa` / `FUN_80088e74`. On timeout or a failed E2E check the substitution path
`FUN_8008b17c` (`COM_rx_default_substitution`) writes the message's targets instead.

**TX** — `FUN_8008a3f8(record_index)`: walk booleans then signals, OR each into the 64-bit frame,
compute the checksum, then `FUN_800a3848` → `FUN_800a3798` → MultiCAN MO. The application deposits
values through `FUN_8009d0ca(handle, value, …)` (dispatch by `handle>>12` via `PTR_FUN_8003e0d8`;
signal class → `FUN_800bffba`).

Both directions gate each signal on `DSM_get_event_status(path)` — the descriptor carries a pointer
to its DSM path id, and a released path selects the live value while a set one selects the
descriptor's default. Note the polarity: **`0` = fine, non-zero = degraded.**

## E2E: alive counter + checksum — mechanism and sites pinned [C]

Both live in `FUN_8008a75e` / `FUN_8008a3f8`, selected by the descriptor's **type** byte:

| type | meaning |
|---|---|
| 6 | **alive counter** — stores the value, compares against the previous one modulo `1<<bit_len`, and counts mismatches against the two thresholds in the descriptor |
| 7 / 9 | **XOR checksum** over all 8 payload bytes; type 9 additionally folds in the identifier: `((id>>8) & 7) ^ ((xor ^ id) & 0xff)` |
| 8 | byte-sum checksum with identifier fold and a nibble-fold tail |
| 10 / 11 | delegated to `FUN_80089f9e` / `FUN_8008a098` |

Every message in the ACC/TSK/ESP set uses **type 9**, so the effective per-id seed is
`(id>>8) ^ (id&0xff)` — ACC_01 `0x109` → `0x08`, ESP_05 `0x106` → `0x07`, TSK_01 `0x10a` → `0x0b`,
TSK_02 `0x10c` → `0x0d`, TSK_04 `0x10e` → `0x0f`. Matches the verified seeds in the
`vw-mlb-checksums` note.

`FUN_80089e00` is a separate table-driven CRC8 (nibble tables `0x800454e7`/`0x800454f7`) used by the
type-10 path; it takes its seed either from the identifier or, when the record's `+0x28` pointer is
set, from a counter-indexed table (ESP_05 → `0x800304f8` → `0x800454b7`).

## Raw-frame snapshots and the monitor-path speed decode [C]

Thirteen RX messages keep a verbatim 8-byte copy of the last frame, addressed by record `+0x24`
(`0xd0009a9c .. 0xd0009b1c`). `FUN_800a3f76` mirrors all thirteen into a second contiguous block
based at **`0xd0009a2c`**, and the EGAS-L2 side reads *that* block rather than the COM shadows:
`FUN_8005e822` and `FUN_80050a04` rebuild `byte4 | byte5<<8` from `0xd0009a30/31` — ESP_01 frame
bits 32..47, i.e. **`ESP_v_Signal` decoded a second time, independently of
`comsig_d0008608_b32l16`.** That is the redundancy the Level-2 monitor path is built on.

Mirror order: `0xd0009a2c`←`0x100`, `a34`←`0x082`, `a3c`←`0x083`, `a44`←`0x10b`, `a4c`←`0x109`,
`a54`←`0x106`, `a5c`←`0x105`, `a64`←`0x3c0`, `a74`←`0x102`, `a84`←`0x098`, `a8c`←`0x0a9`,
`a94`←`0x0a5`.

## The messages that matter, fully decoded [C]

DBC names from `vw_mlb.dbc`; `bool` rows are 20-byte boolean descriptors, `sig` rows are 40-byte
signal descriptors. `target` is the RAM byte/word the COM layer reads or writes.

### ESP_05 `0x106` — RX, record 71, MO config 70 · 25/25 DBC match

| kind | descriptor | target | bits | signal |
|---|---|---|---|---|
| sig | `0x80038650` | `0xd000a4a2` | 0\|8 | CHECKSUM |
| sig | `0x80038628` | `0xd000a50b` | 8\|4 | COUNTER |
| bool | `0x800346e4` | `0xd000ab77` b0 | 12\|1 | ESP_QBit_Bremsdruck |
| bool | `0x800346f8` | `0xd000ab42` b7 | 13\|1 | ESP_QBit_Fahrer_bremst |
| sig | `0x80038600` | `0xd000ab33` | 14\|2 | ESP_Schwelle_Unterdruck |
| sig | `0x800385d8` | `0xd0008dd4` | 16\|10 | ESP_Bremsdruck |
| bool | `0x8003470c` | `0xd000ab42` b3 | 26\|1 | ESP_Fahrer_bremst |
| bool | `0x80034720` | `0xd000ab42` b0 | 27\|1 | ESP_Verz_TSK_aktiv |
| bool | `0x80034734` | `0xd000ab2c` b0 | 28\|1 | ESP_Lenkeingriff_ADS |
| bool | `0x80034748` | `0xd000ab42` b4 | 29\|1 | ESP_Konsistenz_TSK |
| bool | `0x8003475c` | `0xd000ab2f` b0 | 30\|1 | ESP_Bremsruck_AWV2 |
| bool | `0x80034770` | `0xd000ab42` b6 | 32\|1 | ECD_Fehler |
| **bool** | **`0x80034784`** | **`0xd000ab42` b5** | **33\|1** | **ECD_nicht_verfuegbar** |
| bool | `0x80034798` | `0xd000ab42` b1 | 34\|1 | ESP_Status_Bremsentemp |
| bool | `0x800347ac` | `0xd000ab6a` b0 | 36\|1 | ESP_HDC_Standby |
| bool | `0x800347c0` | `0xd000ab79` b0 | 38\|1 | ESP_Prefill_ausgeloest |
| bool | `0x800347d4` | `0xd000ab7c` b0 | 39\|1 | ESP_Rueckwaertsfahrt_erkannt |
| bool | `0x800347e8` | `0xd000ab41` b0 | 40\|1 | ESP_Status_Anfahrhilfe |
| sig | `0x800385b0` | `0xd000ab34` | 42\|2 | ESP_StartStopp_Info |
| sig | `0x80038588` | `0xd0008dd2` | 48\|8 | ESP_BKV_Unterdruck |
| bool | `0x800347fc` | `0xd000ab6f` b0 | 56\|1 | ESP_Autohold_aktiv |
| bool | `0x80034810` | `0xd000ab41` b1 | 57\|1 | ESP_FStatus_Anfahrhilfe |
| bool | `0x80034824` | `0xd000a61d` b0 | 58\|1 | ESP_Verz_EPB_aktiv |
| bool | `0x80034838` | `0xd000a60b` b0 | 59\|1 | ECD_Bremslicht |
| bool | `0x8003484c` | `0xd000ab42` b2 | 61\|1 | ESP_Status_Bremsdruck |

`0xd000ab42` is the ESP brake/ECD status byte: eight ESP_05 bits packed into one byte. **Frame bit 33
`ECD_nicht_verfuegbar` → bit 5 is the origin of the whole ACC low-speed floor — see
`ecd_relay.md`.** `ESP_Verzoeg_EPB_verf` (60\|1) is not bound here.

### ACC_01 `0x109` — RX, record 64 · 11/11 DBC match

| kind | descriptor | target | bits | signal |
|---|---|---|---|---|
| sig | `0x80038c18` | `0xd000a465` | 0\|8 | CHECKSUM |
| sig | `0x80038bf0` | `0xd000a4e3` | 8\|4 | COUNTER |
| sig | `0x80038bc8` | `0xd00084ae` | 16\|6 | ACC_zul_Regelabw_unten |
| sig | `0x80038ba0` | `0xd00084aa` | 24\|11 | **ACC_Sollbeschleunigung** |
| sig | `0x80038b78` | `0xd00084b0` | 35\|5 | ACC_zul_Regelabw_oben |
| sig | `0x80038b50` | `0xd00084be` | 40\|8 | ACC_neg_Sollbeschl_Grad |
| sig | `0x80038b28` | `0xd00084c0` | 48\|8 | ACC_pos_Sollbeschl_Grad |
| **bool** | **`0x80034a04`** | **`0xd000a59b` b0** | **57\|1** | **ACC_Anhalten** |
| sig | `0x80038b00` | `0xd000a595` | 58\|2 | ACC_Dynamik |
| sig | `0x80038ad8` | `0xd000a590` | 60\|3 | **ACC_Status_ACC** |
| bool | `0x80034a18` | `0xd000a592` b0 | 63\|1 | ACC_Minimale_Bremsung |

ACC_01 carries no `ACC_Anfahren` binding in this image (DBC 56\|1 is unbound).

### ACC_05 `0x10d` — RX, record 65 · 9/9 DBC match

`0xd000a590` (57\|3, `ACC_Status_ACC`) and `0xd000a59b` (62\|1, `ACC_Anhalten`) are the **same two RAM
bytes ACC_01 writes** — the platform variant that sends the ACC command on `0x10d` lands on the same
shadows. Also: `0x800349b4` → `0xd000a598` b0 (12\|1 `ACC_Freigabe_Momentenanf`), `0x800349c8` →
`0xd000a5fe` (15\|1), `0x80038ab0` → `0xd0008588` (16\|10 `ACC_Momentenanforderung`), `0x80038a88` →
`0xd000a59d` (44\|2 `ACC_StartStopp_Info`), `0x800349dc` → `0xd000a596` (60\|1 `ACC_Betaetigung_EPB`).

### TSK_02 `0x10c` — TX, record 55 · 12 bindings

| kind | descriptor | target | bits | signal |
|---|---|---|---|---|
| sig | `0x800392a8` | `0xd000a4d8` | 0\|8 | CHECKSUM |
| sig | `0x800392d0` | `0xd000a545` | 8\|4 | COUNTER |
| **bool** | **`0x80034b58`** | **`0xd000a33d` b0** | **12\|1** | **TSK_Anhalten** |
| sig | `0x80039370` | `0xd000ab01` | 16\|2 | TSK_Status |
| sig | `0x80039348` | `0xd00082e6` | 18\|5 | (Fahrzeugmasse, shared with TSK_05) |
| bool | `0x80034b6c` | `0xd000a358` b0 | 23\|1 | (QBit) |
| **sig** | **`0x80039320`** | **`0xd0005de0`** | **40\|12** | **TSK_Radbremsmom** |
| bool | `0x80034b80` | `0xd000a968` b0 | 52\|1 | TSK_Standby_Anf_ESP |
| bool | `0x80034b94` | `0xd000a33f` b0 | 53\|1 | (Codierung_ACC) |
| bool | `0x80034ba8` | `0xd000a345` b0 | 54\|1 | (Zwangszusch_ESP) |
| bool | `0x80034bbc` | `0xd000a968` b1 | 55\|1 | (Freig_Verzoeg_Anf) |
| **sig** | **`0x800392f8`** | **`0xd0008d5a`** | **56\|8** | **TSK_Verzoeg_Anf** |

> `TSK_Verzoeg_Anf` is `0xd0008d5a` and `TSK_Radbremsmom` is `0xd0005de0`. Names in parentheses are
> taken from TSK_05, which binds the same RAM bytes at the same geometry; the DBC's TSK_02 variant
> does not list them.

### TSK_04 `0x10e` — TX, record 56 · 8/8 DBC match

`0x800391b8`→`0xd000a4da` (0\|8), `0x800391e0`→`0xd000a549` (8\|4), `0x80039280`→`0xd00082ce`
(12\|6 `TSK_zul_Regelabw`), `0x80039258`→`0xd00082b6` (18\|9 **`TSK_ax_Getriebe`**),
`0x80039230`→`0xd00082fc` (27\|10 `TSK_Wunsch_Uebersetz`), `0x80034b30`→`0xd000a720` b0
(37\|1 `TSK_Freig_WU`), `0x80034b44`→`0xd000aac0` b0 (38\|1 `TSK_Limiter_aktiv`),
`0x80039208`→`0xd000ab01` (62\|2 **`TSK_Status_GRA_ACC_02`**).

### TSK_01 `0x10a` — TX, record 54

`0x80039398`→`0xd000a4d7` (0\|8), `0x800393c0`→`0xd000a543` (8\|4), `0x80034bd0`→`0xd000a35d` b0
(12\|1), `0x80039460`→**`0xd0005e34`** (16\|24 **`TSK_Status_AB`**), `0x80039438`→`0xd00082fa` (40\|8),
`0x80039410`→`0xd0008ec0` (48\|9 `TSK_amax_moeglich`), `0x800393e8`→`0xd000a759` (57\|2).

`TSK_Status_AB` bit 7 of `0xd0005e34` is TSK_01 frame bit 23 — the ECD relay's exit onto the wire.
Full chain in `ecd_relay.md`.

### ESP_01 `0x100` — RX, record 30 · 18/18 DBC match

The vehicle-speed source: `0x8003a770` → **`0xd0008608`**, 32\|16, `ESP_v_Signal`, **0.01 km/h**.
Also `0x8003a7c0`→`0xd00085d4` (12\|10), `0x8003a798`→`0xd00085d2` (22\|10), and eleven booleans
(`ASR_Tastung_passiv` … `ESP_ASP`) into `0xd0008c7e`, `0xd000a78f`, `0xd000a78a`, `0xd000a625`,
`0xd000a5ae`.

### Getriebe_03 `0x102` — RX, record 42 · 10/10 DBC match

`0x80039c08` → **`0xd000a6c3`**, 44\|4, **`GE_Waehlhebel`** — the gear-selector position that the
EGAS-L2 `dc8b` term reads (`l2_monitors.md`).

## Quick reference

- MultiCAN init `FUN_800a3ae4` · MO TX `FUN_800a3798` · MO RX `FUN_800a393c` · MO→DMA `FUN_800a347a`
- MO config table `0x8003e640` (130×`0x18`) · id pool `0x80027fc0..0x800281b4` · MO number map `DAT_d000b814[msgidx]`
- COM message table `0x80030c38` (113×`0x30`, runtime pointer `DAT_d0006630`)
- signal descriptors `0x80035d10..0x8003b8a0` (`0x28`) · boolean descriptors `0x80033d48..0x80035c24` (`0x14`)
- RX distributor `FUN_8008a75e` · TX assembler `FUN_8008a3f8` · counter/checksum extractor `FUN_80089dac` · CRC8 `FUN_80089e00`
- set-signal `FUN_8009d0ca` → `PTR_FUN_8003e0d8` → `FUN_800bffba` · RX default substitution `FUN_8008b17c`
- DSM event status `FUN_800981cc` (threshold `DAT_80027f88`=23; arrays `d000b083` bit `0x40` / `d000b117` bit `0x20`)
- raw-frame snapshots `0xd0009a9c..0xd0009b1c`, mirrored to `0xd0009a2c` by `FUN_800a3f76`

## Gaps

- The `+0x00` byte-0 flags and `+0x03` extraction mode are decoded but their variant meanings are not
  exercised in this image. **[G]**
- Node membership is built into RAM at init (`DAT_d000c66c` per-node index lists), so the node→MO
  assignment is only inferable from the extended-identifier split. **[I]**
- Cyclic TX period: the producers run from an OS function-pointer task table with no in-corpus
  callers, so the period is not statically recoverable. **[G]**
