# COM-init object-table build — architecture + why the CAN binding resists software-only (8R0907379BG)

Goal: bind the 4 decel channels (and EPB) to their CAN frames purely in software. The decel
channel buffers (comfort request `0x405462`, the ANB gate inputs, EPB `EPB_Verzoeg_Anf`) are
**bulk COM signals** whose RAM buffers are assigned at init by the object-table allocator, not by a
static flash table. So the binding runs through the object table `0x40a1a8` (`*0x4069b4`). This doc
records how that table is built and why neither static parsing nor bounded emulation reconstructs it.

## The build is a config-driven bytecode interpreter (mapped this session)
- **Dispatcher** `FUN_0008df52` (via wrapper `FUN_0008e0aa`, called from the 3 task loops
  `FUN_000219c0/21edc/223b0`). It is a cooperative state machine: it reads a **phase** int
  (`0x406aa4`) and a **command byte** (`0x4069a8`) from the COM-init control block `0x4069a4…`, and
  `switch`es the command to a builder op:
  - `0xd3` `FUN_000814c2` — registrar: writes `objtable[handle].descr[sig].+0xd = bytecount` from
    staging `{handle@+4, sig@+6, bytecount@+7}` (`0x4069a4…`), space-checked vs pool limit `*0xbda34`.
  - `0xd4` `FUN_00089f90` — per-message descriptor-array alloc.
  - `0xdd` `FUN_000892a0` — phase machine → runs the bump allocator `FUN_0006b936`.
  - `0xe0` `FUN_0008e298` — populate. (plus 0xd5/0xd6/0xde/0xdf/0xe1/0xe2/0xf1/0xf3/0xf5/0xf6/0xf9/0xfa…)
- **Object-table base** `*0x4069b4 = 0x40a1a8`; bump ptr `*0x4069b0`; a small header at `0x40a12c…`
  (recovered in `analysis/ram_bases.csv`, which also has the dispatcher **phase `0x406aa4 = 1`**).

## Why static enumeration fails
- The command stream is **not a flash table**. The command byte is fed by a **config walker** that
  reads the flash config (config root `0xa7e14`, per-handle lists `0xa7xxx` incl. EPB `0x25b`
  @`0xa7ba6`, signal-ID arrays `0xb2000–0xb3480` via index `0xb4600`) through **RAM base pointers**
  with **no code literal** — so xref cannot walk to it. Confirmed: the command byte `0x4069a8` has
  no init-time literal writer (its only literal writer, `FUN_000f929c`, is a post-init stats reuse
  of the same RAM); the config root `0xa7e14` has zero code-literal refs.
- The per-signal **byte size** the allocator needs is runtime-computed from signal bit-definitions,
  not tabulated (the long-standing "size source" blocker).

## Why bounded emulation fails (attempts this session, all negative — artifacts in emu/)
- `exp_objtable_materialize.py`: running each builder op in isolation (bases applied) → 0 writes;
  preconditions (registered staging) unmet.
- `exp_cominit_drive.py` / `exp_forceinit.py`: looping the dispatcher, even after forcing its entry
  gates (`0x4092e0=0`, `0x406aa0=0`, `0x4069e4=1`, phase 0) → phase advances 0→1 (via the phase-0
  setup `FUN_000931e8`) but the **command byte stays 0** and nothing populates: the command feed is
  a separate walker function that must run before the dispatcher, which the isolated loop never drives.
- `exp_taskrun.py`: running a full task tick (`FUN_000219c0`) with MMIO tolerated (harness maps
  unmapped pages, reads return 0, SVCs continue) → completes but builds 0 object cells: the table is
  built at STARTUP, and the startup init idles on hardware-readiness / orchestration state that reads
  0 under emulation.

## The precise remaining software-only step
Materialize `0x40a1a8` by driving the **full startup COM-init**, which requires: (1) identifying the
**config-walker command-feed** function (the one that reads the flash config via the RAM base
pointers and writes `0x4069a8`/staging each phase) and running it in lockstep with the dispatcher,
or (2) recovering that walker's RAM base pointers (extend `capture_ram_bases.py`) and its flash
config cursor, then statically replaying the interpreter. Once `objtable[handle]` resolves,
`objtable[0x25b]` (EPB) and the comfort/ANB handles give their buffers, and the decoded mailbox
(`decode/mailbox_map.py`, EPB `0x104↔0x25b` anchor) closes each channel to a CAN-id.

## Firmly established regardless
- Receive tables decoded (`decode/mailbox_map.py`): EPB = CAN `0x104` → handle `0x25b`; ACC_10 =
  `0x117`; **CAN `0x10d` is NOT in the receive filter `0xafae0`** (the pack's "comfort = ACC_05
  0x10d" needs revisiting; received comfort candidate is within `0x100–0x10c`).
- Comfort deserializer chain (seg2): `FUN_000f9948`→`FUN_000fa23c` → message block `0x40542c`,
  request `0x405462`; the deserializers are runtime-wired (no static pointer/branch to them).

---
## UPDATE (2026-09-05) — decel-source reframe + emulation-path results

### Reframe (verified): most decel authority is INTERNAL, not a received CAN value
Re-tracing the producers shows the ESP computes most of its decel demand itself; CAN mainly
supplies enable/freigabe gates, not the magnitude:
- **type4 / ANB is internal.** `anb_target_filter` (0x8390c) verified header: the ANB target decel
  is a PT1 filter over an **internal** input `0x407894` (computed by `FUN_0007da34` from ANB working
  values / wheels, `anb_decel_from_wheels` 0x7c1d4) — no frame-RAM read; `0x40926c/0x40926e` are
  private filter state, not received buffers. CAN provides the ANB enable/freigabe only.
- **type1 is internal** (assembled from status/plausibility flags).
- **type5 is inactive** (staging `0x403d6e` never written).
- **type2 / comfort is the one channel with a received CAN decel VALUE** — the request `0x405462`
  (control block `0x40545a`+8), deserialized by `FUN_000f9948`/`FUN_000fa23c` from received pool
  `0x405668`. Its buffer is object-table-allocated, so its CAN-frame binding still needs the table.

So "what the ESP actuates based on" is largely internal computation gated by CAN; the sole external
decel-magnitude input to arbitrate is the ACC comfort request (type2).

### Emulation path — why the object table won't materialize under the current harness
All in `emu/exp_*.py` (this session), all negative with a specific cause:
- **From `_start` (0x8f440):** returns immediately — crt0 hands off via SBOOT context that is absent,
  so main()/COM-init is never reached (`*0x4069b4` stays 0). (`exp_startup.py`)
- **Task tick `FUN_000219c0`:** diverges at the **3rd module fn `FUN_0009d2d6`** (MMIO wait / loop
  on peripheral status that reads 0) — only 2 of 53 task fns execute; the COM dispatcher (`0x8e0aa`,
  75th in the list) is never reached. (`exp_trace_tick.py`)
- **Auto-stubbing the diverging fns** corrupts control flow (returns early), still never reaching the
  dispatcher. (`exp_autostub.py`)
- **Dispatcher in isolation / forced gates:** phase advances 0→1 but no command is ever fed — the
  config walker only feeds commands within the full startup state machine. (`exp_forceinit.py`,
  `exp_cominit_drive.py`, `exp_init_seg2fix.py` — the last also maps seg2 at VMA=file+3, no change)
- **Cold-calling each of the 53 task fns**, write-watching the command byte `0x4069a8`: none feeds a
  command from cold RAM. (`exp_findwalker.py`)

### The one viable software-only route, precisely scoped
Materialize `0x40a1a8` by running the COM startup to completion under a harness that **models the
peripherals the init waits on** (the CAN controller `0xfff7exxx` mailbox status + timer/OS ticks) so
the task tick does not diverge at `FUN_0009d2d6` and reaches the COM dispatcher across ticks. That is
a bounded hardware-model (a handful of status registers returning "ready"), not a full SoC model —
identify the exact status bits `FUN_0009d2d6` (and the next few blockers) poll, return them set, and
let the cooperative COM-init run. Then `objtable[handle]` → buffers closes comfort (and EPB) to a
CAN-id via `decode/mailbox_map.py`.
