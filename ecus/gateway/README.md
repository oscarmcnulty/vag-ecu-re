# gateway — Audi B8/8R CAN Gateway (J533, 8R0907468)

CAN gateway / body-electronics master, **VCDS address 19**, component **GW-BEM 5CAN-M**
(LEAR Electronics). Our car: `8R0907468 P` / HW `8R0907468 D` / `H11 0056`; the image here
is SW `0060`.

## What is solved

The gateway ships as a standalone VAG **SGML Object File** (`.sgo`) whose single flash
block uses **crypt=0x01**. Public tooling (simos-suite) mislabels that as "AES (key
unknown)" and walls it. It is not AES — it is a **multiplicative self-synchronising bit
scrambler**, LSB-first, polynomial **x¹⁵ + x¹⁴ + 1**:

```
p[t] = c[t] XOR c[t-14] XOR c[t-15]        # descramble, taps for t>=15
```

Cracked from the file alone (period 0x7FFF → Berlekamp-Massey linear complexity 15 → GF(2)
tap solve), and **validated byte-exact** (re-scrambling the plaintext reproduces the
`.sgo`; erased flash → clean 0x00). Details: `docs/container_and_cipher.md`.

## Reproduce the plaintext

```bash
python3 tools/sgo_gw_decode.py firmware/8R0907468___0060.sgo \
    -o firmware/8R0907468_0060_plain.bin --verify
```

The `.sgo` and the plaintext are firmware-derived and gitignored — never committed.

## Layout

```
ecus/gateway/
  tools/sgo_gw_decode.py     SGO parser + crypt=0x01 descrambler/scrambler (verify round-trip)
  ecu.conf                   pipeline parameters (PROCESSOR unset until arch is confirmed)
  reproduce.sh               wrapper over core/pipeline/reproduce.sh
  firmware/                  .sgo + descrambled .bin (gitignored)
  docs/container_and_cipher.md   container format + the cipher, how it was cracked
  docs/RE_findings.md            image layout, arch-ID plan, open questions
  analysis/                  decode reports, arch sweeps
  ghidra_scripts/            (per-ECU scripts; added once the arch sweep lands)
```

## Next task — architecture

The container is fully decoded; the open item is identifying the MCU so decompilation can
start. Heuristics point to a **2-byte-aligned little-endian** ISA (candidates: Renesas
V850 / RX / RL78, or ARM Thumb). Resolve with a Ghidra multi-arch linear sweep as
`ecus/eps` did, then set `PROCESSOR` in `ecu.conf` and run `reproduce.sh`. See
`docs/RE_findings.md`.
