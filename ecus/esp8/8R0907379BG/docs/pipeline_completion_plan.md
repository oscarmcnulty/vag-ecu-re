# Plan: complete ESP8 decompilation via the standard pipeline

**Premise (correct):** every EPB/COM "wall" this pack hit is an *incomplete-decompilation* wall, not
a firmware limit. The runtime object table, the COM signal buffers, and the CAN/COM handlers all look
unreachable **because the decompiler is missing three kinds of information the pipeline is built to
recover** — and which the ESP8 `reproduce.sh` currently skips. A peer pack (`ecus/al551`, SH-2A TCU)
had the *identical* "boot-copied RAM pointer table" problem and closed it with the pipeline. We mirror
that, make ESP8 a full-pipeline citizen, reach ~full decompilation, then re-open EPB from a complete
corpus.

## Diagnosis: three completeness gaps → three existing tools

| Wall we kept hitting | Root cause (decompilation gap) | Pipeline tool that closes it | Precedent |
|---|---|---|---|
| Object table `0x40a1a8` / `*0x4069b4` → descriptors → buffers "not statically bindable"; EPB buffer runtime-allocated | **RAM-base indirection unresolved** — boot-populated pointer tables read as writer-less globals | `InitEmu.java` (emulate init stubs) → `ram_bases.csv` → `ApplyRamDataImage.java` (step 6c) | AL551 recovered 154 RAM pointer values this way (static deref mis-resolved 72/154 → emulation was authoritative) |
| CAN/COM handlers "reached only via function-pointer tables", computed calls unresolved | **fn-ptr dispatch not resolved** — table is raw DATA, no reference, target stays unlinked/undefined | `RecoverPointerTargets.java` (4d audit) + `ResolveDispatchTables.java` (10b) + `AuditIndirectBranches.java` (11b) | MED17 had 325 unresolved computed call sites |
| ~88% code-region coverage; some code in no function | **orphan / bracketed code not claimed** | `ClaimOrphanCode.java` (4b) + `RecoverBracketedCode.java` (4c) | MED17 recovered 621 KB + 144 KB |
| COM signal→RAM opaque | signal descriptors not decoded | `DecodeComBindings.java` (6b) — needs a Bosch-format variant, OR falls out of the RAM image | MED17: 560 bindings decoded |

The ESP8 `reproduce.sh` I wired in turn 27 does only import→split→analyze→createfns→applysyms→decompile→
coverage. It **skips 4b/4c/4d, 6b/6c, 10b, 11b** — exactly the steps that dissolve these walls.

## Phase 0 — make ESP8 first-class in the pipeline (small, enabling)
- Keep the mixed-ISA front end we built (`EspExportFns`/`EspCreateFns` + `EspSplit`/`EspFix`) — that
  part is ESP-specific and correct. The generic uniform-ISA `reproduce.sh` can't replace it.
- Extend `ecus/esp8/8R0907379BG/reproduce.sh` to run the **full standard tail** after `createfns`:
  4b/4c orphan+bracketed recovery, 4d pointer-target audit, 6b/6c bindings+RAM-image, 10b dispatch,
  11b indirect audit, then decompile + coverage. Add the matching `ecu.conf` keys
  (`CODE_RANGES`, `RAM_DATA_IMAGE`, `RESOLVE_DISPATCH`, `COM_DESC_CB`).
- Validate each generic core script runs on **ARM BE** (they were exercised on TriCore/V850/SH-2A). Any
  that assume a base-register model get an ARM guard, not a rewrite.

## Phase 1 — coverage recovery (cheap, do first) → get from 88% to ~99%
1. `ClaimOrphanCode.java` over `CODE_RANGES=0x0:0xa2000` — claim disassembled-but-function-less bytes.
2. `RecoverBracketedCode.java` (exclude `LOAD_IMAGE_RANGES` if any) — recover undefined+unreferenced
   code between flow terminators.
3. Re-export `function_entries.txt`; `bogus=0` is the validation that nothing was invented.
**Payoff:** the COM/CAN handler bodies currently invisible become real functions to decompile.

## Phase 2 — RAM data image = **the keystone** (materializes the object table)
This is the step that dissolves the central wall. Mirror `ecus/al551/analysis/gen_ram_bases.sh`:
1. **Identify the install stubs / builders** from the corpus: the COM-init functions that populate the
   object table + pointer arrays — `com_objtable_init_phase 0x8db80`, the bump allocator `0x6b936`,
   the queue/base initializers (`0x9313c/0x9a608/0x9fa4c` set `*ptr = 0x40a1a8`), and the per-message
   registrar. (AL551's `*_DAT_x = DAT_x` regex won't match a loop-builder — widen the selector to the
   functions that write `0x4069b0-fc` / `0x40a1a8+`.)
2. **Emulate them** with `InitEmu.java` (Ghidra's emulator) *with `.rodata` present and the config
   roots seeded* — running the **builders directly, not from `_start`, so the SBOOT boot-context wall
   does not apply** (that wall only blocks whole-boot emulation). Output `analysis/ram_bases.csv`
   (`ram_addr,value`): `0x4069b4→0x40a1a8`, the object-table records, the descriptor-array pointers,
   and the per-message signal buffers.
   - Fallback if `InitEmu` (Ghidra emu) can't drive the ARM builders: reuse our Unicorn harness
     (`emu/exp_*.py`, already ARM-BE working) to recover the same `ram_addr,value` rows — same CSV, same
     downstream. The turn-24 harness already runs `0x6b936`; finish the seeding and dump the table.
3. `ApplyRamDataImage.java ram_bases.csv` (step 6c) — initializes ONLY those pointer-table slots, adds
   the slot→target refs + pointer types. Now the decompiler resolves `*(0x4069b4)→0x40a1a8`,
   `object_table[handle*0x10+8]→descriptors`, and the descriptor `dest`→signal buffer.
**Payoff:** the object table is *in the project*. Handle `0x25b` (EPB) resolves to its descriptor and
buffers; `EPB_Verzoeg_Anf`'s buffer becomes a named address with real readers.

## Phase 3 — dispatch + pointer-target resolution (make the handlers visible)
1. `RecoverPointerTargets.java -n` (4d, report-only) → vet candidate fn-ptr-table handlers by hand,
   add confirmed entries to `function_entries.txt`.
2. `ResolveDispatchTables.java` (10b) → resolve computed call/jump targets (the CAN RX dispatch, the
   COM per-message routers) into real edges.
3. `AuditIndirectBranches.java` (11b) → measure remaining unresolved computed calls (the honest gap).
**Payoff:** the CAN-frame→handler and COM-router→signal edges become real call-graph edges; the
"handler reached only via a table" functions get incoming refs and decompile in context.

## Phase 4 — COM bindings annotation (readability + the last mile)
- With the RAM image applied, most signal buffers already resolve. Add an **ESP8 `DecodeComBindings`
  variant** (Bosch format: `com_signal_commit` `{value,src,bit,dest,len}` @0x4fee8; group table 0xb6a44;
  PDU descriptor 0xb6ffc) as step 6b to annotate `/* COM signal: bit N len M */` on each target.

## Phase 5 — iterate on a complete corpus → re-open EPB
Re-run `reproduce.sh` (now full). Then the EPB question is a **static trace on resolved code**:
`EPB_01 (0x104) → mailbox → handle 0x25b → object_table[0x25b] → descriptors → EPB_Verzoeg_Anf buffer →
readers`. Whichever function reads that buffer as a decel/pressure demand is the EPB channel (H1); if
nothing does, H2 is proven. Either way it's now answerable from the decompilation, no bench.

## Success criteria / validation
- Coverage: code-region in-function ≥ ~98%; `bogus=0` from `DecompileAll` on the recovered entries.
- RAM image: `ApplyRamDataImage` reports the object-table cluster initialized; a spot-check decompile of
  a table consumer (`FUN_0009e3f4`) now shows `0x40a1a8[...]` resolved, not `*PTR_DAT`.
- Dispatch: `AuditIndirectBranches` UNRESOLVED count drops materially vs the baseline.
- End test: `EPB_Verzoeg_Anf`'s buffer is a named address with ≥1 reader in the corpus.

## Risks / unknowns
- **InitEmu on ARM** is unproven (used on SH-2A); Phase 2 step 2 has the Unicorn fallback, so this is
  de-risked. The real hard part is **seeding the builder's config roots** — the same seeding that
  stalled the one-shot forks, but here it's bounded (a handful of roots from `.rodata`) and local.
- Some core scripts may assume a base-register/`gp` model absent on ARM — guard, don't rewrite.
- Keep the two-level `.gitignore` (added turn 27) so the enlarged derived corpus never enters git.

## Sequencing
Phase 0 + 1 first (enabling + cheap, immediate coverage win). Phase 2 is the keystone and the main
effort. Phase 3 compounds it. Phase 4 is polish. Phase 5 is the payoff. Each phase leaves the pack more
complete and is independently committable (metadata + scripts only).

---
## EXECUTION LOG

**Phase 1 — DONE (partial).** `ClaimOrphanCode 0x0-0xa2000`: **+106 functions / ~24.9 KB** of
dispatch-reached, function-less code recovered (8 passes, orphan-bytes=0 residual, failed=0). Manifest
re-exported: **3241 -> 3349 entries** (1283 ARM / 2066 Thumb). Wired into `reproduce.sh` as step 05b
(+05c re-export). `RecoverBracketedCode` deliberately NOT wired: it pseudo-disassembles UNDEFINED bytes
in the default ISA and would mis-decode Thumb as ARM -> needs an ARM-aware variant first.

**Phase 3 — the generic dispatch resolver does NOT work on ARM (finding).** `ResolveDispatchTables
--addrefs`: **370 computed sites, 0 targets resolved**. Cause: it seeds TriCore/V850 base registers
`a0/a1/a8` (absent on ARM) and relies on that model for target folding. `AuditIndirectBranches`: 370
computed sites, but ~288 are `bx lr` returns; the real dispatch is ~40 (`blx`/computed `bl`/`mov pc`)
through **RAM fn-ptr tables** -> unresolvable until those tables are materialized. => **Phase 3 is
downstream of Phase 2 on ARM**: the RAM data image must populate the fn-ptr tables first; then an
ARM-aware resolver (or the data refs from ApplyRamDataImage) links them. Reorder: 2 before 3.

**Tooling note:** the generic pipeline scripts are heavily TriCore/V850/SH-2A-oriented (base-register
model). ApplyRamDataImage is processor-agnostic (writes RAM values + refs), but the RECOVERY of the
values for ARM should use our Unicorn ARM-BE harness (emu/), not the SH-2A `InitEmu.java`. So ESP8
Phase 2 = Unicorn harness -> `ram_bases.csv` -> `ApplyRamDataImage` (step 6c).

**Phase 2 — NEXT (the keystone, the crux).** Deliverable: `analysis/ram_bases.csv` (object table
`0x40a1a8` records + descriptor-array ptrs + signal buffers) recovered by running the COM-init builder
chain under the Unicorn harness with `.rodata` present + constant roots seeded (`*0x4069b4=0x40a1a8`,
`*0x4069fc=msgcount`, `*0x4069b0=bump_init`). The open sub-problem is the **per-message REGISTRAR** that
writes `obj_table[i]={sigcount,descr_ptr}` from `.rodata` BEFORE the bump allocator runs -- still to be
pinned. Once `ram_bases.csv` exists, ApplyRamDataImage resolves the whole chain and Phase 3 + EPB fall out.

**Phase 2 — EXECUTED (partial win + a hard ARM finding).** Built `emu/capture_ram_bases.py` (AL551
pattern, ARM-BE via Unicorn): detects 318 self-contained pointer-install stubs from the corpus, runs
each in isolation, captures RAM pointer writes. Recovered **58 real pointer-table slots** ->
`analysis/ram_bases.csv`, incl the object-table base (`*0x4069b4 -> 0x40a1a8`), bump ptr, ANB/decel
calib ptrs (`0x403a18 -> flash 0xace66`), and internal object-table ptrs. `ApplyRamDataImage` initialized
22 blocks + refs. **BUT: the ARM decompiler does NOT auto-fold `*(ptr)->target`** even with the slot
initialized AND the block marked read-only (`EspRoRamPtrs.java`) -- unlike the TriCore/SH-2A decompiler
(base-register + const-pool folding), Ghidra's ARM decompiler reads `*PTR_DAT` as an opaque pointer var.
=> On ARM the RAM data image gives **navigation/structure** (0x40a1a8's contents are now known + in the
project) but NOT the automatic decompile resolution that dissolved the wall on the AL551 TCU. Two gaps
remain for EPB: (1) the per-message object-table RECORDS (`0x40a1a8+i*0x10`) are loop-built, not captured
by simple stubs -> need the registrar/loop-builder run; (2) ARM decompile folding -> needs data-typing +
re-analysis, or manual trace using the now-known 0x40a1a8 contents. So Phase 2 recovered the pointer
SKELETON (real, reusable), but the ARM decompiler limitation means it is not the clean auto-dissolve it
was on TriCore. Honest status: incremental, not the breakthrough.
