# The second code region above 0xa2000 — the COM stack that was hidden (8R0907379BG)

The pack's `CODE_HI=0xa2000` was too small. There is a **large second code region** — file
`0xbb045`–`0x105e61` (~230 KB, ~500 ARM functions + Thumb islands) — that the reproduce pipeline
excluded as DATA. It holds the AUTOSAR-COM signal-deserialization / RX-processing stack: the code
that turns received CAN frames into the signal buffers the app reads, including the 4 decel
channels. Because this code was never disassembled, every CAN-frame→buffer binding looked
"runtime/index-driven only" and prior sessions concluded (wrongly) that a bench dump was needed.
It is statically closable; the code was simply invisible.

## Proof (static, `decode/second_code_segment.py`)
- ARM prologues (`e92d….` with LR) and epilogues (`e8bd….` with PC) above `0xa2000` cluster at
  **file-offset residue 1** (500 each) — not residue 0 like the main segment. Coherent ARM
  disassembles only at that residue (e.g. file `0xfa239` = `e92d4ff0` = `push {r4-r11,lr}`, a real
  function that pops and returns 0x318 bytes later).
- **True VMA = file offset + 3.** Absolute references from seg1/config into this region resolve
  only with delta +3: `0x67ed0→0xbc5f8`, `0x10ce01→0x10002c`, `0x10ec5b→0x10071c` (each points at a
  real prologue at `value-3`). The +3 is a reconstruction shift introduced between the config
  tables and this region when the `.sgo` was unpacked; PC-relative branches are unaffected (they
  survive a uniform shift), and RAM data pointers are absolute.

## Integration (`EspSeg2.java`, wired into `reproduce.sh` as step 04b/04c)
Runs after `04_fix` (which clears code units in `0xa2000-0x110000`, so it must come after):
1. Split the DATA block at `SEG2_START=0xbb045`.
2. `moveBlock(+3)` so the region loads at VMA `0xbb048…` and ARM decodes 4-aligned.
3. Create a function at every ARM prologue (500, 0 failed).
4. `04c` re-analyzes so references from seg2 resolve — the CAN trace becomes a normal xref walk.
The two-block layout (seg1/config at delta 0, seg2 at delta +3) makes every cross-reference
resolve: seg1↔seg2 calls (PC-relative) and absolute RAM refs both come out correct.

## What it unblocks — the comfort (type2) channel, traced inward
With seg2 decompiling, the comfort channel resolves through the COM stack:
- Comfort CAN request = `0x405462` = **control block `0x40545a` + 8** (COM writes `dest+8`).
- Message block `0x40542c`; received-signal pool `0x405668` (per-message `0x1e0`-byte slots).
- Deserialized by `FUN_000f9948` (a 4-phase driver: phases 0-3 call `FUN_000f9bc8` / `FUN_000fa580`
  / `FUN_000fb328` / `FUN_000fa23c`; phase 3 `FUN_000fa23c` fills the comfort block from the pool
  and calls the commit helpers `FUN_000fb474` / `FUN_000fb3a0` with a signal handle).
- `decel_stage_writer` (0x57044, seg1) then reads `0x405462` → the comfort decel source
  (`decel_paths.md`).

## The remaining hop and why it is NOT a static pointer walk (established this session)
The last edge is COM-message → CAN-id. It turns out the ESP8 COM RX dispatch has **no static
representation to walk**:
- The per-message deserializer drivers (`FUN_000f9948` for comfort, and its 4 phase functions
  `f9bc8`/`fa580`/`fb328`/`fa23c`) have **zero references of any kind** in the whole 1.26 MB image —
  no absolute pointer, no direct `BL`, no `ADR`. They are invoked through **RAM function pointers
  wired at init by PC-relative computation**, so nothing in flash names them. Verified exhaustively.
- The deserializers hardcode their own control block / message block as literals (comfort =
  control `0x40545a`, block `0x40542c`, pool `0x405668`), but those addresses appear in **no config
  record** — the message↔handle↔CAN-id association lives only in the runtime **object table**
  (`*0x4069b4 = 0x40a1a8`), which is built at init and is the pack's long-standing runtime blocker.

### Receive tables decoded (real CAN-ids), `decode/mailbox_map.py`
- HW mailbox `0xaea38` (31 recs): handle↔mailbox, mask-filtered. **EPB_01 = CAN `0x104` → handle
  `0x25b`** (exact, on-car confirmed) is the one solid anchor. The other handles filter by mask, so
  handle→exact-CAN-id is not 1:1 here.
- msg-cfg `0xa9fc0`: real CAN-ids → 4-byte status slots (ACC_10 `0x117` → `0x404588`); 0x117+ range.
- receive-filter array `0xafae0` (u32 CAN-ids): the `0x100–0x116`/`0xf8–0x103`/`0x115` cluster.
  **`0x10d` is NOT present** — the ESP8 does not receive CAN `0x10d`, so the pack's earlier
  "type2 comfort = ACC_05 (0x10d)" is not supported by the receive filter and needs revisiting
  (the received ACC/comfort candidate is among `0x100–0x10c`).

### Two ways to close it (unchanged in kind, now precisely scoped)
1. **Materialize the object table `0x40a1a8`** (handle→descriptors→buffers) by emulating the seg1
   builder chain (`FUN_0008db80` → bump allocator `FUN_0006b936`) with the config roots seeded —
   then `objtable[handle]` gives each message's buffers, and the mailbox gives its CAN-id. This is
   the canonical close; prior one-shot emulation forks stalled on the per-message loop.
2. **Bench RAM read** of `0x40a1a8` + the control blocks (minutes) — hands over the same map.
Per channel, once the handle→buffer map exists: type2 comfort = control `0x40545a`/block `0x40542c`;
type4 ANB = builder `0x4bf3c` fed via `radar_msg_signal_proc` 0x2c554 / `anb_signal_conditioning`
0x3bf58; type1 = internal (0x2b568/0x43228/0x45060/0x474bc); type5 = inactive.

## Follow-on
`CODE_HI` in `ecu.conf`/`variant.conf` is annotated: real code extends to ~`0x106000`. The seg2
corpus is now committed-reproducible, so re-opening the object-table builder (now fully
decompiled) is the next concrete step toward the four exact CAN bindings.
