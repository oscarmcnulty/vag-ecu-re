# research/ — exploration scripts (not maintained, not on the reproduce path)

These produced findings that now live in the `ecus/*/maps/` documents but are **not**
part of the reproducible pipeline. Any corpus figure quoted in these files (function counts,
coverage percentages) is a snapshot from when it was written and was not updated afterwards —
treat `ecus/<ecu>/analysis/` as the authority for current numbers. `ecus/<ecu>/reproduce.sh` never calls anything here.
They are kept for provenance — so a reader can see *how* a result was reached — and because
several are a useful starting point for anyone doing TriCore RE. Expect rough edges:
hardcoded addresses, one-shot assumptions, no argument validation. Nothing here is covered
by the reproducibility contract; `core/` is the supported surface.

## emulation/

Ghidra `EmulatorHelper`-driven boot/trace experiments used to pin down dynamic behaviour
the static decompile could not (which function writes a CAN output shadow, where a decel
clamp actually fires, etc.). A family of variants that grew one from another and share a
lot of copy-pasted scaffolding (`A`/`zero`/`w32`/`enc`/`rU32` helpers, a boot-to-run-mode
bridge). If you revive this, collapse them into one parameterized emulator first.

## discovery/

Function- and table-recovery experiments from before the corpus was complete.
`function_entries.txt` (committed) is the settled output, so these are superseded for
reproduction:

- `HarvestFromSeed.java`, `harvest_functions.py` — recover call targets from raw CALL/JL/FCALL
  displacement decoding.
- `AddrGenSweep.java`, `CodePtrSweep.java` — sweep for address-generation / code-pointer runs.
- `gen_tablemap.py` — one-shot function-pointer dispatch-table finder (superseded by
  `core/maps/resolve_dispatch_tables.py`).
- `RecoverGapFns.java`, `RecoverGapStructural.java`, **`RecoverGapWalk.java`**.

> ⚠️ **`RecoverGapWalk.java` is a documented footgun.** It disassembles *undefined* bytes
> blind. On an image whose erased flash reads `0x00` (which decodes to valid-looking TriCore
> instructions), it turned **1.1 MB of erased MED17 fill into ~33k junk functions**. It is
> here as the cautionary counter-example, not as a tool to run. Use
> `core/ghidra/RecoverReferencedCode.java` (seeds only where a call/jump reference proves
> code exists) or `core/ghidra/ClaimOrphanCode.java` (claims already-disassembled code)
> instead — both are on the supported path.

## diagnostics/

Small, single-purpose probes used interactively while reversing: range disassemblers
(`Disasm`/`DisasmF`/`DumpDisasm` — three near-duplicates), reference/xref lookups
(`FindRefsTo`, `FindCalXrefs`, `ScanCalIndexed`), function/state probes (`ProbeFn`,
`RegList`, `DumpAddrRegInsns`), and project-surgery helpers (`DeleteFns`, `CheckManifest`,
`DecompileAddrs`). Most are one screen of code; several are subsumed by supported tools
(e.g. `CheckManifest` by `DecompileAll`'s manifest reconciliation, `FindCalXrefs` by
`core/maps/extract_cal_xrefs.py`).

## handoffs/

Task briefs written to hand a specific investigation to a fresh session — each states what
was already established, what to build on, and which addresses to start from. They are
historical working documents, not current documentation: the state they describe is the
state at the time of writing, and none was revised afterwards. Useful as a record of how a
line of investigation was framed; read `ecus/<ecu>/maps/` for where it landed. Note the handoff
prompts below instruct writing findings back into a per-ECU `RESULTS.md` log; that convention has been
retired for simos85, whose results are now organised by topic rather than chronologically.

## openpilot/

`analyze_decel_fault.py` — decodes ESP/TSK/ACC CAN signals from comma openpilot drive logs
(`rlog.zst`) to study the on-car −3.0 m/s² decel clamp. Takes segment paths as arguments and
needs an openpilot checkout for `cereal/log.capnp` (`$OPENPILOT`); the drive logs it was
written against are private, so supply your own. Kept as a record of how the on-car evidence
in the decel-limit documentation was gathered.
