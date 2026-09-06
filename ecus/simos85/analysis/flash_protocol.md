# Simos 8.5 — the UDS flash protocol, reverse-engineered end to end

This is the write-up behind `ecus/simos85/flash/` (our own flasher). It states the
on-wire UDS flash protocol for the Continental Simos 8.5 (Audi Q5 3.0T, 8R0907551F),
derived only from this repo's RE — the firmware image, the ECU's own ODX flash
container, and the sibling AL551/ZF flow. It does **not** derive anything from
bri3d/VW_Flash; `simos8.py` is used solely as the final acceptance test (§Validation).

Companions: `uds_dispatch.md` (SID table, write descriptor), `write_and_rx_flow.md`
(flash-driver call graph), `RE_findings_checksum.md` (CRC primitives),
`mode09_calid_cvn.md` (CVN), `obd_read_feasibility.md` (why there is no read path).

---

## 1. The RX / dispatch surface (recap, from `write_and_rx_flow.md`)

CAN diag frames → ISO-TP transport → `uds_service_dispatch 0x80024f66` → `uds_access_gate
0x8002c3c4` (attr byte vs `session & 0xc`) → the service handler from the 12-byte SID
table at `0x80085e58`. There is **no CCP/XCP slave** and **no `$23`/`$35`/`$3d`** — the
only write surface is the programming-session reflash (`$34`/`$36`/`$37` + `$31`),
scoped by the descriptor at `0x800826c0` to **calibration + EEPROM**. This is a
calibration flasher; it cannot write ASW code or the boot sector.

## 2. Flash blocks (from the ECU's ODX container)

`frf_extract/FL_8R0907551F__0007.odx`, all `ENCRYPT-COMPRESS-METHOD` empty →
**uncompressed, unencrypted**; `SOURCE-START-ADDRESS` is the 1-byte UDS block id:

| block id | component | size (= UNCOMPRESSED-SIZE) |
|---|---|---|
| `0x01` | CBOOT | 81 408 |
| `0x02` | ASW   | 1 572 352 |
| `0x03` | **CAL** | **261 632** |

`<SECURITY-METHOD>ALFID</SECURITY-METHOD><FW-SIGNATURE>014101</FW-SIGNATURE>` →
`dataFormatIdentifier = 0x00`, `addressAndLengthFormatIdentifier = 0x41`
(4-byte size + 1-byte block id). The extracted `CAL_block3.bin` matches the block
carved from the stock image byte-for-byte (`prep_cal.py`).

## 3. SecurityAccess "SA2" (from the ODX; interpreter is ours)

`<SECURITY-METHOD>SA2</SECURITY-METHOD><FW-SIGNATURE>` =
`6805824A10680493300419624A05871510197082499324041966824A058702031970824A0181494C`

`flash/sa2.py` disassembles this to a clean instruction stream (opcode operand widths
recovered by demanding a clean parse to the `0x4C` terminator across all three SA2
scripts this repo holds — EPS, AL551, Simos85). The two XOR constants decode to
`0x15101970` and `0x02031970` — readable as dates, the signature of a correctly-parsed
VW SA2 program. The **structure** is high-confidence; the exact bit-op per opcode is our
hypothesis (the ECU-side check lives in CBOOT, blank over OBD) and is the headline item
the VW_Flash comparison confirms.

## 4. Checksums

- **Loader per-block CRC-16** (the flash-acceptance gate): poly `0xA001`, **init
  `0xABCD`**, computed by the resident loader over the streamed bytes in `0x1e00`
  windows (`uds_validate_xfer_block 0x801d1ebe`; each window: `word[0]==~word[0x1dfc]`,
  `crc16(payload,len,0xABCD)==word[0x1dfa]`). This is an internal staging check — the
  extracted block images are raw (do not carry the trailer), so **the wire payload is
  raw block bytes**; whether the tool must additionally frame the stream is the one wire
  question deferred to the comparison (§Validation).
- **Block CRC-32** (checkMemory `0x0202` argument, if the session runs it): standard zlib
  CRC-32 over the whole block. Stock CAL = `0x0FC49362`.
- **Mode-09 CVN CRC-32** (runtime smog value, NOT a flash gate): descriptor at `0x40300`
  `{type,u32 ref,u32 seg_count, {start,end}…}`; stock ref `0xA92A60BC` (stored
  little-endian). The documented ranges do not reproduce it under plain zlib CRC-32, so
  `prep_cal.py` self-tests and refuses to rewrite an unverified value.

## 5. The sequence (`flash/flash_simos85.py`)

```
10 03                       extended session
85 02                       ControlDTCSetting off
28 03 01                    CommunicationControl disableRxAndTx / normal
10 02                       PROGRAMMING session
27 11 -> 27 12 <key>        SecurityAccess SA2  (sa2.py)
31 01 0203                  checkProgrammingPreconditions
31 01 FF00 03               eraseMemory(block 0x03)
34 00 41 03 <size:4>        RequestDownload (DFI 0x00, ALFID 0x41)  -> maxNumberOfBlockLength
36 <seq> <data...>          TransferData (chunked to maxblk-2)
37                          RequestTransferExit
31 01 0202 <blockCRC32:4>   checkMemory
31 01 FF01                  checkProgrammingDependencies
11 01                       ECUReset
```

## 6. Validation — resolved against the VW_Flash acceptance test

A subagent ran `bri3d/VW_Flash` as the final acceptance test. Results, and the fixes
folded into `flash/` (each independently re-verified against our own firmware where
possible):

| # | item | outcome |
|---|---|---|
| 1 | SecurityAccess level 0x11/0x12 | **MATCH** |
| 2 | ALFID 0x41, 1-byte block-id addressing | **MATCH** |
| 3 | eraseMemory 0xFF00 argument | **Confirmed** `01 03` |
| 4 | precond/checkMem/depend RIDs 0x0203/0x0202/0xFF01 | **MATCH**; checkMemory arg **Confirmed** zero-header `01 03 00 04 00000000` (Simos ignores the UDS value) |
| 5 | TransferData framing | **MATCH** (raw stream on the wire, no 0x1e00 CRC-16 framing — the 0x1e00 CRC-16 is a loader-internal staging check, as §4 held). Chunk cap set to 0xFFD |
| 6 | diag ids 0x7E0/0x7E8 | **MATCH** (OBD Mode-04 on the functional id) |
| 7 | dataFormatIdentifier / compression | **Confirmed** DFI **0xAA** with LZSS+rolling-XOR (`flash/simos_codec.py`), RequestDownload size = uncompressed length; the decompress step is in CBOOT (blank over OBD). |

**SA2 (the headline):** our first interpreter used a wrong register-file model. Replaced
with the correct single-register loop+branch VM (`flash/sa2.py`); **re-verified against
our own firmware** — it reproduces the acceptance-test key vectors exactly
(seed 0 → 0x4DCC7D0C, 0xDEADBEEF → 0x55612515, 0xFFFFFFFF → 0x30CFB280).

**Internal cal CRC-32 (the CVN mystery, now solved):** it is **not** reflected zlib —
it is poly 0x04C11DB7, init 0, non-reflected, no final XOR. **Verified**: over the
descriptor segments this reproduces the stock reference 0xA92A60BC byte-for-byte.
`flash/prep_cal.py` now patches it correctly (a byte-identical image results when cal is
unedited).

**Flow additions folded in** (from the proven tool): OBD Mode-04 clear-DTC precondition
(before) and post-reset; `checkProgrammingPreconditions` run in the *extended* session
before entering programming; a programming-fingerprint write to DID 0xF15A before erase;
and a TesterPresent (3E 00) cadence between steps. The spurious `85 02` / `28 03 01` from
the first draft were removed.

### Open items (do not affect the protocol layer; confirm before on-car use)
- **LZSS byte-exactness.** Our `simos_codec.py` LZSS round-trips (encoder↔decoder proven
  self-consistent) but its window/encoding must byte-match the ECU's CBOOT decompressor.
  Closing this needs the CBOOT dump or a bench read-back. The rolling XOR is symmetric and
  low-risk.
- **ECM3 monitor.** A 64-bit sum near cal offset 0x400 that Simos also checks; its exact
  region isn't pinned from our firmware yet — `prep_cal.py` reports it for manual review
  rather than patching an unverified value.
- **CAL length.** VW_Flash's generic `block_lengths_s8[3]` is 0x3C000; **our ODX for this
  exact part (8R0907551F) says 261632 (0x3FE00) and the carved block matches byte-for-byte**,
  so we keep 261632. Re-confirm per part number if flashing a different Simos8 image.
