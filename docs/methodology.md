# Methodology

End-to-end workflow for reversing a VAG TriCore ECU: extract → decompile → annotate →
map cal → patch → checksum → flash → validate. Specialized for TriCore + VAG flash
containers, and validated against two suppliers (Continental Simos 8.5, Bosch MED17.1.1)
— which is what separates the steps that generalize from the ones that were Simos-shaped
assumptions.

## 0. Acquire & lay out assets

- OBD read (Pcmflash/WinOLS) or bench/BDM dump. OBD reads usually omit the protected
  boot sector (Simos 8.5: file `0x0–0x20000` blank). A bench/boot read is needed to
  study SBOOT/CBOOT (RSA, flash-loader CRC).
- Drop images in `ecus/<name>/firmware/` (gitignored). Record the load base.
- **Record the image's provenance.** A WinOLS export with checksum correction disabled,
  or any file whose name carries a tuning tag, is *not* a virgin OEM read — every cal
  finding derived from it inherits that caveat. Write it in the pack README.

## 1. Localize what changed (no Ghidra)

`core/diff/diff3.py` over Original vs tuned images → the byte ranges that differ are your
modified maps. Restrict to the cal region.

## 2. Find the integrity primitives (no Ghidra)

`core/checksum/crc_finder.py` recovers CRC tables + polynomials by table-matching. Then
decide the integrity model: a *static* cal checksum in the image, or integrity enforced
only at flash-write time? (Simos 8.5: the latter — see
`ecus/simos85/analysis/RE_findings_checksum.md` §4. Simos 18: ECM3 + AES, handled by
VW_Flash.)

## 3. Locate the calibration region

Do not guess it from a memory map. `core/maps/find_cal_region.py` scores each 64 KB block
by **axis-array density** — strictly monotonic u8/u16 runs, the fingerprint of map
breakpoint axes. On MED17.1.1 the cal blocks scored 735–2282 against a median of 115 for
code, a 6–20× separation, and the software-ID strings landed inside the winning span as
an independent corroboration.

## 4. Build the project (one command)

`ecus/<ecu>/reproduce.sh` — a wrapper that sources `ecu.conf` and runs the shared driver
`core/pipeline/reproduce.sh`. Adding an ECU means writing a config, not a pipeline. Each
step is conditional on the config declaring its inputs and **skips loudly** rather than
silently faking a result, so a cold-start pack (nothing but a firmware image) and a mature
one (named functions, an A2L, an identified map framework) run the same code.

Steps: import + `MapMemory` → `FindBaseRegs` → `SetBaseRegs` → `CanonicalizeAlias` →
function set → `ClaimOrphanCode` → `ApplySymbols` → A2L labels → `MarkCalData` →
`DecompileAll` (+ manifest) → disasm fallback → `ResolveCalReads` → `TraceMapCalls` →
`CoverageStat`.

### Base registers are not universal

TriCore code reaches globals through base registers (`a0`/`a1`/`a8`) set once at startup.
`FindBaseRegs.java` recovers the values; `SetBaseRegs.java` applies them as context so
`[a1+off]` folds to an absolute address. **But what a1 points at is supplier-specific:**

| | Simos 8.5 (Continental) | MED17.1.1 (Bosch) |
|---|---|---|
| `a1` | `0x80048000` — **the cal base** | `0x8002f298` — a ROM constant pool in the code region |
| cal addressing | base-register-relative | **absolute** (`movh.a` + `lea`) |
| effect of unlocking a1 | resolved cal refs 23 → 840 | none; cal reads already resolve |

So "unlock a1 to see the maps" is a Simos playbook step, not a TriCore one. Set the cal
window explicitly (`--cal=LO:HI`) and let `ResolveCalReads.java` work either way.

### Map the non-cached alias

TriCore maps the same physical flash twice: cached at `0x80000000`, non-cached at
`0xA0000000`. Firmware genuinely dispatches through alias pointers. With only the cached
block loaded, those flows die as *"Could not follow disassembly flow into non-existing
memory"* and the decompiler **truncates the body** — silent damage that looks like a clean
decompile. `MapMemory.java` byte-maps the alias (a view, not a copy).

That fixes the flow but makes auto-analysis create twin functions at `0xA0…` (~29% of the
MED17 corpus). `CanonicalizeAlias.java` collapses them, distinguishing two cases that must
not be conflated: pure duplicates (delete) and **orphans reachable only through an alias
pointer** (create the cached twin first — a blind delete loses real code).

## 5. Measure coverage in BYTES, not functions

**"% of functions that decompiled cleanly" is the wrong metric.** It only counts functions
Ghidra already found; bytes that never became a function are invisible to it. MED17.1.1
scored 99.9% clean while **621 KB — over half the disassembled bytes in the main program
blocks — sat in no function**, emitting no C and appearing in no manifest.

`core/ghidra/CoverageStat.java` measures the image: in-function vs orphan-disassembled vs
defined data vs erased vs genuinely unaccounted. Erased Infineon flash reads `0x00` (not
`0xFF`), so undefined-zero must be separated out or erased sectors masquerade as coverage.

Two recovery tools, and the difference matters:

- **`ClaimOrphanCode.java` — safe.** Creates functions over code that is *already
  disassembled* but owns no function. Iterates to a fixpoint, because each new function
  exposes more orphan code in the holes of its (usually non-contiguous) body.
- **`RecoverGapWalk.java` — hazardous, kept only in `research/`.** Disassembles *undefined*
  bytes blind. Since erased flash is `0x00`, which decodes to valid-looking TriCore
  instructions, it converted 1.1 MB of erased MED17 fill into ~33k junk functions.
  `RecoverReferencedCode.java` is the safe counterpart: it seeds only where an incoming
  call/jump reference already proves code exists, refuses all-zero targets, and rolls back
  implausibly small bodies.

Before concluding that unaccounted bytes are *missing code*, test it: if
`RecoverReferencedCode` finds zero undefined bytes with an incoming call/jump reference,
and the remainder is thousands of short runs (MED17: 37,411 runs averaging 9.7 bytes),
it is padding, literal pools and axis arrays — a labelling job, not a decompilation one.

## 6. Never let a decompile fail silently

`DecompileAll.java` writes a per-function **manifest** classifying every intended entry
`ok | degraded | bogus | fail | absent`, reconciled against `function_entries.txt`, so a
function that produced no C is reported rather than simply missing. Anything without
usable C goes to `DumpDisasmFns.java` for annotated disassembly, and `recover_sigs.py`
recovers return types the decompiler could not type (from register liveness plus whether
any caller consumes the result).

Not every decompiler warning is damage. "Restarted to delay deadcode elimination for
space" and "Could not recover jumptable … Too many branches" both complete with correct C;
keying `degraded` on them mislabelled ~850 healthy functions. Genuine damage is a body
*truncated* on bytes SLEIGH could not decode.

## 7. Annotate at scale

`core/pipeline/annotate.py` batches decompiles through an LLM (local endpoint or the
`claude` CLI); `iterate.py` closes the loop — apply symbols, refresh the callgraph,
re-decompile, re-annotate only what changed — so each pass has strictly more grounding.

**Track provenance per symbol.** `symbols_merged.csv` carries a `source` column
(`verified` / `re-trace` / `fr-trace` / `llm`). An LLM-proposed name is a hypothesis, not a
finding; cross-reference the supplier Funktionsrahmen or an A2L before promoting one.

## 8. Map the calibration

Identify the map-reader framework and walk descriptors to recover dims/axes (Simos 8.5:
bilinear `kf_interp_u16` @`0x800a5fc0`, descriptor table via `FUN_800a8ff0`;
`TraceMapCalls.java` resolves the map pointer + axes per consumer).

**Source of truth, in order of preference:**

1. **A2L** (`ecus/<ecu>/maps/*.a2l`) — the one committed, hand-edited store. Everything
   else is regenerated from it: `a2l_to_symbols.py` feeds the Ghidra label pass,
   `a2l_catalog.py` emits the flat catalog (both via `core/maps/a2l.py`, the single ASAP2
   reader). Re-derive both after every edit so they never drift.
2. **A recovered cal object table** — where no A2L exists. MED17.1.1 keeps a sorted
   pointer array at `0x80103464` covering the whole cal region: 971 objects with address
   *and* size (the gap to the next), i.e. an A2L index with the names stripped. That
   boundary information is exactly what an A2L is otherwise needed for →
   `core/maps/cal_object_table.py`.

## 9. Patch + re-checksum

Apply byte changes to the cal, then regenerate whatever the integrity model requires
(Simos 8.5: nothing static in-file; the streamed flash CRC16 poly `0xA001` init `0xABCD`
is computed by the loader at write time).

## 10. Flash + validate

Flash via the accepted tool path (the Pcmflash module named in the WinOLS project) or
`core/uds/` over CAN. Validate by reading the cal region back and, ideally, by bench or
drive measurement.

## Reproducibility contract

No decompiled C is ever committed — it is a derived work of copyrighted firmware. What IS
committed is the metadata needed to regenerate it exactly: `function_entries.txt` (entry
addresses), `symbols_merged.csv` (our names/comments + provenance), the A2L, `ecu.conf`,
and the pipeline scripts. `reproduce.sh` rebuilds the rest.
