# Plan: recover the UDS dispatch jumptables, `$27` seed/key, and flash window

`obd_read_feasibility.md` §6d leaves three structures unresolved because the diagnostic
layer dispatches through **RAM-resident function-pointer tables** that Ghidra reports as
"Could not recover jumptable … Too many branches." This is the plan to close them. It builds
on tooling the repo already has (`gen_tablemap.py` pointer sweep, `ResolveCalReads.java`'s
`SymbolicPropogator` pattern, `RecoverReferencedCode.java`, `EmulBoot.java`), and the
concrete anchors already recovered (below), so it's a running start, not a blank page.

## What we're recovering
1. **SID → handler + required session/security level** (the UDS service table).
2. **`$27` SecurityAccess** seed source, key transform, and attempt/delay limiter.
3. **The writable flash window** — the segment list the reflash path (`$34/$36`) will accept.

## Why static C alone failed (root cause)
The dispatch target is `*(context_ptr + offset)` where `context_ptr` is a **RAM** global set
once at init from a flash descriptor. The decompiler sees an indirect call through a
runtime-computed pointer with no provable bound, so it emits "Treating indirect jump as
call" and stops. The *data* (records + handler pointers) is real and in the image or
reconstructable; it's the **edge** that's missing. Recover the edge → the handlers become
ordinary functions.

## Established anchors (already recovered — start here)

**Diagnostic dispatcher `handle_diagnostic_request`@`800b3e6e`** — 2-level record table via
`DAT_d00005c8`:
```
base   = *(DAT_d00005c8 + 4)
outer  = base + (param>>8)   * 0x44      // 68-byte records, "service group"
inner  = *(outer+4) + (param&0xff) * 0x1c // 28-byte records, indexed by SID low byte
handler = (inner+8 == 1) ? *(inner+0x3c) : *(inner+0x1c)   // TWO fn-ptrs per record
```
- `DAT_d00005c8` is set by `801d8590` (`DAT_d00005c8 = param_1`) and zeroed by `801d864e`.
  **→ trace `801d8590`'s caller for the constant it passes = the table base.**

**Service-permission table `8002c65e`** via `_DAT_c03fc37c`:
```
tbl   = *(_DAT_c03fc37c + 0x10)   // record[0]=SID, *(tbl+1)=count, 4-byte records
mask  = *(_DAT_c03fc37c + 0x1c)   // per-service permission/state array
```
- Record `byte[3]` = the session/security attribute byte (`8002c54e`); the access gate
  `8002c3c4` returns NRC `0x11` unless the request's session/security bits satisfy it.

**Flash-config table `@0x800826c0`** (passed to flash driver `801f13b8`; read straight from
the bin — it's flash-resident, no RAM indirection):
```
0x800826c0: count = 5
            then segment records referencing sub-descriptors @0x80082654/0x8008265c,
            flash-op handler 0x800aa018, RAM staging 0xd400xxxx, magic 0x35ca6553.
@0x80082654: { handler=0x800aa018, link=0x8008264c, flags=0x00010006,
               bank_addr=0xafe00000, size_mask=0x0000ffff, sub=0x80082634/0x80082624, … }
```
`0xafe00000` is a TC1796 program-flash address → these records are the **bank/segment
descriptors** that define the programmable window. Fully decodable statically.

## Recovery strategy — four complementary techniques

### A. Static flash-descriptor decode (Python over the bin — cheapest, do first)
For structures that are flash-resident (the `0x800826c0` flash-config table, and any SID
table the init merely *points* at rather than *builds*): decode the records directly from
`firmware/8R0907551F_Original.bin` with a small script, exactly like `gen_tablemap.py`. This
alone should yield the **flash window** (target 3) and confirm record strides.

### B. Init-trace to pin the RAM table bases (get the descriptor the init copies)
The RAM contexts (`DAT_d00005c8`, `_DAT_c03fc37c`) are set from a flash descriptor at diag
init. Find the setters' callers and the **constant flash address** they pass:
- `FindRefsTo`-style write-xref (or grep the decompiles) for the assignment sites — already
  have `801d8590` for `DAT_d00005c8`; find who calls it and with what.
- Once the flash base is known, technique A decodes the 2-level `0x44`/`0x1c` record tables →
  the `{SID → handlerA/handlerB, access_byte}` map (target 1) and the permission table.

### C. `SymbolicPropogator` jumptable resolution → create refs → recover functions
A new headless pass modeled on `ResolveCalReads.java` (which already seeds `a0/a1/a8` and runs
`SymbolicPropogator` per function):
1. Seed the diagnostic context register(s) with the constants from B.
2. At each unresolved indirect branch (`800b3e6e`@`0x800b3e96`/`0x800b3ea0`, and the
   `8002c3c4`/`8002c65e` sites), resolve the table base + index range, read the pointer array
   from program memory, and **`addReference` from the branch site to each target**.
3. Run `RecoverReferencedCode.java` (already in `core/ghidra/`, and safe — it creates a
   function only where an incoming ref now exists, refusing erased/0x00 targets), then
   re-`DecompileAll`. The handler bodies — including the `$27` handler — now decompile as
   normal C, so target 2 (seed/key) becomes readable.

### D. Boot emulation as ground truth (for anything static won't prove)
The repo's stated "reliable new-function source" is runtime call-target logging
(`research/emulation/EmulBoot.java`, "call X → Y"). Boot-emulate far enough to run diag init
(so the RAM tables are built), then either read the constructed tables out of emulated RAM,
or drive a synthetic UDS request (`$27`, then `$23`/`$35`) through the diagnostic entry and
log the actual dispatch targets and the NRC path. This is the definitive check on A–C and the
way to observe the RAM tables as actually constructed.

## Per-target playbook

| Target | Route | Concrete output | Status |
|---|---|---|---|
| **1. SID→handler+level** | image-search for a confirmed handler ptr (`801229b4`@`0x80085f04`) → decode the 12-byte record grid @`0x80085e58` | 23-service SID→handler+attr table; `0x23`=NULL, `0x35`/`0x3d` absent | ✅ **DONE** → `uds_dispatch.md` |
| **2. `$27` seed/key** | decode `0x27` aux sub-table @`0x80085e38` → read the 6 subfn handlers | **not a seed/key** — condition/cal-gated state machine; nothing readable to unlock | ✅ **DONE** → `uds_dispatch.md` |
| **3. Flash window** | A (decode `0x800826c0` + `0x80082654` records) | cal + DFLASH/EEPROM; boot excluded; ASW not in reflash descriptor | ✅ **DONE** → `uds_dispatch.md` |

> Note: Technique B's name-led first attempt (`DAT_d00005c8` via `801d8590`) landed in a
> **GPTA** table (mislabelled `handle_diagnostic_request`), not UDS. The reliable route was
> searching the image for a pointer to a **behaviourally-confirmed** handler, bypassing the
> LLM names. `ResolveDispatchTables` (Technique C) was ultimately **not needed** for these
> targets, but is retained below as the general pass for the remaining GPTA/Com jumptables.

## New tooling to add
- `core/ghidra/ResolveDispatchTables.java` — the technique-C pass (parameterized by the
  context-pointer constants + the indirect-branch sites), emitting
  `analysis/dispatch_resolved.csv` = `site,context,table_base,n,targets…` and adding the
  references so `RecoverReferencedCode` + `DecompileAll` pick the handlers up. Wire it into
  `core/pipeline/reproduce.sh` as an optional step keyed on a new `ecu.conf` var (same pattern
  as `TRACE_MAP_CALLS`), so it's reproducible and skips loudly when undeclared.
- Extend `research/discovery/gen_tablemap.py` (or a sibling) with a `--records` mode that
  decodes strided record tables (`0x44`/`0x1c`/4-byte) given a base + stride, for technique A.

## Outputs & persistence
- New `analysis/uds_dispatch.md`: the recovered SID→handler+level table, the `$27` seed/key
  writeup, and the flash-window segment list — each row tagged with its evidence route (A/B/C/D).
- Recovered handler names into `analysis/symbols_merged.csv` with `source=re-trace` (they were
  confirmed via the dispatch edge, not guessed) — and fix the two known mislabels noted in
  `obd_read_feasibility.md` §6c (`800aa922` GPTA-not-UDS, `800a2c54` cal-indexer-not-memread).
- Update `obd_read_feasibility.md` §6d to point at the resolved results.

## Pitfalls (from `maps/dispatch_tables.md` and `RecoverReferencedCode.java`)
- **Targets aren't all function entries.** 20–43% of pointer-run entries are mid-function
  switch labels; do **not** bulk-create functions at every swept pointer. Only create at
  targets reached by a *resolved dispatch edge* (technique C), and let `RecoverReferencedCode`
  roll back any target whose body doesn't decode to `--min` bytes.
- **RAM vs flash.** `DAT_d00005c8`/`_DAT_c03fc37c` are RAM; you need the *flash descriptor*
  they're loaded from, not the RAM address itself. If the table is genuinely *constructed*
  (not just pointed-at) at init, technique D (emulation) is the only faithful read.
- **Erased flash decodes to plausible code** (0x00 → valid TriCore insns) — never blind-walk;
  the reference-seeded recovery is the safe path.

## Sequencing / effort
1. **A on `0x800826c0`** — pure Python, no Ghidra → flash window. ✅ **DONE — results in
   `uds_dispatch.md`** (writable window = calibration + DFLASH/EEPROM; boot sector in no
   descriptor; ASW banks in the geometry map but not the reflash descriptor).
2. **B → A on the `0x44`/`0x1c` tables** — trace `801d8590`'s caller, decode records → SID map.
3. **C (`ResolveDispatchTables.java`)** — the reusable pass; recovers the handler bodies incl.
   `$27` → seed/key.
4. **D (emulation)** — only if B/C can't pin a RAM-built table; also the end-to-end validation.

This closes §6d without changing its conclusion (there is still no `$23`/`$35` and no
CCP/XCP); it turns "in RODATA/RAM, unresolved" into a named, evidence-tagged table — and the
`ResolveDispatchTables` pass generalizes to every other "Could not recover jumptable" site in
the CAN/Com/ACC subsystem, which is the bulk of what static call-graph analysis still misses.
