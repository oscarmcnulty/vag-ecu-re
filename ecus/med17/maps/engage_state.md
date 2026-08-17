# ACC mode arbitration and the engage state machine (MED17.1.1)

Two distinct pieces of machinery, often conflated:

1. **`FUN_800accac`** decides *which longitudinal mode the car is in* — off / GRA / ACC / ACC-extended
   — and publishes it as `d000a3c1` → `d000a454`.
2. **`FUN_80143b8a`** (`ACC_engage_state_machine`) runs the actual engage/disengage sequence once the
   mode is ACC.

Neither contains a speed threshold. Tags: **[C]** read code/bytes · **[I]** inferred · **[G]** gap.

## 1. Mode arbitration — `FUN_800accac` [C]

Not bespoke ACC logic: a generic Bosch **state-vector engine** ("Zustandsautomat") that validates a
packed condition vector and latches each field into an output shadow.

1. **Build the condition vector** (`abStack_4c`, 52 bytes) by bit-unpacking a 10-byte mask via
   `FUN_800aba88` (a pure bit-splitter, e.g. `cond[0x1c] = (mask[5] >> 5) & 3`). The mask is the
   runtime vector `DAT_d0009b63` when it validates, else the flash coding default `DAT_803def94` —
   selected by `DAT_d000b9ae = FUN_800aca8c()`, a checksum/consistency check over the vector.
2. **Latch conditions → output shadows** via the decision table at
   `PTR_DAT_8003f374 = 0x80044772`, `DAT_8003f378 = 134` records of 4 bytes
   `{cond_idx, expected, out_idx, out_val}`: `if cond[cond_idx] == expected then out[out_idx] = out_val`.
   The 134 records are a near 1:1 copy of ~40 condition fields into the output shadows
   `DAT_d000a3bd..a3ec`.
3. `FUN_800abc46(&table, vector)` runs the same table as a sequenced state check
   (→ `DAT_d0008c34`, `DAT_d000791c`) — the validation/latch gate. It does not compute `a3c1`.

### The master ACC mode `a3c1`

`DAT_d000a3c1 = abStack_74[0x1b]`, and out_idx `0x1b` is produced by exactly four records — read
straight out of the table at `0x80044772`:

| record | bytes | condition | → `a3c1` | meaning |
|---|---|---|---|---|
| 94 | `1c 00 1b 00` | `cond[0x1c] == 0` | 0 | cruise/ACC off |
| 95 | `1c 01 1b 01` | `cond[0x1c] == 1` | 1 | **GRA** (basic cruise) |
| 96 | `1c 02 1b 02` | `cond[0x1c] == 2` | 2 | **ACC/DCC** |
| 97 | `1c 03 1b 03` | `cond[0x1c] == 3` | 3 | ACC extended |

So **`a3c1` is a pure pass-through of condition field `0x1c`**, a 2-bit "cruise mode" field.
`FUN_802c806e` then maps it to the output selector `d000a454` (1 → GRA path, 2/3 → ACC path).
`cond[0x1c]` is a pure *input*: no record writes out_idx `0x1c`.

### Where the mode field comes from [C mechanism / G source]

- **Runtime:** `cond[0x1c]` = bits 5-6 of byte 5 of `DAT_d0009b63`. That vector has no
  direct-assignment writer in the corpus — it is populated through computed pointers by the
  ACC-availability arbitration (driver ACC on/off plus system availability) and then checksum-validated
  by `FUN_800aca8c` (`FUN_800abcc8` hash vs `DAT_d0009b5a`). **Which upstream signals drive field
  `0x1c` to 2 is the open item.** **[G]**
- **Flash fallback in this image:** with `b9ae == 0` the vector is the coding block `DAT_803def94`,
  whose byte 5 is `0x26`, so `cond[0x1c] = (0x26>>5) & 3 = 1 = GRA`. The default/fallback mode on this
  bin is GRA; ACC (2) is asserted at runtime by the arbitration, not by the static coding.
  (`DAT_803def94` and `DAT_803ded00` are byte-identical here, so the coding-mask combine is
  idempotent.) **[C]**

### No speed floor here [C]

The 40 condition indices are abstract packed booleans. No speed variable and no calibration read
appears anywhere in `FUN_800accac` or in its decision table, and the conditions arrive pre-computed
through an OS mailbox (`FUN_800ad364` over `d0009b48`). Mode arbitration is exactly that — mode
arbitration.

## 2. The engage state machine — `FUN_80143b8a` [C]

A switch on `ACC_engage_state` (`0xd00049ec`) with states 0..6. Its guards:

| guard | meaning |
|---|---|
| `FUN_80143ade` | abort condition |
| `FUN_80143b0c` | enable-mode match against cal `PTR_DAT_8010384c + 0x35` |
| `FUN_80143b26` | abort request = `ACC_abort_request` (`0xd00049c9`) |
| **`FUN_80143b34`** | **low-speed block guard — three instructions returning `(0xd00049ca != 0)`** |

`FUN_80143b34` is consulted from four call sites (states 1, 3, 5, 6). While it returns non-zero it
**forces states 1 and 5 to state 2 and blocks both re-engage chains**; the default path then calls
`FUN_801439fc`, which zeroes `d0004936` and `d0004941`.

Disengage zeroes `d000a350` and `d000a362` in one transition, which is why both TSK request channels
rail simultaneously (`acc_flow.md` §5).

### What drives the block guard [C]

`0xd00049ca` bit 7 is fed by **`ESP_05` frame bit 36 `ESP_HDC_Standby`** through a debounced chain
(cal `0x803b50e6` = 6 on-delay, mask `0x803b50c1` = 0xFE). This is a genuine low-speed engage lock,
wired to hill-descent standby — which is **constant 0 on these vehicles**, so it never fires here.
The full chain is documented in **`ecd_relay.md`**; do not conflate it with the ECD relay that shares
the same source message.

## 3. What this means for openpilot

- **Neither mechanism imposes a speed floor.** The ~15 km/h floor is `ESP_05` bit 33
  `ECD_nicht_verfuegbar`, declared by the ESP/ABS (`ecd_relay.md`). The separate ECU-side constraint
  is the EGAS-L2 monitor cal #208 (`l2_monitors.md`), which is not part of this state machine either.
- **What openpilot does need** is for the car to be in ACC mode (`a454 == 2`) — driver ACC enabled and
  coded for ACC so the arbitration sets `cond[0x1c] = 2`. Inside that mode openpilot operates as ACC
  master; it does not need to defeat the decision table.
- **If the engage lock ever mattered** (a variant where `ESP_HDC_Standby` is live), its mask
  `0x803b50c1` = 0xFE and on-delay `0x803b50e6` = 6 are calibratable.

## Key addresses

- Mode arbitration: `FUN_800accac`; validator `FUN_800aca8c`; bit-splitter `FUN_800aba88`; table engine
  `FUN_800abc46` / `FUN_800ac32a`; hash `FUN_800abcc8`; coding loader `FUN_800ad364`.
- Decision table `0x80044772` (134 × 4 bytes `{cond_idx, expected, out_idx, out_val}`), count
  `DAT_8003f378`.
- Runtime condition vector `DAT_d0009b63` / flash coding default `DAT_803def94`; select `DAT_d000b9ae`.
- Master state `DAT_d000a3c1` (= `cond[0x1c]`) → `FUN_802c806e` → `DAT_d000a454`.
- Engage state machine `FUN_80143b8a`; state `0xd00049ec`; guards `FUN_80143ade` / `FUN_80143b0c` /
  `FUN_80143b26` / `FUN_80143b34`; teardown `FUN_801439fc`; block flags `0xd00049ca`.
