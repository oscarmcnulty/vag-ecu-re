# vag-ecu-re

Reverse-engineering toolkit for **VAG (Audi/VW) TriCore-based engine ECUs** —
the Continental *Simos* and Bosch *MED17 / MD1* lineages, all built on Infineon
TriCore. Inspired by the structure of
[ghostdev137/ford-pscm-re](https://github.com/ghostdev137/ford-pscm-re), but
adapted to TriCore (which Ghidra decompiles natively — so we skip the custom
SLEIGH processor that project needed for Renesas V850).

## Why this scope

| ECU | Supplier | MCU | Arch |
|-----|----------|-----|------|
| Simos 8.5 | Continental | TC1796 | TriCore 1.3 |
| MED17.1.1 | Bosch | TC1797 | TriCore 1.3.1 |
| Simos 18.1 / 18.10 | Continental | TC1791/93 | TriCore 1.3 |
| MD1 / MG1 (MLBevo) | Bosch | Aurix TC27x/29x | TriCore 1.6 |

Everything in `core/` is shared across these; per-ECU knowledge lives in
`ecus/<name>/`. The reuse boundary is deliberately **VAG + TriCore** — outside
that, almost nothing concrete transfers. Two suppliers are done (Simos 8.5,
MED17.1.1), which is what lets the docs distinguish a genuine TriCore step from a
Simos-shaped assumption (e.g. base-register cal addressing — see
`docs/methodology.md` §4).

## Layout

```
core/        Reusable, arch-agnostic-ish tooling (built against simos85, generalized on med17)
  ghidra/      headless import + memory-map + symbol-apply + decompile-dump + coverage
  pipeline/    reproduce.sh — the shared ECU-agnostic build driver
               annotate.py / iterate.py — AI function annotation (OpenAI-compatible or claude CLI)
  maps/        A2L reader + cal-region locator + cal-object-table + xref tooling
  diff/        diff3.py — N-way image/cal diff (RUNS TODAY, no Ghidra)
  checksum/    crc_finder.py — locate & ID CRC tables (RUNS TODAY, no Ghidra)
  uds/         ISO-14229 client harness for cal read/write over CAN
  odx/         ODX-F / FRF flash-container parsing
research/    Exploration scripts kept for provenance — NOT on the reproduce path, not maintained
ecus/
  simos85/     Reference pack — Audi Q5 3.0 TFSI; the core/ tooling was built here
  med17/       Bosch pack — Audi Q5 2.0 TFSI; first proof the pipeline generalizes
  simos18/     Placeholder — will vendor bri3d/VW_Flash rather than reinventing it
docs/        methodology.md, local_llm.md
```

## How reproduction works

No decompiled C is committed — it is a derived work of copyrighted firmware.
What is committed is the metadata to regenerate it, and one driver rebuilds it:

```bash
source .env.sh                 # JAVA_HOME, GHIDRA_HOME (Ghidra 12.1.2 / JDK 21)
# supply ecus/<ecu>/firmware/<image> locally (gitignored)
ecus/simos85/reproduce.sh      # or ecus/med17/reproduce.sh
```

Each `ecus/<ecu>/reproduce.sh` is a two-line wrapper that sources `ecu.conf`
(the ECU's parameters — load base, base registers, cal window, memory map, …)
and runs `core/pipeline/reproduce.sh`. **Adding an ECU is writing a config, not a
pipeline.** Every step skips *loudly* when its inputs aren't declared, so a
cold-start pack (nothing but a firmware image) and a mature one run the same code.

## Runnable today (no Ghidra needed)

```bash
# Find every CRC lookup table and recover its polynomial
python3 core/checksum/crc_finder.py ecus/simos85/firmware/8R0907551F_Original.bin

# Localize modified maps across tunes (cal region 0x40000:0x80000)
python3 core/diff/diff3.py \
    ecus/simos85/firmware/8R0907551F_Original.bin \
    ecus/simos85/firmware/8R0907551F_Stage1.bin \
    ecus/simos85/firmware/8R0907551F_Stage2.bin --region 0x40000:0x80000
```

## Reading the findings honestly

Two disclosures the repo makes up front, because taking a number here at face
value would be a mistake:

- **`symbols_merged.csv` now holds only confirmed names.** A 20-sample audit found the
  machine-proposed (`llm`) names were 20% actively *wrong* — misleading in the way that
  misdirects analysis (see `ecus/simos85/analysis/symbol_name_audit.md`), so the ~2500 of
  them were removed. It now carries only `source ∈ {verified, re-trace, fr-trace}`;
  everything else is `FUN_<addr>` (honest "unknown"). The retired guesses are recoverable
  from git history if ever wanted, but are deliberately not carried in the tree.
- **The MED17 image is not a virgin OEM read.** It is a WinOLS export tagged
  `ACC_ENABLE` with checksum correction off — the cal area may already be
  modified, precisely in the ACC/cruise bytes under study. Every MED17 cal
  finding inherits that caveat; a stock read to diff against is the highest-value
  missing input. See `ecus/med17/README.md`.

## Status

- [x] Repo scaffold + core diff/checksum tools (verified on Simos 8.5)
- [x] Ghidra headless pipeline reproducible from committed metadata (both packs)
- [x] Shared reproduce driver + per-ECU config (`ecu.conf`)
- [x] Second supplier proven (MED17.1.1) — generalized the base-register / alias / coverage handling
- [x] AI annotation pipeline wired (local endpoint + `claude` CLI backends)
- [ ] simos18 pack (vendor VW_Flash)
- [ ] Obtain a bench/boot read to study SBOOT/CBOOT (RSA, flash loader)

See `docs/methodology.md` for the end-to-end workflow, and each pack's
`README.md` for ECU-specific findings.

> For research and personal-vehicle use only. See `LICENSE` for scope.
