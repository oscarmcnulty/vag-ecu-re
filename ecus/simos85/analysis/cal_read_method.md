# Simos8.5 calibration-read mechanism (how code reads cal, and how to trace it)

Reverse-engineered on the clean `reproduce.sh` project (a1=cal base **0x80048000**, a0=RAM
0xd0008000). This is the general method; it unlocks tracing most cal usages. Validated on real
descriptors (below).

## The three cal-read paths

### Path A — scalar constants: `*(a1 + imm)`
Simple `C_*` constants are read as an immediate displacement off a1. Ghidra's constant
propagation (after `SetBaseRegs`) **creates a data reference**, so these are directly traceable:
- `FindRefsTo.java <addr>` lists reader instructions+functions (verified: 0x800456c0
  `C_VS_MIN_CRU_MON` → 3 reads in `egas_l2_monitor_cal_init@800a0c9c`).
- or grep `analysis/decompiles_r` for `DAT_8004xxxx`.
This accounts for the ~840 folded cal refs.

### Path B — Kennlinien (1-D maps/curves): interpolation helper + inline block
Curves are read by a lookup helper that takes a **pointer to an inline block** and an input value:
```
block layout (all s16, little-endian):
  [0]      N               (number of points)
  [1..N]   x_axis[N]        (monotonic increasing)
  [N+1..2N] y_values[N]
helper: linear_interpolation( block + 2 + 2*N ,  interp_index_from(x_axis, input) )
```
Helpers: `process_input_with_offset`@801f0cd4, `process_input_data`@801f0d0c,
`calculate_interpolated_value_801f0f88 / _801f0914`, `linear_interpolation`.
**Validated** on `801e9b86`'s call `process_input_with_offset(0x8007a204+0x24, input)` →
block @**0x8007a228**: N=6, x=[0,23,6857,9600,10971,13714] (monotonic ✓),
y=[4200,4200,4200,3700,3000,3000]. Decodes cleanly.

### Path C — how the block pointer is obtained: cal-struct pointer tables
The block/scalar pointer is `cal_struct_ptr + fixed_offset`. `cal_struct_ptr` is an entry in a
**cal-struct pointer table** — a run of **0xa0-aliased absolute pointers** into cal (mask
`& 0xdfffffff` to get the 0x80… cached form). Consumers do `iVar = DAT_80090fxx;` then
`*(iVar + off)` (scalar) or `helper(iVar + off, input)` (curve).

**13 pointer tables found image-wide** (scan flash for ≥3 consecutive 4-aligned cal pointers):

| table vaddr | n | cal-struct bases |
|---|---|---|
| 0x8008120c / 0x80081220 | 3 | 0x80055630 |
| 0x80081360 / 0x80081374 | 3 | 0x800556b0 |
| 0x8008a660 | 5 | 0x800791e8..0x800792e8 |
| 0x8008a7e0 | 7 | 0x80078bbc..0x8007901c |
| 0x8008a804 | 5 | 0x80078bb0..0x800791b8 |
| 0x8008a95c … 0x8008a9fc | 9,9,9,9,20 | 0x8006dec4..0x8006f5e4 |
| **0x80090f78** | 17 | 0x80079398..0x8007a4dc (ACC/cruise cluster) |

## Reusable tracing technique
1. Enumerate a pointer table (or all 13); each entry = a per-module cal-struct base.
2. `FindRefsTo.java <ptr_var_addr>` → the **consumer function** that loads it. Example — the ACC
   cluster (table 0x80090f78) resolved to:
   - 0x80090f88 → `update_control_flags`@801e6d54
   - 0x80090f94 → `cruise_torque_pi_controller`@801e9b86
   - 0x80090f9c → `copy_calibration_data`@801eaea8
   - 0x80090fa8 → `update_status_flags`@801eecfc
   - 0x80090fb4 → `update_engine_control_parameters`@801f0204
   (Directly-loaded pointers get a ref; entries read by table *iteration* don't — for those, find
   the init/iterator that walks the table.)
3. In the consumer, `struct_base + offset` = the cal address; if the offset is passed to a Path-B
   helper, decode the `{N,x,y}` block at that address.

## Tooling: `core/ghidra/ResolveCalReads.java` (symbolic p-code pass)
Per-function `SymbolicPropogator` (a0/a1/a8 seeded from program context) resolves the effective
address of every ld/st/lea and, for hits in [0x80040000,0x80080000), writes a row
`function,insaddr,rw,caladdr,mnemonic` (rw = R load / W store / P lea-pointer).

**Reproducible from the bin** (no committed derived data — same model as `decompiles_r` /
`callgraph_*.csv`): `reproduce.sh` **step 6** runs it → `analysis/cal_reads.csv` (gitignored,
regenerable). Standalone: `analyzeHeadless ghidra_proj Simos85 -process <bin> -noanalysis
-scriptPath core/ghidra -postScript ResolveCalReads.java analysis/cal_reads.csv`
(add `0x<addr>` args to restrict to specific functions; omit the path to print to stdout).

Aggregate to a consumer view with a one-liner, e.g.:
`awk -F, 'NR>1&&$3!="P"{a[$1]=a[$1]" "$4} END{for(f in a)print f, a[f]}' analysis/cal_reads.csv`

**Image-wide result: 1742 accesses, 293 functions, 395 distinct cal scalars — all in
0x40718..0x48000 (a1-NEGATIVE offsets).** Hottest scalar 0x80043bc6 is read by 161 functions
(a global config/state byte). Top consumers e.g. `update_control_flags_800dc00c` (28),
`process_ecu_data_800f800e` (27).

**What this reveals — cal is split into two regimes:**
- **0x40000–0x48000 (Path A, "hot scalars")**: read `a1`+negative-immediate. Fully mapped by the
  pass + the CSV. This is the fast-access scalar block.
- **0x48000+ (interpolation maps/curves)**: NOT read by `a1`+immediate, so absent from
  `cal_reads.csv`. **These are traced instead by `core/ghidra/TraceMapCalls.java`** (map-lookup
  framework pass) → `maps/map_calls.csv`, which resolves the map data-ptr + axis args passed to
  every interpolator. Join to the tuner-diff blocks with `maps/gen_map_consumers.py`.

  **CORRECTION (2026-07-12): the Path-C "pointer-table" theory was mostly wrong for these maps.**
  `TraceMapCalls` was extended to follow each argument's decompiler pcode through
  `COPY/CAST/INT_ADD/PTRADD/LOAD` (a `LOAD` from a constant address reads the pointer value from
  program memory and normalizes the 0xa0→0x80 alias). Over the full 0x40000–0x80000 region it now
  resolves **~3984 map-arg addresses (vs 17 for the old constant-only scan)** — but **only 1 of
  those goes through a pointer-table load.** So the 0x48000+ maps use **inline-immediate addresses**
  (`movh.a`+`lea`/`addi`, sometimes via a cast/add the old pass couldn't fold), not the 13 pointer
  tables. The pointer tables (Path C below) are real but account for very few of the perf maps; the
  effective enhancement was pcode-following, not pointer-table seeding.

## Known exception: runtime-indexed cal arrays (e.g. the decel-limit table)
The decel-limit curve at **0x8004dd90** (see `../maps/decel_limit_flow.md`) is reached by **none**
of the above: no data ref, no absolute pointer anywhere in the image, not covered by any of the 13
pointer tables, no a1-relative u16 descriptor. Its layout is an axis block + two identical value
blocks (functional + monitor):
- axis @0x8004dd90 = [4370,9170,13970,15570,17170,20370]
- values @0x8004dda0 & @0x8004ddb0 = [−7.5,−3.25,**−3.0**,−2.0,−1.565,−1.25] m/s² (×0.005)
This is three N-headed s16 sub-blocks: axis `{6,x[6]}`@0x4dd90, functional `{6,y[6]}`@0x4dda0, monitor
`{6,y[6]}`@0x4ddb0. **CORRECTION (2026-07-05): the −3.0 is a FIXED ceiling, not speed-interpolated** —
on-car the engine output tracks the ACC command then hard-caps at exactly −3.000 and latches TSK_04=3,
and multiple examples clamp at the same −3.0 (a fixed limit, not a speed curve). The −3.0 is selected
by a selector that is constant in normal ACC operation (a discrete mode/profile idx, not vehicle
speed); the earlier "selector = speed / 0.005 km/h axis" reading is **withdrawn**. The byte-axis readers
`find_previous_index`@800a2bd0 / `read_map_descriptor`@800a2c48 cannot read this s16 table, and the s16
interpolators (801f0f88/0914) expect a contiguous `{N,x,y}` block, which this isn't — so the reader
stays non-analyzed. See `../maps/decel_limit_flow.md` (2026-07-05 CORRECTION).

**Static route now EXHAUSTIVELY closed** by `core/ghidra/ScanCalIndexed.java` (new). It runs
`SymbolicPropogator` per function with two detectors beyond `ResolveCalReads`: **REG** — any address
register a0..a15 resolving to a constant in a target window (catches runtime-*indexed* bases formed
by `addsc.a/add.a`+variable index, which `ResolveCalReads` misses because it only inspects the ld/st
operand base) — and **IMM** — any instruction carrying a signature immediate (a1-offset 0x5d90/…,
absolute 0xdd90/…). Image-wide over 3375 fns, **both `0x80` and `0xa0` aliases**, window ±0xe00 around
the table: REG(0x80)=0, IMM=0; REG(0xa0) hits only `update_ecu_state_8019571c` forming `0xa004cf24/
0xa004d180` — a *different* curve, not the decel table. So no analyzed function names the table by
constant/immediate/indexed-base in either alias, and it's in none of the 13 pointer tables and has no
aligned pointer anywhere in the image. ⇒ the pointer is supplied to the generic curve-reader family
(`find_previous_index`+`read_map_descriptor`@800a2c48 / `process_sensor_data_800a2f34`) by the ACC
decel coordinator in the runtime-context Com layer outside the analyzed set; its base is a
RAM-resident descriptor computed at boot/runtime. Confirm the value via UDS ReadMemoryByAddress or
edit-and-test (both functional+monitor copies).
