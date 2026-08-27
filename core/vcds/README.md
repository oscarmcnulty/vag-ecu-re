# VCDS label files

Two unrelated container formats share the `.clb` extension.

## Legacy (~2010, VAG-COM / early VCDS) — `svcdec.py`

Records separated by `\x00\n`; each byte folded against a fixed 1597-byte
keystream (which is VCDS' own *"How to Copy and Paste"* help page, stored in the
program as `byte * ((i&3)+2) * ((i&5)+1)` so it doesn't look like text):

```
cch    = key[pos] | 128
plain  = cch ^ ((cipher - cch) & 255)
```

The only per-line secret is where in the keystream the line starts:
`offset(n) = ((n % 16) * P + Z) % 256`, with shipped presets
`(P,Z) ∈ {(3,250), (2,250), (3,233)}`. `svcdec.py <file> brt` recovers an
unknown `(P,Z)` from the file itself. Port of
[isublimity/SVCdec](https://github.com/isublimity/SVCdec) `SVCdec.php`.

## Current (VCDS ≥ ~12.12, incl. 21.3.0) — `clbinfo.py`

`svcdec.py` does **not** read these: none of the 1114 `.clb` files in the
VCDS 21.3.0 installer decode at any keystream offset. The container is

```
repeat: u16be plaintext_length | ciphertext (length rounded up to ×8) | 00 0A
```

and one record is one *data* line of the source `.lbl` (comments are dropped at
compile time). `.crd` coding-reference files use the same container.

Evidence from the 21.3.0 corpus (1162 files, 99940 records, `clbinfo.py --corpus`):

| observation | conclusion |
|---|---|
| ciphertext always a multiple of 8, padded only when needed | 8-byte block cipher, length field replaces padding |
| 0 of 621590 distinct blocks occur at two different block indices | not ECB, not a position-independent stream |
| 77533 repeated blocks at index > 0, **all** with an identical preceding block | chaining — CBC |
| block 0 repeats across unrelated files | fixed IV, one global key |
| `.crd` blocks collide with `.clb` blocks | same key for both file types |

Known plaintext: `e6427c2e261007a1` = `E(IV ^ "REDIRECT")`, seen as record 0 in
418 files — all of them 2–7 record redirect stubs whose first record is 39–48
bytes, matching the `REDIRECT,<part-number>.CLB,<...>` lines in the 1301 label
files that ship unencrypted.

### Key status: not recovered

* A dictionary attack (Blowfish / CAST5 / IDEA / 3DES / TEA / XTEA × raw,
  zero-pad, MD5, SHA-1, SHA-256, UTF-16 SHA-1 derivations × Ross-Tech-flavoured
  passphrases) found nothing. Test oracle: for a candidate key,
  `D(ct[i]) ^ ct[i-1]` must be printable for every record — a wrong key scores
  ~0.38 printable, the right one 1.00.
* The algorithm lives only in `VCDS-32.exe` / `VCDS-64.exe`, and both are
  protector-packed: every section RWX with entropy 8.00, unnamed sections, a
  177 MB virtual section, entry point in the last section, one-import-per-DLL
  stub table, `PUBLIC_MODULUS_*` RCDATA licence resources. Ghidra sees only the
  packer. No other shipped binary (LCode, VCDSScan, VCIConfig, VCScope,
  CSVConv, TDIGraph, RT-USB) references `.clb` — LCode reads `.LBL`/`.XPL` only.

Recovering the key therefore needs a runtime dump: run VCDS on Windows (or
Wine), let the protector unpack, dump the image (Scylla/x64dbg, or read
`/proc/<pid>/mem` under Wine), then analyse the dump. The label reader can be
found from the `\x00\n` record walk or by breakpointing the `.clb` file read.
