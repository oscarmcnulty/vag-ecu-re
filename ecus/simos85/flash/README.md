# Simos 8.5 calibration flasher (our own)

Flash a modified **calibration** to the Continental Simos 8.5 (Audi Q5 3.0T,
8R0907551F) over UDS. Built entirely from this repo's reverse engineering — see
`../analysis/flash_protocol.md` for the derivation and firmware citations. It does
**not** import or copy bri3d/VW_Flash; the seed→key is our own `sa2.py`.

Scope: **calibration + EEPROM only** (the OBD reflash descriptor's window). It cannot
write ASW code or the boot sector — that is RSA-signed and gated in CBOOT.

## Pipeline
```
edit full image ─▶ prep_cal.py ─▶ CAL_block3.bin + block_crc32.txt ─▶ flash_simos85.py
```
```bash
# 1. prep: extract CAL block + block CRC-32 (self-tests the CVN vs stock)
python3 prep_cal.py my_tuned_full_flash.bin --stock ../firmware/8R0907551F_Original.bin --out out/

# 2. inspect the plan (dry run — default, writes nothing to the car)
python3 flash_simos85.py out/CAL_block3.bin out/block_crc32.txt

# 3. flash for real (battery charger on, engine off)
python3 flash_simos85.py out/CAL_block3.bin out/block_crc32.txt --flash --transport isotp --channel can0

# SA2 seed→key, standalone
python3 sa2.py DEADBEEF
```

## Files
| file | role |
|---|---|
| `sa2.py` | our SA2 bytecode disassembler + seed→key interpreter |
| `prep_cal.py` | extract CAL block, block CRC-32, self-tested CVN rewrite |
| `flash_simos85.py` | UDS state machine (isotp / panda transports), dry-run by default |

Transports: `--transport isotp` (SocketCAN + `can-isotp`) or `--transport panda`
(comma panda). Both are thin `Transport` shims; wire in your own if needed.

> Status: protocol layer verified against VW_Flash (SA2 keys, CRC-32, wire params all
> reconciled — see `flash_protocol.md §6`). Open items before on-car use: LZSS byte-exact
> match vs the ECU decompressor, and the ECM3 monitor.
