# Handoff: find the non-analyzed ACC coordinator by its CODE SIGNATURE (behavioral disassembly sweep)

You are continuing a reverse-engineering effort on a **Continental Simos 8.5** engine ECU
(Audi Q5 3.0 TFSI, `8R0907551F`; Infineon **TC1796**, TriCore 1.3, little-endian, load base
`0x80000000`). Image: `ecus/simos85/firmware/8R0907551F_Original.bin` (2 MB OBD read; gitignored
symlink, present locally). Env: `source `.env.sh` (`GHIDRA_HOME`=Ghidra 12.1.2,
`JAVA_HOME`=JDK 21). Ghidra project `ecus/simos85/ghidra_proj/Simos85`, program
`8R0907551F_Original.bin`. Decompiles in `ecus/simos85/analysis/decompiles_r/<addr>.c` (3375 fns,
"100% decompiled" — so the target is almost certainly ONE of these functions, just **unlinked**).

## The target and why static xref fails
There is a **longitudinal ACC coordinator** that: reads the commanded accel, reads the fixed **−3.0
m/s² deceleration-limit curve at `0x8004dd90`**, **clamps** the decel, writes the **TSK_02 (0x10C)**
brake output (`TSK_Verzoeg_Anf` decel + `TSK_Radbremsmom` torque), and on the clamp sets+latches
**`TSK_04` (0x10E) `TSK_Status_GRA_ACC_02 = 3`** (key-cycle to clear). This is confirmed on-car and is
the code that holds the accel/decel/**jerk (internal accel-rate)** limits openpilot needs.

It is "non-analyzed" because it is function-pointer/interrupt scheduled and uses **computed /
cal-relative pointers for everything** — the accel input, the `0x8004dd90` cal (via a map-descriptor),
the TSK output shadow, and the status write. Every static ANCHOR method has been exhausted and returns
empty: `FindRefsTo`/data-xref (verified working on other addrs), call-graph edges, absolute-pointer
scan into `0x8004dd90` at all aliases (`0x80…`/`0xa0…`), file-offset scans, and a runtime RAM scan
after boot (the dispatch table / resolved cal pointer are not materialized because the ACC subsystem
never activates in emulation). **So you cannot find it by references. You must find it by its behavior
— its control-flow / instruction SIGNATURE — because the CODE is in flash even though it is unlinked.**

## The decel cal block (your anchor for signatures) — `0x8004dd90`
Three separate N-headed s16 blocks, 0x10 apart (a Continental Kennlinie split into axis + functional +
L2-monitor copies):
- axis  `@0x8004dd90` = `{N=6, 4370, 9170, 13970, 15570, 17170, 20370}`  (s16; hex `0x0006, 0x1112, 0x23D2, 0x3692, 0x3CD2, 0x4312, 0x4F92`)
- funcY `@0x8004dda0` = `{N=6, -1500, -650, -600, -400, -313, -250}`     (×0.005 = `-7.5,-3.25,-3.0,-2.0,-1.565,-1.25`; hex `0x0006, 0xFA24, 0xFD76, 0xFDA8, 0xFE70, 0xFEC7, 0xFF06`)
- monY  `@0x8004ddb0` = identical copy of funcY (EGAS level-2 monitor). **−3.0 = −600 = `0xFDA8`.**

## The SIGNATURES to hunt (ranked by distinctiveness)
1. **L2 symmetry monitor (MOST distinctive).** Somewhere a function reads corresponding elements of the
   **functional block (`…dda0`) AND the monitor copy (`…ddb0`)** — two locations exactly **0x10 apart**
   — and compares them (equality/tolerance), raising `LV_SYM_ERR_DECE_CTL` on mismatch. Normal code
   reads ONE table; a dual-read-of-two-copies-0x10-apart + compare is rare. This monitor also **very
   likely runs at init / cyclically as an integrity self-check, NOT gated on ACC-active** — so it is
   the easiest to catch (see technique #1 below).
2. **s16-axis interpolation + clamp.** Binary-search over the axis `{N, x[N]}`, linear-interpolate
   `y0 + (x−x0)*(y1−y0)/(x1−x0)` on the value block, then **max()-clamp** the accel command against the
   result (the decel floor). The interpolation arithmetic (a mul + a divide/shift for the fraction) is
   a recognizable instruction cluster. NOTE the known interpolators `calculate_interpolated_value_801f0f88`
   / `_801f0914` (s16-axis) expect a CONTIGUOUS `{N,x[N],y[N]}` block; the decel table is three
   SEPARATE blocks, so the reader either calls the index-helper on the axis and does its OWN interp on
   the two value blocks, or uses a FIXED index (idx 2 → −600). Check both patterns.
3. **Status latch.** Writes fault code `3` to a status byte and sets a **latched/persistent** error
   flag (cleared only on reset / `LV_ERR_DECE_CTL_EMS`, FR ch.48.54 "init at reset clears FMY"). Look
   for `mov d,#3` / `st.b …,#3`-equivalent into a status that also drives a non-volatile/error store.
4. **Map descriptor.** The Kennlinie is referenced by a descriptor encoding the three-block layout
   (`{N=6, three cal-relative offsets 0x10 apart}` or `{base, stride 0x10, dims}`). No ABSOLUTE pointer
   to the table exists, so the descriptor holds **cal-relative offsets** — search data for a triple of
   values `0x10` apart, or `0x8004dd90`'s offset from a plausible cal base (try bases `0x80040000`,
   `0x80000000`, and the `a0/a1` data-base regs) in u16/u32 form and `>>1` (s16-index) form.

## Techniques (do #1 first — it is the cheapest and highest-odds)
**1. Emulator read-watch on the decel cal region — catch the L2 monitor at boot.**
`core/ghidra/EmulBoot.java` boots the firmware to steady state (validated; read it). It has an
instruction-level READ-WATCH: every load whose effective address lands in a watched window is logged
with the reader PC + function. **Point it at `0x8004dd90–0x8004ddbe`** and run a full boot
(`arg6=1` full-init) — if the L2 integrity monitor (or any curve reader) executes at init/cyclically,
you get the reader PC for free, which IS (or calls) the coordinator/monitor. To do this: in
`EmulBoot.java` change the read-watch predicate (search for `RD-ACC` / the `ea>=0xd000d5c0` test) to
`ea>=0x8004dd90 && ea<0x8004ddc0`, remove the `injected` gate so it watches from step 0, and run:
```
"$GHIDRA_HOME/support/analyzeHeadless" ecus/simos85/ghidra_proj Simos85 -process 8R0907551F_Original.bin \
  -noanalysis -scriptPath core/ghidra -postScript EmulBoot.java 80021140 12000000 0 0 -1 0 1
```
grep the log for the read-watch line. (Note: cal at `0x8004…` may be accessed via the non-cached
alias `0xa004dd90` at runtime — watch BOTH `0x8004dd90` and `0xa004dd90` windows.) Also add a
read-watch on the FUNCTIONAL-vs-MONITOR pair specifically (`…dda0` and `…ddb0`) and flag any PC that
reads both within a short step window = the symmetry monitor.

**2. Force-disassemble all flash + grep for the signatures.** `core/ghidra/DisasmF.java <startHex>
<endHex>` force-disassembles a range (plain `Disasm.java` only prints already-defined instructions).
Dump code regions and grep the asm for: (a) two `lea`/`addsc.a` that produce addresses `0x10` apart
feeding a compare (signature #1), (b) the interp mul+divide cluster near a `min`/`max` (signature #2),
(c) `#3` stored to a byte that also touches an error/latch store (#3). Cross-check candidates against
the decompiles.

**3. Grep the decompiled corpus for the behavioral shape.** In `decompiles_r/`, search for functions
that: read two same-typed arrays and compare element-wise (monitor); OR do a binary-search +
interpolation + clamp; OR write a status `= 3` and set a persistent flag. The immediates `−600`
(`0xFDA8`) / the axis values may appear if a fixed index or bound is hardcoded (low odds — grep anyway:
`0xfda8`, `0xfd76`, `0x3692`).

**4. Descriptor + interpolator callers.** List callers of `801f0f88`/`801f0914` (s16 interpolators) and
`find_previous_index@0x800a2bd0` and check whether any handles an accel/decel-scaled map; and search
data for the map descriptor per signature #4.

## What to deliver
- The **code address** of the coordinator (and/or its L2 monitor twin), force-disassembled / added as a
  Ghidra function, with the decompile.
- From it: the **positive-accel limit**, the **−3.0 decel clamp mechanism** (fixed index vs the curve,
  and what selects the index), and the **internal jerk / accel-rate limit** — the four limits openpilot
  needs. Log evidence (decompile lines + any emulator read-watch PC) as a new UPDATE in
  `ecus/simos85/maps/RESULTS.md`; commit new/edited scripts under `core/ghidra/`.

## Ground rules
- Static + emulation only; do NOT rely on on-car testing for this task (a separate on-car XCP/UDS
  dump track exists — don't block on it).
- Be honest about negatives; this approach is explicitly **low-odds** because computed pointers hide the
  specific addresses — if the signature grep comes up empty, say so and note that the emulator read-watch
  (technique #1) or the on-car dump are the higher-confidence routes.
- Read `EmulBoot.java` and `maps/decel_limit_flow.md` fully before starting; prefer reading the bin /
  decompiles over guessing.

## Key files
- `core/ghidra/EmulBoot.java`, `core/ghidra/DisasmF.java`, `core/ghidra/FindRefsTo.java`.
- `ecus/simos85/maps/decel_limit_flow.md` (the decel curve + prior static-closure evidence, incl. the
  `ScanCalIndexed.java` result that no analyzed fn names the table), `ecus/simos85/maps/RESULTS.md`
  (UPDATES 18–32), `ecus/simos85/analysis/ACC_COORDINATOR_HANDOFF.md` (the parallel "run it in
  emulation" approach; complementary).
- `ecus/simos85/analysis/decompiles_r/801e9b86.c` (the ACC supervisor — the ONE linked consumer of the
  accel mirror `d000d606`; useful for context and for the cal-struct field conventions).
