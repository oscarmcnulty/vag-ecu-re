# ESP8 8R0907379BG — flash signature analysis

Investigating the two `SIGNATURE_BLOCKS` (variant.conf) to answer: **can we re-sign a
patched image?** Short answer: **no — they are RSA-1024 signatures.** Re-signing needs
Bosch's private key. The path to a patched flash is a bootloader-level bypass, not a re-sign.

## Descriptor format (identical in both blocks)

```
[0xNN fill]
u32  signed_region_length      (big-endian)
u32  magic = 0x81820154
u8[8] field                    (differs per block; hash-prefix or key-id, NOT a plain CRC/SHA of the region)
u8[12] algo/version header = 00 00 00 01 01 01 00 00 00 03 04 00   (IDENTICAL in both -> same scheme)
char[] "Bosch.CSDE.BEG_VAG.01.004\0" + zero pad
u8[128] SIGNATURE              (H=6.53, ~uniform -> RSA-1024)
[0xb6 fill to segment end]
```

## Two independent signing units (confirmed by arithmetic)

| block | descriptor @ | declared len | signed region | contents |
|-------|-------------|--------------|---------------|----------|
| SIG1  | 0xb7f20 | 0xbd424 | [0x0, 0xbd424) (sig window excluded) | **ASW / program** |
| SIG2  | 0x133be9 | 0x61b28 | **[0xd20c1, 0x133be9)** exact | **CAL / dataset** |

SIG2 is clean: `0x133be9 - 0x61b28 = 0xd20c1`, so the signed region ends exactly at the
descriptor. SIG1 covers the program from 0x0 with its own descriptor window zeroed during hash.

## Why it's RSA, not a checksum

- Blob is **128 bytes** of high-entropy data (H=6.53, 100/256 distinct byte values). A CRC is
  2-4 bytes, a CMAC 16, a SHA-256 32. 128 bytes = **RSA-1024** signature.
- The 12-byte header `...00 03 04 00` is a fixed algorithm/keylen descriptor (0x04 -> 4*256 =
  1024-bit), identical across both blocks.
- No plain SHA-1/256/MD5/CRC32 over the naive signed regions reproduces the 8-byte field, i.e.
  the integrity value lives *inside* the RSA-signed structure, not as a separate recomputable tag.

## Consequence: re-signing is impossible; bypass is the route

You cannot forge or recompute an RSA-1024 signature without the private key (not in firmware;
only the public key is, and it lives in the **bootloader**, not this ASW image). So a patched
image is only flashable if the verification can be defeated. All four routes need SBOOT/CBOOT,
which is why the bench spare matters:

1. **Enforcement question:** does CBOOT verify RSA only at *flash time* (0x31 routine after
   0x36) while the runtime jump checks only a CRC? If so, a patched ASW with a corrected
   runtime CRC boots despite an invalid RSA sig — you only need to pass the flash-time gate.
2. **CBOOT verify patch:** flip the signature-check branch, or exploit a verify-routine bug.
3. **SBOOT exploit** (cf. the Simos SBOOT OBD path) to write flash bypassing enforcement.
4. **Voltage-glitch** the verify branch at flash time (bench only).

## Next task

Bench-dump SBOOT/CBOOT (hardware read of the opened unit) and reverse the signature-verify
routine: locate the RSA public modulus + exponent, find the verify call site, and determine
whether it gates the runtime jump or only the download. That decides which of routes 1-4 is
viable. Ties: [[esp8-bench-pinout]] (bench harness), [[abs-sa2-key]] (UDS unlock).
