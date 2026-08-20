# Where Simos 8.5 keeps its coding — and what every coding bit reaches

Target: `8R0907551F_Original.bin` (Audi Q5 8R 3.0 TFSI, CTUC, Simos 8.5, TC1796).

**Short answer.** The engine ECU's *Codierung* is a **10-byte long-coding block**. It is not in
the calibration region and not in the program flash the tuner touches: it lives in the
**EEPROM-emulation area** as two redundant records, is mirrored into RAM at boot, and is
unpacked into **49 coding cells** that fan out to ~60 RAM flags the application reads. The
calibration region holds only the *factory default* coding and the *rules* that decide which
cells a tester is allowed to change.

Everything below is read out of the image. Where a claim is an inference it says so.

---

## 1. The diagnostic surface — `$22`/`$2E` DID `0x0600`

| DID | length | direction | target | what it is |
|---|---|---|---|---|
| **`0x0600`** | **10 (variable)** | read | `0x8011ff20` → copies `d000b3a6` | **the coding value** |
| `0x0601` | 1 | read | `0x8011ff3c` → constant `10` | the coding **length** in bytes |
| `0xF198` | 6 | write | `d000d42a` | repair-shop / tester code, **required before coding** |

### 1a. Correction: the DID-table record layout was off by one field

The DID tables are 12-byte records **`{handler:u32, did:u16, length:u16, flags:u32}`** — the
handler comes *first*. Reading them as `{did, length, flags, handler}` (the natural-looking
order) pairs every DID with the previous row's handler and quietly produces wrong answers; it
is what makes `0x0600` look like it returns a single byte.

The corrected layout is verified, not assumed — under it **every declared length matches what
its handler actually emits**, across 30+ records, and the `flags` byte becomes meaningful:

| flags byte | meaning | check |
|---|---|---|
| `0x02` | target is a **data pointer**, fixed length | every `0x02` row points at RAM or cal |
| `0x03` | `handler(buf)` emits exactly `length` bytes | e.g. `0xF1A2` len 6 → `0x801203fc` emits 6 |
| `0x04` | `handler(buf, emit)` **returns** the length | e.g. `0x0600` → `0x8011ff20` returns 10 |

Under the old reading none of that holds. Two independent confirmations: `0xF189` (VW ECU
software version, 4 bytes) resolves to the cal string `"0007"` at `0xa0040080`, and the
`0x02E0/02ED/02EE/02EF/02F9/02FF` chain resolves so that each handler passes **its own** DID to
the record helper `0x801dbd84` and advances by **its own** declared length.

The five tables (`analysis/uds_did_table.csv`, 766 records):

| table | records | contents |
|---|---|---|
| `0x80030890` | 18 | boot/init identity DIDs |
| `0x80083ac0` | 5 | `0x0405/0407/0408/040F`, `0xF17C` |
| **`0x80083b14`** | **39** | **application DIDs — incl. `0x0600` coding** |
| `0x80083d18` | 641 | measuring-value DIDs (`0x1000`–`0x425C`) |
| `0x80085b30` | 63 | `0x16A0`–`0x1717` + `0xF1F0/F1F1/F4F8` |

### 1b. Writing coding — `0x801229b4`

`0x801229b4` is the **DID write dispatcher**. Proof from its body: it reads the payload that
*follows* the DID, length-checks it, copies it into RAM, and passes **`0x2e`** (not `0x22`) as
the mode argument to the shared record helpers `0x801dbd84` / `0x801d5334` — the read handlers
pass `0x22` to those same helpers.

For DID `0x0600` it requires:

1. **request length exactly `0x0d`** — `[2E][06][00]` + **10 coding bytes**, else NRC `0x13`;
2. a **non-zero repair-shop code** already staged in `d000d42a` (6 bytes, written via DID
   `0xF198`), else NRC `0x24` requestSequenceError — i.e. *you must write the workshop code
   before the coding is accepted*, exactly the transaction VCDS/ODIS perform;
3. `coding_validate_and_apply` (§4) must accept the value, else NRC `0x22` / `0x31`.

On success it stages the 10 bytes at `d000b3a6`, copies the workshop code to `d000b3fa`, and
raises NV-write requests `0x801d3628(0x10)` and `0x801d3628(0x0f)`.

> **Open item.** The SID table at `0x80085e58` reads as `SID 0x22 → 0x801229b4`, which
> contradicts the write semantics proved above (and `0x2E` in that table has a NULL handler
> plus aux `0x80085e4c` → `uds_conditions_check_shared`). The *function's* behaviour is not in
> doubt; how the SID row selects it is unresolved. This does not affect any conclusion here.

---

## 2. Where the bytes physically live

| copy | address | size | role |
|---|---|---|---|
| NV record A | EEPROM | 10 | primary stored coding, guarded by an `0xAA55` marker + counter |
| NV record B | EEPROM | 10 | redundant second copy (`0xAA55` marker at a different offset) |
| `d0001487` | RAM | 10 | **active** coding the ECU runs on |
| `d0001491` | RAM | 10 | RAM mirror of NV record A (loaded by `0x801b6358`) |
| `d000149b` | RAM | 10 | RAM mirror of NV record B (loaded by `0x801b6450`) |
| `d000b3a6` | RAM | 10 | coding as last written by a tester — **what DID `0x0600` returns** |
| `d000b3cc` | RAM | 10 | last value accepted by the validator |
| `d00014a5` | RAM | 49 | active coding **unpacked to one byte per cell** |
| `d00014d6` | RAM | 49 | factory-default coding, unpacked |
| `d0001507` | RAM | 49 | previously-stored coding, unpacked |
| `0x800620bc` | **calibration** | 10 | **factory default coding** = `2A2A0012052601060000` |
| `0x80062088` | calibration | 49 | per-cell **rule byte** (codeable / locked / …) |
| `0x8005ac6c` | calibration | 49×8 | per-cell **allowed-value list**, `0xFF`-terminated |

`0x801b6358` and `0x801b6450` each take an NV record buffer and validate it by the constant
`0xAA55`; `0x801b6334` / `0x801b6418` then reconcile the two mirrors. If neither is valid,
`coding_load_default_from_cal` (`0x801b4f44`) falls back to the calibration default at
`0x800620bc` — so **an ECU with erased EEPROM still runs, on the dataset's default coding.**

**Which physical memory:** `uds_dispatch.md` §3b establishes that the only non-calibration
segments in this ECU's UDS reflash descriptor are the TC1796 **DFLASH EEPROM-emulation banks
`0xafe00000` / `0xafe10000`** (64 K each, present twice for erase + program). The coding
records are NV data reached through that record layer, so DFLASH is where they land —
**inference**: the record-layer→DFLASH binding is not traced call-by-call here, and the
callers of `0x801b6358`/`0x801b6450` are reached through a table this pass did not resolve.

The practical consequence is firm either way: **coding is not in the 256 K calibration window,
so reflashing a tune neither carries nor clears it**, and conversely coding a car does not
touch the tune.

---

## 3. The 10 bytes → 49 cells

`coding_unpack_cells` (`0x801b4d64`) explodes the 10 bytes into 49 one-byte cells. The full
bit layout is in **`maps/coding_cells.csv`** and rendered into the label file. Two cells sit
out of numeric order (cell 47 at byte 3 bit 5, cell 48 at byte 8 bit 4), and **byte 8 bit 6 is
never read** — 79 of the 80 bits carry a cell.

Widths: 3-bit and 2-bit multi-value cells plus single-bit flags; e.g. cell 27 = byte 5
bits 5–6, cell 3 = byte 1 bits 0–2.

## 4. The validator decides what a tester may change

`coding_validate_and_apply` (`0x801b5520`) unpacks the candidate coding, then walks all 49
cells against the calibration rule byte at `0x80062088`:

| rule | behaviour |
|---|---|
| `0x02` | value must appear in the cell's allowed-value list at `0x8005ac6c` |
| `0x06` | allowed-list **and** refuses a later change once set |
| `0x10` | **locked** — rejected unless equal to the factory default |
| `0x08` / `0x0a` | additionally gated on a session/security bit |
| `0x20` / `0x22` | carried over from the stored coding rather than taken from the request |
| `0x00` | unused cell |

On this dataset **19 of the 49 cells are `0x10`-locked**, and **9 more have a single-entry
allowed list** (cells 0, 1, 3, 4, 7, 8, 9, 23, 35) — they accept exactly one value. So only
**21 of 49 cells are genuinely changeable**, and one of those (cell 29) only once. That is the honest ceiling on
what any coding tool can change on this ECU — the rest will come back as a rejected write.

The 5×8-byte cross-cell consistency table at `0x8005b158` is **all `0xFF` on this dataset**, so
that check is inert here.

On acceptance the validator calls `coding_decode_cruise_type` (`0x801b5900`), copies the value
to `d000b3cc`, and triggers the NV write.

## 5. Where the cells actually go

`coding_decode_cruise_type` (`0x801b5900`) is the fan-out: it turns the 49 cells into ~60
individual RAM flags (`d000a735`–`d000a762`, `d000b3b0`–`d000b3c6`) that the rest of the
firmware reads. `maps/coding_cells.csv` records, per cell, the destination globals and the
evidence behind the proposed label. Highlights:

- **Cell 27 — cruise-control type** (CONFIRMED, already traced in this repo):
  `1 = GRA` basic cruise, `2 = ACC`, `3 = F2S`. Drives `coding_GRA_ena` (`d000a756`) and
  `LV_DCC_ENA` (`d000a757`); `d000a758` (F2S) is written and never read, so F2S is not
  implemented. This image is coded `1` (GRA) — **and the allowed list for cell 27 is
  `{0,1,2}`, so the validator will accept `2` (ACC).**
- **Cell 3 — the widest-reaching cell**, 122 consumer functions, 5 mutually exclusive classes.
- **Cell 24** → `d000a753`, which gates the `ESP_05` (CAN `0x106`) RX decoder and a 14-bit
  block of TX enables in `can_tx_scheduler` (`0x80106ed8`).
- **Cell 18** indexes six 8-entry calibration tables (`0x8005b2d4/2dc/2e4/2ec/2f4`,
  `0x80042c98`) into `d000b3c0`–`d000b3c5` — a variant parameter set.
- Cells 3, 23, 29 and 35 each contribute one **letter** to a 16-byte identifier assembled by
  `0x801bd36c` from the cal ID block plus four coding-derived characters.
- A dozen single-bit cells gate individual **CAN TX message enables** in `can_tx_scheduler`.

## 6. Honest confidence statement

- **Firmware-derived and reliable:** the bit layout, the factory default, the per-cell rule,
  the allowed-value lists, the locked/codeable state, the storage map, and the `$22`/`$2E`
  `0x0600` path.
- **Hypotheses:** most of the English *names*. Only cell 27 is traced end to end. Cells tagged
  `PROBABLE` are consistent with their consumers but unproven; cells tagged `UNKNOWN` are real
  coding cells whose meaning is simply not established. Nothing here has been written to a car.
- Per this repo's rules, none of the `PROBABLE`/`UNKNOWN` names were added to
  `symbols_merged.csv`; only the structural coding functions, which were read directly, were.

## 7. Reproduce

```bash
source .env.sh && ecus/simos85/reproduce.sh          # needs the image; decompiles are gitignored
python3 ecus/simos85/maps/gen_coding_labels.py \
        ecus/simos85/firmware/8R0907551F_Original.bin ecus/simos85/labels
```

The generator re-reads the rule table, default coding and allowed-value lists straight out of
the image, so `maps/coding_cells.csv` and `labels/8R0-907-551.LBL` regenerate from the binary.
