
## FOLLOW-UP (2026-09-03) — object table PINNED to 0x40a1a8; builder = multi-phase COM init
Emulation fork proved *0x4069b4 = **0x40a1a8** (the object table's fixed RAM address). Builder chain
(read via Ghidra): object-table-head literals 0x40a1a0/a4/a8 loaded by FUN_0008db80 (+ 0x93234/0x9a698/
0x9fa80). **FUN_0008db80** = a COM-init phase: iterates the table (FUN_0008dac0), runs the bump allocator
FUN_0006b936 (THUMB), then finalizes pointers (*0x40a1a4 = table_end - 0x40a1a8). FUN_0009e3f4 READS the
table (*ptr+handle*0x10, fields +0/+1/+4/+0xd). So the table is populated across multiple init phases from
the .rodata config; materialization needs DRIVING that multi-phase config-dependent init - which is where
3 emulation forks stalled (600s watchdog on the heavy per-message registration loop).
STATUS: emulation is the right path and pinned the table address, but full materialization needs a careful
INCREMENTAL local harness driving each init phase with seeded config roots (not a one-shot fork - they
stall). CLEAN ALTERNATIVE now precisely targeted: a bench RAM read of **0x40a1a8** (few KB) yields the
whole object table incl EPB handle 0x25b -> settles H1/H2 directly.

## SESSION 2 (2026-09-19) — walker+dispatcher co-run cracked to the command-queue stage
Reproducible in `emu/objtable_corun.py`. Advances the object-table build materially past prior
one-shot forks:
- **Dispatcher `FUN_0008df52` is Thumb** (prior loops ran it as ARM = garbage). Gate to run a
  builder op: `*0x406aa0==0 && *0x4092e0==0 && *0x4069e5==1 && *0x4069e7==0 && *0x4069e4!=1 &&
  phase *0x406aa4==1`, then `switch(*0x4069a8)`: 0xd3 registrar / 0xd4 alloc / 0xdd phase /
  0xe0 populate / … — VERIFIED each command branches into its builder.
- **Walker `FUN_00049f38` (ARM)**: main body at `0x4a060` (entered when `*0x4069e3!=1`), needs
  `*0x4069e2==1` (record-ready) and reads the 14-byte record staged at cursor `0x406980`. Per
  record: `[4]==0xff`→header→`0x40699c`; `[4]==0xdc`→alloc cmd; else→copy `record[0:0xc]` to
  dispatch staging `0x4069a4` + set `*0x4069e5=1`, then (next pass) alloc+emit into the command
  queue struct `0x408ba8`. Tail state machine on `*0x406a04`/`*0x408ba0..ba1` calls the sizer
  `com_objtable_alloc 0x8e3d0` when `*0x408ba1==0x14` (config via `0xbd6c4`).
- **`FUN_00049e48/49e80` are 16-bit byte-swap helpers** — config half-words are byte-swapped on
  read (the 0xa7e14 stream is a byte-swapped, variable-length TLV — a fixed 14-byte step misaligns).
- **Record source** `FUN_0008e4f4(len≤14, ptr)` stages a record + sets `*0x4069e2=1`; its iterator
  is RAM-wired (no static caller), so records must be fed by us.

Remaining (scoped in the script docstring): (1) bridge the walker's command queue `0x408ba8` to the
dispatcher's staging `0x4069a4`; (2) sequence the 2-phase-per-record + tail state so records advance
(currently ~1 record then stalls on consume/ack); (3) parse the `0xa7e14` TLV with per-type lengths +
byte-swap. NB: materialization yields ROUTING (container id→signal 0x046f→0x408f10); the NM *content*
to pass `FUN_00040950` node-id/mask validation is a separate need (real sensor-cluster payload/capture).

## SESSION 2 cont. — walker per-record phase trace (single record)
Traced one staged record through repeated walker calls (emu/objtable_corun.py trace):
- **pass A** (`*0x4069e5==0`): copies `record[0:0xc]` -> dispatch staging `0x4069a4`, sets `*0x4069e5=1`.
- **pass B** (`*0x4069e5==1`): calls `com_objtable_alloc 0x8e3d0` once, then emits a queue job at
  `0x408ba8` = {`+0xc`: tag `0x0200` (byteswap of 2), `+0xe`: `record[2]` handle, `+0x10`: `0xfe`
  marker, `+0x11`: `0x10`} and sets ready-flag `*0x408ba0=1`. Walker state `*0x406a04` becomes
  `0x1000000`; internal counter `*0x408ba1` starts incrementing.
- **passes C+**: `*0x408ba1` just increments (0x01,0x02,…0x0c…) and nothing else happens — the
  build STALLS. The tail allocation (`com_objtable_alloc` when `*0x406a04==0 && *0x408ba1==0x14 &&
  *0x4069e6==1`, config via `0xbd6c4`) never fires because `*0x406a04` is `0x1000000` (not 0) and
  `*0x408ba1` never reaches `0x14`. The bump pointer `*0x4069b0` does NOT advance and 0x40a1a8 stays
  empty — `com_objtable_alloc` returns without allocating (a precondition is unmet).

Interpretation: the walker is a large multi-phase byte-swapped interpreter whose per-record work is
gated by internal state (`0x406a04`, `0x408ba0/ba1`, `0x4069e4..e7`) that the FULL startup sequences
across many records + a header (`type 0xff` -> `0x40699c`) record first. Driving it needs (a) feeding
the correct VARIABLE-LENGTH record sequence — the record iterator that calls `FUN_0008e4f4` reads the
`0xa7e14` TLV with per-type lengths (RAM-wired, not yet replicated), and (b) not letting `0x406a04`
latch to `0x1000000` (find/clear the writer, or run the missing phase that resets it to 0 so the tail
alloc fires). This is the concrete remaining work; it is a multi-step effort, not a one-shot.

## SESSION 2 cont. — dispatcher disassembled + walker/dispatcher command-space split
Disassembled both engines directly (not decompile) — key structural facts:
- **Dispatcher `FUN_0008df52` (Thumb)** switches on `*0x4069a8 - 0xd3` via a **0x2c-entry jump table**
  at 0x8dfdc (commands 0xd3..0xfe). Gate (confirmed by disasm): `*0x4092e0==0 && *0x406aa0==0 &&
  (*0x4069e4==1 || *0x4069e5==1) && *0x4069e7==0 && phase *0x406aa4==1 && *0x4069e4!=1` (e4==1 diverts
  to phase-0 setup). A `*0x4069e1` **bit3** test can bypass the range pre-check. Command byte =
  `staging[4]` at `0x4069a8`; staging is `0x4069a4`.
- **Command source is NOT a flash record array.** Scans for stride-N records with byte4∈{0xd3..0xfe}
  hit only ARM veneer code (e.g. 0xa2750 = `e59fc000/e12fff1c` ldr/bx thunks). The `0xa7e14` records
  have byte4=0x00/0x09. So the `0xd3+` commands are **runtime-generated** by the walker, not stored.
- **Walker emits STATE codes, not dispatcher commands.** The small values (2,8,9,6,4) it computes are
  written to `*0x406a04` (walker next-state) at 0x4a3f4 — they are NOT the 0xd3+ dispatcher command.
  Its queue at 0x408ba8 (tag/handle/0xfe) and counter 0x408ba1 are internal bookkeeping.
- **Record-construction helpers** at 0x4a41c / 0x4a450 build records at `0x406990` (memset 0xc,
  byteswap tag, byte4=0xff header / tag 1/2). `com_objtable_alloc 0x8e3d0` and the byteswap
  `0x49e48/0x49e80` are the shared primitives.

**The one unresolved link**: how the walker's parse of the high-level config becomes the `0xd3+`
dispatcher command stream in `staging[4]`. The walker copies `record[0:0xc]->staging` (so
`staging[4]==record[4]`), yet no located config has `record[4]∈{0xd3..0xfe}` — so a walker phase (or
the RAM-wired iterator) must WRITE the 0xd3+ command into `0x4069a8` from the parsed config +
allocation result. Finding that write is the next concrete step; it is the crux of materialization.
This is a large multi-stage interpreter — closing it is a dedicated effort, not a one-shot.

## SESSION 2 cont. — DEFINITIVE blocker: config iterator is boot-installed RAM dispatch
Ran option (1) — hunt the 0xd3+ command source — to ground. Findings:
- The dispatcher command = `staging[4]` = `record[4]`; a record with `record[4]∈{0xd3..0xfe}` IS a
  builder command (walker "else" path copies it to staging). Dynamic watch confirms NOTHING else
  writes `0x4069a8` — not phase-0 setup (0x931e8), not the builders, not the dispatcher.
- So the 0xd3+ command stream can only come from records the iterator feeds via `FUN_0008e4f4`.
- The iterator is reached only through thunks (`FUN_000954ce -> FUN_000a1cbc -> FUN_0008e4dc`,
  `FUN_000a1cac -> FUN_0008e4f4`) that have **no static caller** AND **no stored function pointer
  anywhere in flash** (searched 0x954ce/a1cac/a1cbc/e4f4/e4dc as ARM+Thumb pointer values → zero
  hits). They are invoked via RAM function pointers the boot code **computes PC-relative and stores
  at init** — the project-wide object-table wiring, confirmed here from a new direction.
- The config header (`type 0xff` record -> `0x40699c`) is internal walker bookkeeping, not a config
  root pointer (only the walker references `0x40699c`).

**Conclusion**: the object table cannot be materialized by driving isolated pieces — the record
iterator only runs once the boot init has installed the RAM dispatch pointers. The single viable
software route is therefore the **full boot init under a peripheral-model harness** (skip the absent
SBOOT/crt0 context, call the init directly, and stub the CAN-controller status + OS-tick MMIO that
`FUN_0009d2d6` and the startup wait on) so the real init installs the dispatch and the config
processing runs to completion. That is a substantial emulation-engineering task (a bounded SoC
peripheral model), not achievable by more static/isolated poking. Alternative: a bench RAM read of
`0x40a1a8` after the ECU boots, or a real private-CAN capture (decoded with the recovered node-ids).

## SESSION 2 — FINAL: option 1 (emulation) is architecturally blocked (SBOOT context absent)
Pushed the emulation route to ground and independently confirmed the prior RE conclusion
(`asw_start_sboot` @0x8f440, `com_obj_table_base_ptr` @0x4069b4):
- The config-processing iterator is reached only via thunks (954ce/a1cbc/a1cac/e4dc/e4f4) with NO
  static caller and NO stored function pointer in flash (searched all forms) — the dispatch pointers
  are **computed and installed by SBOOT/crt0 at boot**, and that context is ABSENT from the ASW image
  (0x0–0x134011). `_start` (0x8f440) uses SBOOT monitor SVCs (#0x13–0x16) that can't run bare.
- Therefore full COM-init cannot be bootstrapped from this image by any isolated/partial drive.

### The circular dependency (the real wall)
operational  ← needs NM container msg  ← needs container CAN-id  ← needs object table 0x40a1a8
object table  ← (a) emulate COM-init  = BLOCKED (SBOOT context absent)
              ← (b) bench read via UDS 0x23 = BLOCKED (SecAccess + Dcm, needs operational)
              ← (c) enter SBOOT to read     = BLOCKED (programming session via Dcm, needs operational)
Every software/bench-injection path loops back through the operational wall.

### What breaks the circle (only external inputs)
1. **Real CAN capture** of a running B8 Q5 private chassis/sensor CAN (or power the G419 sensor
   cluster on the bench) → the container frame + CAN-id directly. Decode with the recovered NM
   node-ids {0x4a,0x5f,0x98,0x99,0x9a,0xd4} + the 0x060 CRC-8/J1850. FASTEST.
2. **Hardware read** (JTAG/BDM/boot-pin into SBOOT, or die read) → dumps RAM 0x40a1a8 / flash
   directly, bypassing all Dcm/ComM gates. Needs the debug port open or a boot-strap trigger.
The pure-software / bench-injection approaches are exhausted; these external inputs are required.
