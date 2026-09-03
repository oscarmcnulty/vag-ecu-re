# 8R0907468 gateway — multi-arch linear-sweep results

Reproduce: `source .env.sh` then `ecus/gateway/tools/arch_sweep.sh 0x20000 0x18000`
(imports the descrambled plaintext under each Ghidra language via BinaryLoader at base
`0x8010`, `-noanalysis`, and runs `ghidra_scripts/FullSweep.java` over the window).

## Sweep scores — 96 KB window at 0x20000 (dense "code" region)

`valid`/`invalid` = instructions the linear disassembler accepted / rejected; `rets` =
terminators; `calls`/`distinctTargets`/`reused>=2` = direct-call targets landing inside
`0x8010..0x78000` and how often they repeat.

| language | invalid% | rets | calls | distinctTargets | reused≥2 | verdict |
|---|--:|--:|--:|--:|--:|---|
| `V850:LE:32:default`    |  **1%** |  47 | 503 |  48 | 0 | permissive fit — see below |
| `M16C/60:LE:16:default` |   2% | 273 | 789 | 254 | 1 | permissive fit |
| `ARM:LE:32:v8T` (Thumb) |   6% | 222 | 554 |   5 | 0 | reject |
| `M16C/80:LE:16:default` |   8% | 614 | 910 | 200 | 1 | reject |
| `SuperH4:LE:32:default` |  12% |   3 |3191 |3080 |95 | reject |
| `ARM:LE:32:v7` (ARM)    |  18% | 965 |1938 |   9 | 0 | reject |
| `NDS32:LE:32:default`   |  23% |  87 | 251 |  49 | 0 | reject |
| `PowerPC:BE:32:default` |  28% |   0 | 433 | 113 | 0 | reject (control) |
| `Xtensa:LE:32:default`  |  27% |   1 |2487 | 976 | 4 | reject |
| `tricore:LE:32:tc176x`  |  40% |   0 |1142 |   0 | 0 | reject (control) |

Renesas RX and RL78 are **not** shipped with Ghidra 12.1.2, so they could not be swept
here; nothing in the evidence points to them anyway (see below).

## Why the low-`invalid%` fits are NOT the architecture

The V850 / M16C low reject rates are an artifact of a permissive decoder run over
**structured non-random bytes**, not evidence of real code. Direct disassembly disproves
code at every candidate offset:

- **Dense region (0xb260, a `d9 35`-idiom cluster).** Under V850 the recurring 8-byte
  idiom `d935af881d41bbfb` decodes self-consistently, but the *content* is not code: a
  `bnc` conditional branch every ~3 instructions, wall-to-wall saturating arithmetic
  (`satsub`/`satsubr`/`satadd`) and packed-halfword stores, with **no** function
  prologues (`prepare`/`dispose`), **no** `jarl` calls to reused targets, and **no**
  `movhi`+`movea` constant loads. Real V850 code looks nothing like this.
- **Taper region (0x6a010).** Decodes to a repeating ~10-byte record (`…37 5567 559f 15…`)
  — a data table, again read as "1% invalid" by the permissive V850 decoder.
- **call-target reuse is ~0** under every arch (`reused>=2 ≤ 1` for the plausible ones):
  real code has functions called from many sites; this has essentially none.

## The finding: this block is a raw DATA partition, not code

The descrambled block is not executable under any arch because it is **raw structured binary
data** (a data/config/routing/calibration partition), not code — and not compressed or
encrypted either. Evidence (details in `docs/RE_findings.md`):

1. **Fixed-record tables.** `0x6F000` is a clean 22-byte-record table (constant 6-byte field
   `e0 9d d5 a6 ec d2` recurring every 22 bytes, + variable prefix/suffix + `0xFF` pad);
   other slabs show 24-/30-/74-byte record periods by autocorrelation. Code has no such
   fixed periods.
2. **Not compressed.** `gzip -9` shrinks the region ~17 % overall and table slabs 30–56 % —
   impossible for an already-compressed stream (~0.98–1.0) — and LZ would tokenise the
   literal repeats instead of leaving a 6-byte constant verbatim hundreds of times.
   `zlib`/raw/`gzip`/`lzma`/`bz2` all fail at every offset.
3. **Not encrypted.** Least-compressible slab still has byte chi² ≈ 2500 (AES ≈ 255),
   ~11 000/16 384 distinct halfwords with thousands of exact 4-byte repeats (a cipher gives
   all-unique blocks, ≈0 repeats). simos-suite's `crypt=0x01 → "AES"` label is wrong here.
4. **No surviving strings.** Zero real ASCII — consistent with numeric tables, not code.

The ~7.9 bit/byte entropy that first suggested "compression" is just the density of the
variable table fields; the constant fields + `0xFF` padding are the structure gzip/chi² see.
So the architecture cannot be read here — not because of a codec, but because the **program
code is not in this one-block container** (it lives in a separate code partition; there is no
reset-vector table at `0x8010`).

> Correction: an earlier pass this session labelled the block "packed/compressed under a
> custom codec." Deeper tests (gzip-ratio, chi², halfword-repeat, fixed-record autocorrelation)
> disproved that — it is raw uncompressed/unencrypted data. There is no codec to reverse.

## Is the descramble damaging the bin? No — it reveals structure

A fair objection: the byte-exact round-trip only proves the scrambler is invertible, not
that the code region was ever scrambled (if only the fill were scrambled, descrambling would
*corrupt* plaintext code and the round-trip would still pass). The direction of the transform
settles it:

| region | entropy | chi² (uniform ≈ 255) | top 4-byte pattern |
|---|--:|--:|---|
| RAW `.sgo` blob (pre-descramble) | 8.000 |    266 | 2× |
| DESCRAMBLED | 7.955 | 27 743 | 815× |

The raw blob is **featureless uniform noise** (chi² ≈ 255); descrambling turns it into
**strongly structured** data. A descramble that damaged real code would go the other way
(structured → random). random → structured is what a *correct* descrambler does. And the
poly is provably right: the erased tail zeroes out over many LFSR periods, which only the
correct taps can achieve. (A self-sync descrambler also re-synchronises within 15 bits, so a
header/phase offset could corrupt at most the first ~2 bytes, never the bulk.)

Note the raw blob *also* sweeps at "V850 1% invalid" — identical to the descrambled block —
which is the final proof that the sweep's low reject-rate is meaningless: a permissive RISC
decoder accepts ~99% of *provably-random* bytes. Only chi² + real disassembly separate code
from non-code here, and both say: not code.

**Conclusion.** The single `.sgo` block is a *raw binary DATA partition* (fixed-record
tables + dense fields), correctly descrambled and final — not code, not compressed, not
encrypted. Identifying the CPU architecture from this block is therefore impossible because
the **program code is not in it**: this container ships one block at data base `0x8010` with
no reset-vector table, so the executable image lives in a separate code partition (plausibly
below `0x8010` and/or another SW block) that this container does not include.
