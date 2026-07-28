# Phase B notes — map extraction: the TriCore base-register blocker

> **Historical (pre-unlock) note.** This records the base-register blocker + its fix. The old cruise-min
> hypothesis below ("`C_VS_MIN_CRU` u8 ~30 km/h") is **superseded**: the operative floors are `C_VS_MIN_CRU`
> = 3.0 km/h (`0x8007a26a`, 1/128 km/h) and the L2 `C_VS_MIN_CRU_MON` = 15 km/h (`0x800794ef/f2`). See
> `cruise_control_flow.md` / `fr_alignment.md`. Kept for the base-register method + the map-engine unlock.

## What's done
- Symbols applied: Ghidra project now has **2058 named functions** + 4 labels
  (`analysis/symbols_merged.csv`, seed names override LLM where they overlap).
- `core/maps/extract_cal_xrefs.py` (text) and `core/ghidra/FindCalXrefs.java`
  (Ghidra resolved refs) both built and run.

## The blocker (expected, classic TriCore/Simos issue)
Both xref methods find only **~23 references** into the cal region. Reason: cal
data is accessed **base-register-relative** (`[a0+off]`, `[a1+off]`, `a8-0x26a8`),
and Ghidra doesn't know the runtime values of `a0/a1/a8/a9`, so it never resolves
`[a0+off]` to an absolute cal address. The decompiles show `a0 + -0xd4c`, not
`0x8004xxxx`. So neither text-grep nor Ghidra xref can see the map accesses yet.

## What the data-driven scan revealed
- A master **pointer/descriptor table** at file `0x8615c` (vaddr `0x8008615c`),
  **2285 pointers**, of which **572 distinct** target cal **`0x80064dc0–0x80069520`**
  (the HIGH-cal data class — likely axis arrays / a specific object class).
- The **performance tuner-diff blocks live in LOW cal `0x80040940–0x80058000`**,
  which the master table does NOT index. So the low-cal performance maps are
  reached `a0`-relative, not via that table.

## The unlock (next sub-task)
Resolve the TriCore base registers, then re-analyze. Standard procedure:
1. Find where `a0/a1/a8/a9` are initialized (startup code; `movh.a`/`lea a0,...`).
2. In Ghidra, `setRegisterValue` for those registers over the whole code range
   (or use the TriCore "set base register" context).
3. Re-run auto-analysis -> Ghidra resolves `[a0+off]` to absolute cal addresses,
   creating real references. THEN `FindCalXrefs.java` yields hundreds of map
   xrefs, and decompiles show `0x8004xxxx` instead of `a0 + -0xd4c`.

After that unlock both targets fall out directly:
- **Performance maps:** join resolved cal refs against the 50 diff blocks -> the
  consuming function for each tuner-modified map -> name via FR (TQI_MAX, boost,
  ignition, limiters in `fr_alignment.md`).
- **Cruise min speed:** the `C_VS_MIN_CRU` u8 (~30 km/h) becomes a resolvable cal
  byte; find the cruise-monitor function (reads vehicle speed, compares to a ~30
  constant; FR ch.14.16 p.2193) and read the value. Negative control: not in the
  tuner diff.

## Artifacts
- `maps/cal_xref.csv`, `maps/cal_ghidra_xref.csv` (sparse until registers resolved)
- `maps/diff_block_addrs.txt` (50 performance-map blocks)
- `maps/perf_block_to_descriptor.csv` (low-cal blocks vs master table: 8/50, confirms
  they're a different access class)
- `maps/fr_alignment.md` (FR-side targets for both goals)

---

## UPDATE: base-register unlock succeeded

`core/ghidra/FindBaseRegs.java` recovered (init at 0x80030cca, mirror 0x801deae8):
- **a0 = 0xd0008000** (RAM small-data base)
- **a1 = 0xa0048000 -> cached 0x80048000** = **calibration base** ([a1+off] reads cal)
- **a8 = 0x80088800**; a8-0x26a8 = 0x80086158 = the master pointer table @0x8008615c ✓

`core/ghidra/SetBaseRegs.java` set these as context + re-analyzed:
- cal references **23 -> 840** (461 distinct addresses). Function count 2069 -> 2171.
- `maps/perf_maps_consumers.csv`: 8/50 diff blocks map to a clean CODE consumer
  (e.g. 0x800449fc -> update_engine_control, 0x8004119e -> reset_ecu_state). The
  rest are either shared flag bytes (one block referenced by ~200 fns) or maps
  reached only through the kf/kl interpolation framework (pointer passed as arg).

### Remaining blocker for COMPLETE naming
Ghidra created the references but the **decompiler still prints `a1 + off`** (it
doesn't fold the register into a constant `DAT_80048xxx` in C output). So:
- consumer NAMES come from the reference manager, not readable C;
- cruise constant can't be pinned by reading C logic yet.

### Next step (the clean fix)
Make the decompiler treat a1 (and a0/a8) as a global constant base so C shows
`DAT_80048xxx`. Options: (a) set the register value via the decompiler's assumed-
register mechanism / a custom .pspec default; (b) post-process: a script that, per
function, rewrites `a1 + N` -> absolute, using the known a1 value. Then:
- grep resolved C for cruise speed compares -> C_VS_MIN_CRU exact addr + value;
- trace each diff-block map's interpolation call -> consumer + axes -> FR name.

### Cruise candidates (referenced cal bytes, value 20-40 km/h)
See scan: 0x80040a52=30, 0x80040bc2=31, ... but consumers are generically named
(annotation predates the unlock). Need the decompiler-fold step to disambiguate.
