# AL551 CAL flashing (UDS)

How to write an updated **calibration** (block DB_4) to the AL551 TCU over UDS, in the
bri3d/VW_Flash style. Only DB_4 (the CAL) is touched — CBOOT/ASW are left alone, so a bad CAL
faults but is recoverable by reflashing the stock CAL (it does **not** brick the bootloader).

## Flash layout (4 UDS blocks)
| block | content | flash base | size (uncompressed) | method |
|-------|---------|-----------|---------------------|--------|
| DB_1 | ASW    | `0x040000` | 1310208 | 22 |
| DB_2 | blk2   | `0x006000` | 7680    | 22 |
| DB_3 | CBOOT  | `0x020000` | 130560  | 22 |
| **DB_4** | **CAL** | **`0x180200`** | **523776 (`0x7FE00`)** | **22** |

## Two checksums — both standard zlib CRC32, big-endian (VERIFIED on the stock image)
1. **Internal CAL CRC32** at flash `0x180244`, over `0x190000..0x1FFD5F`. Runtime integrity
   check — edit the CAL and this must be rewritten or the ECU faults. Stock = `0x6089B711`.
2. **DB_4 block CRC32** over the whole 523776-byte payload — the argument to the `checkMemory`
   routine (`0x0202`). Stock = `0x8210A83E` (matches the ODX `FW-CHECKSUM`).

`flash/prep_cal.py` fixes (1), extracts DB_4, method-22 encodes it, and computes (2).

## The container ("22" codec)
`ENCRYPT-COMPRESS-METHOD "22"` = 19-byte XOR (`CyA2008ZFVAGtcuxsam`) + bit-flag LZSS (2048-B
window). `al551_codec.py` decodes it; `compress_method22()` **encodes** it as all-literal LZSS
(no matcher needed) — ~1.125× vs the OEM ~4:1, but the ECU decompresses to `UNCOMPRESSED-SIZE`
and stops, so the decoded image / size / CRC are identical. Round-trip is asserted in prep_cal.

## UDS sequence (`flash/flash_cal.py`, VW_Flash pattern)
```
10 03                extended session
04                   OBD mode-04 clear DTCs   <- the real programming-session precondition
85 02                ControlDTCSetting off
28 03 01             CommunicationControl disableRxAndTx
10 02                PROGRAMMING session
27 11 / 27 12        SecurityAccess SA2  (LEVEL 0x11 -- programming; Sa2SeedKey)
31 01 0203           checkProgrammingPreconditions
31 01 FF00 <range>   eraseMemory (DB_4)
34 22 44 <addr4> <len4>   RequestDownload (DFI=method22, ALFID=4B+4B, 0x180200 / 0x7FE00)
36 <seq> <data...>   TransferData (method-22 stream, chunked to the returned max blocklength)
37                   RequestTransferExit
31 01 0202 <crc4>    checkMemory (block CRC32, big-endian)
31 01 FF01           checkProgrammingDependencies
11 01                ECUReset
```

## Workflow
```
# 1. edit the CAL in a copy of the full-flash image (0x190000..0x1FFD5F region)
# 2. prepare (fix CRC32, encode, compute block CRC):
python3 ecus/al551/flash/prep_cal.py my_modified_full_flash.bin --out /tmp/prep
# 3. dry-run the plan, then flash on-car (comma panda on bus 1 / 0x7E1):
python3 ecus/al551/flash/flash_cal.py /tmp/prep/DB_4_method22.bin /tmp/prep/block_crc32.txt
python3 ecus/al551/flash/flash_cal.py /tmp/prep/DB_4_method22.bin /tmp/prep/block_crc32.txt --flash
```

## Verification status (be honest before you flash a car)
- **CONFIRMED**: session/security/precondition sequence (tested on-car earlier — SA2 unlocks the
  programming session at level 0x11 after the OBD mode-04 DTC clear); both CRC32 algorithms
  (computed to match the stock image + ODX); the block/size/method (ODX); the method-22 encoder
  (byte-exact round-trip).
- **NOT yet exercised on-car**: an actual DB_4 *write*. The `RequestDownload` memoryAddress
  (`0x180200`) and the `eraseMemory` argument format follow the DB_4 flash-base + standard VW
  memory-range erase; if the on-car ODX flash job addresses by **logical block number** instead,
  set `RD_ADDR`/`ERASE_ARG` accordingly (both printed in `--dry-run`). `DFI=0x22` is assumed to
  equal the ODX method; confirm against a VCP/ODX trace before writing.
- The `opendbc` `UdsClient` internal calls (`_uds_request`) may need tweaking to the installed
  opendbc version.

## Safety
Battery charger on, engine off, stable 12 V. Do not interrupt. Keep the **stock** DB_4
(`DB_4_plain.bin` / `DB_4_method22.bin` from the unmodified image) to recover. Because CBOOT/ASW
are untouched, a rejected or bad CAL is reflashable — but treat this as unproven until a first
successful stock-CAL round-trip (flash the unmodified CAL back, confirm no DTCs).
