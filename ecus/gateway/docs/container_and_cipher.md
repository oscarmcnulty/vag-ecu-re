# 8R0907468 gateway — SGO container + the crypt=0x01 scrambler

The gateway flashdaten arrives as a standalone VAG **"SGML Object File"** (`.sgo`).
Everything here is reproduced by `tools/sgo_gw_decode.py` and verified byte-exact.

## Container

`SGML Object File` magic, then a small header. The fields the parser uses (all u32-LE
unless noted), matching `~/tools/simos-suite/cp_tools/sgo_unpack.py`:

| offset | meaning |
|--------|---------|
| `0x00` | magic `SGML Object File` |
| `0x19` | pointer to the IDENT block (0xFF-XOR'd part number + SW version) |
| `0x29` | pointer to the SA2 security section (`len` u32, then the SA2 bytecode) |
| `0x2D` | end of block data (start of the trailing block-offset table) |

For `8R0907468___0060`:

- **Part / version:** `8R0907468___0060`, SW `0060`
- **One flash block:** big-endian 25-byte descriptor →
  `addr 0x008010, crypt 0x01, declen 0xB7FF0, blob_len 0xB7FF0`
- `declen == blob_len` ⇒ the payload is **length-preserving** (no compression at the
  container layer).

## The crypt=0x01 cipher — solved

simos-suite's unpacker flags any high-entropy `declen%16==0` block as **AES (key
unknown)** and walls it. That heuristic is **wrong for this LEAR gateway**. The payload
is a **multiplicative self-synchronising bit scrambler**, LSB-first, with the maximal
15-bit polynomial **x¹⁵ + x¹⁴ + 1**:

```
descramble:  p[t] = c[t] XOR c[t-14] XOR c[t-15]      (bit index t, LSB-first, taps for t>=15)
scramble:    c[t] = p[t] XOR c[t-14] XOR c[t-15]
```

AES in any mode is impossible here: the erased-flash region repeats with period exactly
`0x7FFF` bytes, and `0x7FFF` is not a multiple of the 16-byte AES block, which no
ECB/CBC/CFB/OFB/CTR construction can produce.

### How it was cracked (reproducible from the file alone)

1. **Period.** A constant-input (erased-flash) span repeats with period exactly
   `0x7FFF = 2¹⁵ − 1` — the maximal period of a 15-bit LFSR.
2. **Berlekamp-Massey** on that span: **linear complexity 15** in LSB-first bit order
   (120 in MSB-first). That proves a degree-15 LFSR and fixes the bit endianness.
3. **GF(2) tap solve** on the zero-fill region (where `p=0`, so the ciphertext obeys the
   descrambler's own recurrence): taps `[14, 15]`, stable across window sizes.
4. **Validation.**
   - Erased flash (`0x80000..0xC0000`) descrambles to a clean 256 KB run of `0x00`.
   - `0xFF` padding runs and repeated 16-bit constant tables appear at the right places.
   - Identical opcode byte-strings (`d9 34 2b 08`) recur at multiple offsets ⇒ no residual
     position-dependent transform.
   - **Re-scrambling the recovered plaintext reproduces the `.sgo` block byte-for-byte.**

### Why this matters

- Other SGO versions (0051/0055/0056/0060/0070) and the 8T sibling use the same
  container; this scrambler should invert all of them (re-run the tool).
- No `.frf`, no bench dump, and no key were needed — this is a pure-cryptanalysis decode.
- It corrects the public tooling: `crypt=0x01` here is a self-sync LFSR scrambler, not AES.
