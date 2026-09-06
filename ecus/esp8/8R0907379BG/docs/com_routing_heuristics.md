# Heuristic searches to crack the exact COM RX routing (CAN-ID -> buffer)

Goal: break the runtime-COM-routing wall and get proven {CAN-ID -> RX buffer -> signal} bindings.
Ranked by promise x tractability. (P) = probed this session with the noted result.

## TIER 1 — most promising

1. **id-array(0xafae0) parallel-index anchor** (P: strong lead)
   - Probe result: msg-config(0xa9fc0) order is NOT the id-array order (0/30), BUT the id-array
     order (0x103,0xfc,0xfb,0xf9,0xfa,0x102,0x115,0xf8,0x104,0x105,0x106...) MATCHES the earlier
     descriptor-segment order at 0xb6a44. => id-array is parallel to the GROUP/descriptor order.
   - Do: align id-array[k] to group-table[k] (0xb6a44 stride 0x18) and to the descriptor segments;
     the group record's buffer field (+8 / its descriptor block) then gives CAN-ID -> buffer.
     Validate against known anchors (ESP_05, ACC_10 checksum seed).

2. **E2E/CRC seed table inversion** (the seed IS the address)
   - Every XOR-checksummed RX msg has seed = (id>>8)^(id&0xff), computed by FUN_0005f57c from a
     per-group word. Map each FUN_0005f57c CALL SITE (group index arg) -> the buffer verified in
     that block -> seed -> candidate id set; intersect with the mailbox/msg-config id list.
   - For CRC8H2F msgs (ACC_10 0x117 etc.) find the data-ID/counter config record (distinct table).

3. **Allocator-recording emulation** (definitive, if it converges)
   - Re-run COM init but replace FUN_000a29dc/a2a3c/a11ee with a bump-allocator that RECORDS
     handle->backing-address, so the runtime tables (0x4069b4->0x40a1a8, group table 0x406cd0)
     materialize with known addresses. Then dump {group -> mailbox, buffer}. Prior full-init stub
     failed because handles weren't backed; recording+backing them is the fix.

4. **RX-indication write-trace emulation** (per-mailbox)
   - For each mailbox object (controller e400/e600 base + idx*0x10, from FUN_000501d4), stage a
     MARKED 8-byte frame in the mailbox regs and run can_rx_indication(0x8e3ec) / the RX dispatch
     with a UC_HOOK_MEM_WRITE hook; the marker bytes' landing addresses = that message's RX buffer.
     Needs the group-table set up first (via #3 or a minimal init).

## TIER 2 — structural mining

5. **Enumerate ALL double-buffer/memcpy maps** (P: partial)
   - com_decel_double_buffer (0x64ce4) has 1 caller but is ONE of several. Find EVERY caller of
     mem_copy whose literal pool is a {dst,src,len} table -> each is a recoverable signal-routing
     map (staging<->current). Union them = the internal signal plumbing (RX side of the decel/ECD
     groups already recovered this way).

6. **Group-table field decode via FUN_000501d4/FUN_00050090 semantics**
   - Now known: group record @0xb6a44 stride 0x18 -> {value(+0), mask(+4), ptr(+8), status(+0x10),
     byte(+0x14), type(+0x16), ctrl-sel(+0x17=1:e400/2:e600)}. Decode all 62 records; the type-5
     branch matches by VALUE (received ID) not pointer -> those +0 fields may hold expected IDs.

7. **Mailbox mask expansion** (P: caution)
   - Mailboxes use MASKED acceptance (e680 accepts 0x117 AND 0x11d). Robustly re-parse 0xaea60
     (stride 0x18) collecting ALL (id,mask) per mbox_reg; a mailbox -> a SET of ids. Cross with the
     group table's value-match demux to pick the actual id per group.

## TIER 3 — value-matching & anchoring

8. **Route-payload correlation** — for a message present in the route, its known byte pattern (e.g.
   ACC_10 idle 00 40 68 00 00 00) can be searched as an initial/expected value in the config, or
   used in an RX-emulation to confirm the buffer.

9. **Anchor-and-expand from known signals** — ESP_05 TX storage (0x405e81), the decel double-buffer
   map, the mailbox arb-ID validators (ACC_10 0x117). Walk pointer neighborhoods outward.

10. **Config-root walk** — the "COM master root" 0x503c0 island + 0xa7e48/0xaea38 tables are the
    PB-config the init consumes; reverse the init's table-walk arithmetic directly (no emulation).

## Discarded / low-yield (probed)
- Naive "CAN-id u16 followed by a 0x40xxxx ptr within +8" scan: 378 hits, mostly degenerate
  (buf 0x400000) -> too noisy without the record-stride constraint.
- msg-config <-> id-array direct index join: 0/30 (different orderings; use a VALUE join instead).

## RESULTS of running the heuristics (2026-08-23)

**#1 id-array alignment — INCONCLUSIVE.** id-array(0xafae0) first ~16 entries are clean ordered
IDs (0x103,0xfc,0xfb,0xf9,0xfa,0x102,0x115,0xf8,0x104-0x10b...), but as a flat u32 array it does
NOT hold ~225 clean IDs (set overlap with msg-config only 51 -> past the first run it's other data
/ different structure). The 0xb6a44 group table (stride 0x18, 62 recs) is the descriptor triple-
stream, NOT {id,buffer} pairs (only 23/62 have a RAM buffer in +0; rest are counts/encodings). No
clean 1:1 to align. id-array's true length/structure + a parallel buffer array were not found.

**#5 double-buffer maps — WORKS but gives INTERNAL plumbing, not raw routing.** 56 distinct
functions call mem_copy(0x8e0d0); the big ones (com_decel_double_buffer 0x64ce4 x28, FUN_0008eb9c
x8, 0x852ac x6, 0x9ce9c x5, 0x95bec x5, 0x7ae1c x4 ...) are per-group staging<->current double-
buffers. Recoverable and useful for internal signal plumbing, BUT they double-buffer ALREADY-
extracted internal signals (e.g. FUN_0008eb9c does per-wheel struct +0x184->+0x1a4), not the raw
CAN frame -> first buffer deposit. Same one-level-up limitation as the decel map.

**#2 seed inversion — BLOCKED for buffer groups.** FUN_0005f57c seed = f(group.word0>>0x12). For
the 23 BUF groups word0 is a RAM ptr (0x40xxxx) -> >>0x12 gives ~0x10 -> garbage seed, not a valid
CAN-id seed. Only addr<<0x12-encoded groups give valid seeds, and those aren't the buffer groups.

### Verdict
Every STATIC heuristic recovers INTERNAL signal plumbing (staging/double-buffer/estimator maps)
but NOT the raw CAN-frame -> first-buffer deposit, because that deposit is done at a COMPUTED
address by can_rx_indication(0x8e3ec) using the RUNTIME-allocated routing table. Confirmed
structural reason the wall persists.

### Only two paths left to the RAW routing:
- **#3 allocator-RECORDING emulation** (definitive): re-run COM init with FUN_000a29dc/a2a3c/a11ee
  replaced by a bump-allocator that BACKS + RECORDS each handle->address, so 0x4069b4->0x40a1a8 and
  the group table 0x406cd0 materialize; then dump {group->mailbox,buffer}. (Prior stub failed only
  because handles weren't backed.)
- **#10 full static init reversal**: hand-reverse the init table-walk over the 0x503c0 island +
  0xa7e48/0xaea38 PB-config. Tedious but no emulation risk.

## SESSION 2026-09-02 — COM engine structure decoded; the wall is now precisely localized

Goal: a software-only decode of CAN-ID -> signal buffer (esp. EPB_01 -> the type5 decel source).
Progress this session narrows the wall from "the whole COM layer" to ONE specific mechanism.

### What is now PROVEN static (decodable without a bench)
- **Descriptor format (from the consumer code).** `com_signal_commit` (0x4fee8) descriptor =
  `{[0]=init/value(<<0x12 encoded), [2]=SRC ptr, [3]=group-ready bit, [4]=DEST ptr, [5]=len}`;
  it byte-copies `SRC -> DEST+8` for `len` bytes. `com_group_ready` (0x4fff8): group table stride
  **0x18**, `+4`=ready mask, `+0x10`=status-obj ptr (status at `+8`).
- **The per-message COM handlers reference STATIC FLASH tables.** `com_pdu_router_9546e` (0x9546e,
  handles PDU-handle `<0xd`, group `0x3d`) loads `com_pdu_descriptor` **0xb6ffc** and
  `com_sig_group_table` **0xb6a44** directly from its literal pool (0x95544/0x95548). So the
  **src/dest/len signal-commit routing is static**, not runtime-allocated.
- **0xb6ffc is used by exactly one function** (the router); **0xb6a44 is the central table**, walked
  by ~9 COM-engine fns (0x503d4/0x5f5e8/0x7648c/0x82884/0x95548/...). The COM engine is centralized.

### The residual wall — localized to ONE edge
The static descriptors give **SRC -> DEST** commit copies (internal plumbing). The part that is NOT
static is the **raw CAN frame -> first SRC buffer** deposit:
- `can_rx_indication` (0x8e3ec) copies the frame to a buffer resolved via
  `*(routing_table_0x4069b4 + handle*0x10 + 8)` — a **runtime-allocated, 2-byte-handle-indexed** table
  (`0x4069b4 -> 0x40a1a8`), populated at init by the handle allocator `FUN_000a29dc` (returns a
  16-bit handle; Thumb->ARM veneer + LR-relative dispatch).
- The decel sources confirm it: `type5` current `0x403d76` <- staging `0x403d6e` (static double-buffer
  `com_decel_double_buffer` 0x64ce4), but **`0x403d6e` has NO static writer and NO flash-descriptor
  dest pointer** -> it is deposited at the runtime-resolved address. Same for the `type5` enable
  `0x403d7d`. So **EPB_01 -> type5 cannot be closed by static xref** — only the deposit edge is missing.

### The two software-only ways to close that one edge (no bench/car)
1. **Recording allocator + resolver stub (definitive; prior attempt stopped exactly here).** In the
   Unicorn harness, hook `FUN_000a29dc` to return an incrementing **16-bit** handle while recording
   `handle -> a real backing address` in a side map, AND hook the **resolver** (handle->address; the
   `0x4069b4[handle*0x10+8]` dereference path used by `can_rx_indication`) to return the backing
   address. Then run COM init so `0x4069b4/0x40a1a8` and the group table materialize; dump
   `{handle -> buffer}`. Prior stub failed only because it returned 32-bit addresses that truncated to
   the 2-byte handle field — the fix is the separate side-map + resolver hook. Then a marked-frame
   injection through `can_rx_indication` per handle gives `{handle -> SRC buffer}`, and the handle's
   CAN-id comes from the mailbox/id-array. TARGETS: alloc `0xa29dc`, routing `0x4069b4`, resolver in
   `0x8e3ec`, id-array `0xafae0`.
2. **Per-handler marked emulation (partial; covers statically-descriptored PDUs only).** Seed the
   group-state RAM + a marked SRC, run a per-message handler (e.g. `com_pdu_router_9546e`), and read
   where the commit writes (`DEST` from the static descriptor). Binds the handle-`<0xd` group's
   signals without the allocator, but not the runtime-deposited SRC edge.

VERDICT: a purely STATIC decode is blocked at the single runtime-handle frame-deposit edge; the
software-only crack is build #1 (resolver-stub recording emulation), which is a bounded harness task
with all targets identified above. Ties [[esp8-abs-firmware]] SBOOT note (a BDM/SBOOT dump hands you
these same runtime tables directly, and also the valve MMIO map).

## CORRECTION (same session, later) — the "runtime-handle wall" was a DECOMPILER ARTIFACT

The section immediately above (and the 18-turn prior belief in an unresolvable 2-byte-handle COM
allocator) is **WRONG**. Disassembled raw, the "allocator veneers" are trivial Thumb->ARM thunks:
- `FUN_000a29dc` bytes `4778 46c0 eafe9d26` = `bx pc; mov r8,r8; b 0x49e80` -> **0x49e80 = byteswap16**
  `((x&0xff)<<8)|((x>>8)&0xffff)`.
- `FUN_000a2a3c` -> `0x49e64` = **memset(ptr,0,n)**.
- `FUN_000a29e4` -> `0x4a48c` = **bounds check** `x < *0x4069fc`.
The decompiler mis-rendered the `bx pc` interworking thunk as an `(lr&~3)+0x5fc` computed call, and
prior work read that as an opaque handle allocator. There is **no runtime handle allocator**.

**The real mechanism (config-driven, software-recoverable):**
- `FUN_0006b936` is a **bump allocator**: it iterates messages via the object table (`*0x4069b4`,
  stride 0x10: `+6`=signal count, `+8`=descriptor-array ptr, `+0xf` bit5 valid), and per signal
  computes a size from the descriptor (`+0xd`=byte count) then assigns `descriptor[2] = bump_ptr`
  and advances. `FUN_000a29dc` inside it is just the byteswap that stores the size big-endian.
- The object table + signal descriptors are **`.data` globals initialized from flash** (the
  `*0x4069b4` base is not written by any code that references the literal -> C-runtime `.data` copy).
- The COM PB-config with **explicit RAM signal-buffer addresses is in flash ~0xb5da0-0xb7790**
  (records `{type, RAM signal-buffer addr, config=…46c0}`; the recurring `0x46c0` COM constant marks
  them). This region holds `com_sig_group_table` (0xb6a44) and `com_pdu_descriptor` (0xb6ffc).

**Consequence:** the CAN-ID -> signal-buffer routing IS recoverable **software-only** — no bench, no
handle modeling. Two finish options, both bounded:
1. **Emulate** the `.data` init + `FUN_000892a0`/`FUN_0006b936` (all clean ARM; the byteswap/memset
   "veneers" run as-is — do NOT stub them, which is why the prior emulation returned nothing) and
   dump the `descriptor[2]` buffer assignments; then marker-inject per message for CAN-ID -> buffer.
2. **Replicate** the bump allocation in Python from the flash `.data` object table + descriptors +
   the explicit-address PB-config at 0xb5da0-0xb7790.

STATUS: mechanism fully corrected and de-risked; the multi-format PB-config parse / init emulation is
the remaining (bounded) execution step. The earlier "SBOOT/BDM dump required" conclusion is
**downgraded** — it is a convenience, not a necessity, for the RX routing.

## CORRECTION 2 (bootstrap-emulation result, 2026-09-02) — SBOOT is NEEDED after all (for grouping + type5)

The bootstrap emulation partly WALKS BACK Correction-1's "software-only, SBOOT downgraded to
convenience." Result:
- **Confirmed** by emulation: 0x49e80=byteswap16, 0x49e64=memset (no handle allocator). Solid.
- **Recovered software-only:** the signal->buffer half — flash COM signal table `0xb03fc` (43 recs,
  stride 0x10 {sig_id, len, flags, RAM_buffer 0x405xxx-0x409xxx, extraction_link}); see
  `decode/com_signal_table.txt` + `docs/com_routing_decoded.md`.
- **BLOCKED (real, pinned):** `_start` (0x8f440) bootstraps via **SBOOT monitor SVCs** (10 SVCs in
  200 insns; svc #0x13-0x16,#0xff10). The `.data` COM config — object table `*0x4069b4`, runtime
  signal descriptors, message count, AND the **PDU->CAN-ID grouping** — is SBOOT-initialized and
  ABSENT from this ASW image (reset vec `b #0`). `FUN_0006b936` from zeroed RAM allocates nothing
  (3 writes). So config-init/bump-allocator emulation **cannot bootstrap** here.
- **type5/EPB weaker than thought:** every type5 address (`0x403d76`/`0x403d6e`/`0x403d66`/`0x403d7d`)
  appears ONLY in code literals, NEVER in flash config, no static writer — whereas type1 (`0x403fa2`)
  and type4 (`0x407ce8`) COM sources ARE in the flash config table. So "type5 = EPB pass-through" is
  now a **weaker** inference, not a stronger one.

**Net:** wall bisected — signal->buffer = software-recoverable (partial table done); CAN-ID grouping +
type5/EPB feed = need the **SBOOT-resident .data** (SBOOT/BDM dump) or an on-car `EPB_01`<->`ESP_05`
lever-hold capture. SBOOT is a NECESSITY for those two, not merely a convenience.
