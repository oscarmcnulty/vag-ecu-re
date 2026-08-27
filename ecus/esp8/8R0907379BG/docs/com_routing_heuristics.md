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
