# 8R0907468 gateway — RE findings

Audi B8/8R CAN gateway **J533** (VCDS address 19), part **8R0907468**, component
**GW-BEM 5CAN-M** (LEAR Electronics). Scanned on the car as SW `8R0907468 P` /
HW `8R0907468 D`, component `GW-BEM 5CAN-M H11 0056`; this image is SW `0060`.

Subsystems reported on the same node (context, not in this image): `8R0915181`
J367 battery monitor (BDM), `8K0959663B` J532 DC/DC stabiliser.

## Status

| item | state |
|------|-------|
| SGO container parse | ✅ solved (`docs/container_and_cipher.md`) |
| crypt=0x01 scrambler | ✅ solved — self-sync LFSR, byte-exact, verified correct (below) |
| descrambled block | ✅ recovered, `firmware/8R0907468_0060_plain.bin` (gitignored) |
| **block contents** | ✅ **it is a raw DATA partition — fixed-record tables + dense fields** |
| **not code / not a codec** | ✅ **no executable code, no compression, no encryption here** |
| program code + architecture | ⛔ **not in this single-block .sgo** — lives in the code partition |

## The scrambler is correct (verified, not assumed)

The self-sync scrambler (`tools/sgo_gw_decode.py`, `docs/container_and_cipher.md`) is
genuinely correct, and this was re-checked hard this session because the round-trip alone
proves only invertibility:

- **Direction test.** The raw `.sgo` blob is featureless uniform noise (byte χ² ≈ 266,
  ≈ uniform); descrambling turns it into *strongly structured* data (χ² ≈ 27 700). A
  descramble that damaged real content would go structured → random; this goes
  random → structured, which is what a *correct* descramble does.
- **Erased tail** FIR-descrambles to clean `0x00` across `0x7E010..0xBD010` (100 % zero) —
  only the correct poly/taps do that, and a self-sync descrambler recovers correct plaintext
  at every bit once the poly is right (re-syncs within 15 bits, so any header/phase offset
  could corrupt at most the first ~2 bytes).

## What the block actually is: a raw binary DATA partition

The descrambled block is **not** executable code and **not** packed. It is raw, structured
binary data — a data/config/routing/calibration partition — proven by:

- **Fixed-record tables.** e.g. `0x6F000` is a clean **22-byte-record** table: each record =
  4-byte variable prefix + a constant 6-byte field (`e0 9d d5 a6 ec d2`) + short variable
  suffix + `0xFF` padding, the constant recurring **every 22 bytes exactly**. Other slabs
  show 24-/30-/74-byte record periods (autocorrelation). Code has no such fixed periods.
- **Not compressed.** `gzip -9` shrinks the whole region ~17 %, and the table slabs 30–56 %.
  An LZ/compressed stream cannot be re-compressed like that (it sits at ~0.98–1.0), and LZ
  would have *tokenised* the literal repeats — yet the 6-byte constant appears verbatim
  hundreds of times. `zlib`/raw/`gzip`/`lzma`/`bz2` all fail to decode it, at every offset.
- **Not encrypted.** Even the least-compressible slab has byte χ² ≈ 2500 (AES ≈ 255),
  ~11 000 / 16 384 distinct halfwords with thousands of exact 4-byte repeats (a cipher gives
  all-unique blocks, ~0 repeats).
- **Not code.** A 10-arch Ghidra linear sweep + targeted disassembly (`analysis/arch_sweep.md`,
  `tools/arch_sweep.sh`) finds no coherent code under any arch; the low-`invalid%` fits are a
  permissive-decoder artifact (the *raw random* blob scores the same "V850 1% invalid"). Every
  low-entropy region disassembles to a repeating data record, not instructions.
- **No text.** Zero real ASCII anywhere — no part number, no coding/ASAM strings — consistent
  with numeric tables, not code/calibration-with-labels.

The high overall byte entropy (~7.9) that first looked like "compression" is just the density
of the variable table fields; the constant fields and `0xFF` padding are what `gzip` and the
χ² test pick up as structure.

## Consequence for architecture ID

The CPU architecture **cannot** be read from this container, not because of a codec, but
because the **program code is not in it**. This `.sgo` carries a single block at flash base
`0x8010` (data), with no reset vector table — consistent with the executable image living in a
separate code partition (plausibly below `0x8010`, and/or a different SW block) that this
one-block container does not ship. `PROCESSOR` stays unset.

## CAN routing extraction — attempted, blocked in this container

Directly targeted this session. The routing table is **not recoverable from this block**:

- **No CAN-ID column exists.** Scanning the whole image for 16-bit values in the 11-bit range
  (`0x001..0x7FF`) as LE, BE, and left-justified (`<<5`) encodings returns only noise-level
  density (~2 %, = random) — no region is a plaintext ID table. `0x00` is the *rarest* byte
  everywhere (0.26 %), the opposite of a small-integer routing table.
- **The tables are keyed by opaque/hashed identifiers.** The cleanest table (`0x6F000`, 82×
  22-byte records) is: `[type][3-byte key][const e0 9d d5 a6 ec d2][4-byte value][ff ff ff]
  [4-byte footer]`. The 3- and 4-byte fields are near-maximal entropy and unique per record —
  a hash/handle keyed table, not `(bus, CAN-ID, dst-mask)` tuples. High halfword entropy
  (55 051 distinct halfwords) rules out any byte- or word-substitution hiding small integers.
- **No block header / section directory / in-range pointers** at `0x8010` to index a routing
  segment; container metadata only carries the filename.

**Conclusion.** The CAN routing rules are not in this data block in any decodable plaintext
form. On this LEAR gateway they live in the **application code** (which this `.sgo` does not
ship) and/or in **coding/adaptation data** (EEPROM, also not here); the opaque hash-keyed
records here are meaningful only against code symbols we do not have. Two ways to actually get
the routing:

1. **Static:** obtain the code partition (below), disassemble, read the routing logic.
2. **Empirical (best for the openpilot goal):** tap the 5 gateway buses and observe which IDs
   are forwarded bus→bus. This yields the live routing map directly, no firmware needed, and
   fits the existing comma3/panda CAN setup ([[openpilot-integration-goal]]).

## What would unblock code / architecture

1. **The code partition.** A full flash `.frf`/`.sgo` set or a bench read that includes the
   program bank (with the vector table). That is the only reliable path — same pattern as
   other packs here that needed the boot/code block.
2. **Decode the data tables (separate goal).** The 22-/24-/30-/74-byte record formats here are
   the gateway's routing/config data and are directly relevant to CAN-routing / bus-gating
   questions for the openpilot work — worth reversing on their own terms, independent of the
   code. Start from the fixed-record slabs (`0x6F000`, `0x0B000`, `0x18800`).

## Reproduce this session's analysis

```bash
source .env.sh
python3 ecus/gateway/tools/sgo_gw_decode.py \
    ecus/gateway/firmware/8R0907468___0060.sgo \
    -o ecus/gateway/firmware/8R0907468_0060_plain.bin --verify
ecus/gateway/tools/arch_sweep.sh 0x20000 0x18000     # 10-arch sweep (all reject)
```
