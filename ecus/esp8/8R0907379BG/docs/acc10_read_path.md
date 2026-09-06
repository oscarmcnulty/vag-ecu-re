# ACC_10 (CAN 0x117) on the B8 Q5 ESP8 — reception proven, decode chain partially traced

**2026-08-20.** Prompted by the on-car result that openpilot gets low-speed braking on the B8 Q5
via ACC_10. An earlier claim in `../../docs/e2e_family.md` that only the ESP9 handled ACC_10 was
**wrong** and is retracted there.

## 1. The ESP8 does receive ACC_10 (VERIFIED)

`can_msg_cfg_table` @ **0xa9fc0** — 223 contiguous records, stride 0x14:

```
{u32 can_id, u32 timeout_pair, u32 mode/timeout, u32 shared_routine, u32 state_ram}
record #13 @0xaa0c4:  0x117  0x0005000a  0x010a0000  0x0008e3ec  0x404588
```

State slots are `0x404558 + 4*index`. This table covers a **different message set** than
`can_id_array` @0xafae0 (it has 0x117/0x118/0x119 but not 0x104–0x10E, and vice versa) — consistent
with two CAN channels. Reading only `can_id_array` is what produced the wrong answer. ACC_10 also
appears in `can_id_group_table` @0xb1b82 (group 0x144) and the u32 list @0xb2370.

## 2. What ACC_10 carries (from `vw_mlb.dbc`)

It is the **AEB/ANB frame**, not a comfort-ACC frame: `ANB_Zielbrems_Teilbrems_Verz_Anf`
(bit 29, 10 bits, 0.024 m/s²/bit, offset −20.016), `ANB_*_Freigabe`/`Teilbremsung` releases,
`AWV1_ECD_Anlauf` (ECD pre-charge), `AWV*`/`PCF_*`. **Hypothesis worth testing, not proven:** the
ANB request path is not subject to the 15 km/h ECD comfort floor of `ECD_path.md`, which would
explain why ACC_10 gives braking below the speed where ACC_01 drops out.

## 3. The decel chain, from the application end backwards (VERIFIED links)

```
decel_req_arbitrate (0x94a70)  <- decel_req_array 0x405a90/94/a0/ac
   ^
decel_req_assemble (0x86798)   4 TYPED requests: type 1/2/4/5
   |   each gated by status byte 0x405dcd[i] == 0x10  AND an enable bit 0x80
   |   type1 raw 0x403fac | type2 0x403a40 | type4 0x407bb4 | type5 0x403d76
   ^
decel_req_preprocess (0x7f4ec) 4 sources; extrapolates between frames
   |   out = raw - (staleness*gradient)>>2,  staleness = 3-(counter&3), counter @0x400804
   |   EXCEPT the type2/comfort source, which is a DIRECT COPY (no extrapolation)
   ^
decel_src_comfort_calc (0x88a88) -> decel_src_comfort 0x403a40
   |   reads 0x403a80, 0x403a86 (values), 0x403ab8 (flags), 0x403a2e (status),
   |   calibration via *(0x40081c)+0x11c, limits +-0x8000/0x7fff
   ^
com_decel_double_buffer (0x64ce4)  mem_copy(0x403a7c <- 0x403a6c, 0x10)
   |   this copy is what writes 0x403a80 and 0x403a86
   ^
decel_stage_writer (0x57044)  writes staging 0x403a70/72/74/76
   |   inputs: 0x405462, 0x403a48, 0x403ab4, 0x403ddc
   ^
0x405462 = the comfort CAN request   <-- COM-index-written; the CAN-frame edge is not static
       0x405462 has code readers (0x2dff4, 0x34ccc, 0x3fe08, 0x40224, 0x4b7bc, 0x4efe4, 0x5738c,
       0x62b74 ...) but NO code store at that address and no dataset config pointer, so it is
       written only by the index-driven COM layer. (The adjacent 0x405460 is a DIFFERENT field:
       the ECU's internal wheel-speed-derived measured deceleration, 5-tap history at 0x4053c8,
       written by veh_ref_wheel_estimator 0x5ee10 + decel_mode_state_set 0x8c1e8 -- feedback, not
       the request.) The frame binding therefore needs on-car observation / bench RAM read (§5).
```

## 4. Why the last link resists static tracing

- The 223-record table has **no absolute pointer anywhere in the image** (searched for
  0xa9fc0/0xa9fd4/0xab12c: zero hits), and the state array `0x404558` has exactly one literal —
  inside the table itself. So the RX indication is reached **with a record pointer**, and no xref
  chain leads back to it.
- The shared routine `0x8e3ec` has **zero code references**; it is only reachable through the
  table's field 4, loaded and called indirectly. Decompiled, it is a payload copy helper whose
  registers are unbound (r4/r5/r7 set by its caller).
- Signal extraction is **table-driven**: `{src,dst,spec}` entries (stride 12) around
  0xb26bc–0xb42bc feeding `com_signal_route_copy` (0x9c8c0), with sources in 0x405Cxx–0x405Dxx.
  None of them targets the decel input block, so those are written by code, not routing.
- The DBC's scaling constants do not appear in code (searched the ACC_10 zero-offset 834: zero
  hits), confirming conversion is table-driven — nothing to grep for.
- Ruled out: a global static base register (r9/r10/r11 carry no dominant constant), and
  `0x40081c`, which turned out to be the **per-variant flash calibration** base set by
  `variant_cfg_select` (0x872cc), not a CAN buffer.

## 5. Cheapest way to close it

Observation beats more static RE here. With openpilot already able to transmit ACC_10, send a
known `ANB_Zielbrems_Teilbrems_Verz_Anf` value and watch these addresses:
`0x404588` (ACC_10 reception state), `0x403a70`/`0x403a76` (staging), `0x403a80`/`0x403a86`
(current), `0x403a40` (comfort source), `0x405a90/94/a0/ac` (typed request slots) and
`0x405dcd[0..3]` (the ==0x10 gates). Whichever slot moves identifies the type and closes the chain.
**Caveat:** the ABS did not answer UDS at 0x713 over OBD (see the `abs-sa2-key` finding), so this
likely needs a bench harness rather than an on-car OBD read.

Static fallback: find the walker that loads field 4 of the table and calls it — that is the only
remaining route, and it needs value-tracking rather than xrefs.

## AEB/radar decel message → CAN ID 0x110 (resolved via checksum-seed → mailbox init)

The ANB decel target that `anb_target_from_can` (0x8390c) reads from signal buffers
`0x40926a-0x409273` arrives on **CAN ID 0x110** (272 dec). Chain, all static:

1. XOR-checksum verifier `FUN_0005f57c` computes the seed as
   `(word0>>0x12 & 0x7ff)>>8 ^ (word0>>0x12 & 0xff)` — i.e. exactly the VAG
   `(addr>>8)^(addr&0xff)` XOR seed, confirming per-message seeds are address-derived.
   (word0 table = descriptor stream 0xb6a44; the seed value itself is not a clean
   `addr<<0x12` for RX msgs, so the seed alone only *constrains* the ID.)
2. Descriptor block for the AEB signals starts at flash **0xb7154** (triples at
   0xb7160+: buf 0x40926a c=1, 0x40926c c=2, 0x40926e c=2, 0x409270 c=2, 0x409272 c=1,
   0x409273 c=1). A pointer to 0xb7154 sits at 0x503cc inside `FUN_00050090`'s literal
   pool, adjacent to frame-RAM ptr `0x404188` (0x503c8) and mailbox reg `0xfff7e400`
   (0x503c4). `FUN_00050090` reads frame-RAM 0x404188 (the dedicated fast-path RX
   handler — 0x110 is NOT in the AUTOSAR COM msg-config 0xa9fc0, it bypasses it).
3. CAN mailbox init table (stride 0x18, ~0xaea60+): record
   `{w0=ID<<18, mask, mbox_reg, ...}`. Mailbox **0xfff7e400 → w0=0x04400000 →
   (>>18)&0x7ff = 0x110**. Validated by the same table: mailbox 0xfff7e680 →
   w0=0x445c0000 → 0x117 = ACC_10 (known ground truth); 0xfff7e670 → 0x102 (in msgcfg).
   Neighbour mailbox 0xfff7e600 → 0x6b4/0x6b8 (0x6xx diag range) is a different path.

**Conclusion:** the ESP's ANB/emergency-decel external input is CAN ID **0x110**, an
undocumented (not in vw_mlb.dbc) direct-handled radar/pre-fill message — separate from
ACC_10 (0x117). Reconstructed layout: byte0=checksum(seed 0x110→ (1^0x10)=0x11),
bytes1-2/3-4/5-6 = three 16-bit signals, byte7 = status.

### Route cross-check (35258b7bb90057ff/0000000a, undecimated rlog, 1.1M frames)
0x110 is **absent from the entire route** — 0 frames on every bus (0/1/2/128/130/192).
So are 0x108,0x10f,0x111-113,0x115,0x116,0x118,0x119. The decode's validators DO appear
and are high-rate: 0x117=ACC_10 (n=26459, bus0+2), 0x10c (n=39690), 0x102 — so the
mailbox arbitration-ID table is sound; 0x110 is the one that never broadcasts.
The ESP's mailboxes sit on the powertrain controller (it receives 0x117 there on bus0),
so 0x110 would be on that same bus IF sent. Its total absence over ~24 min of normal
driving means 0x110 is **event-triggered** (only emitted during an actual emergency-brake
/ pre-fill event — none occurred in this benign lowspeed route) OR sent by a component not
present/active on this car. A benign route cannot distinguish those two; a route containing
a real Front-Assist/AEB event, or the full VAG MLB matrix, would. This is exactly the
expected signature of an AEB-demand message: silent until an emergency is computed.

## ⚠ RETRACTION (2026-08-23): 0x110 is NOT the ANB path

Adversarial re-trace (fork) + independently verified. The 0x110→ANB dataflow claim above
is **FALSE**. What actually holds:
- `0x40926c`/`0x40926e` are **private PT1 filter accumulators** of `anb_target_filter`
  (0x8390c) — EspRefsRange confirms the ONLY writer is that function itself (@0x8392c/0x83948).
  They are NOT COM/descriptor RX destinations. The descriptor-stream decode that tagged
  0x40926c as an "RX signal buffer" was a **misidentification**.
- The filter input is INTERNAL: `0x40926c += (0x407894 - 0x40926c)>>3`, and `0x407894` is
  computed by `FUN_0007da34` from ANB working values (no frame-RAM read). => the ANB decel
  target is **internally/wheel-derived** (`anb_decel_from_wheels` 0x7c1d4 → 0x4066e0),
  matching the ORIGINAL wheel-only finding. The turn-21 "received-radar-target" retraction
  was itself wrong.
- `0x404188` is a single status/error flag byte (read by FUN_00050090's error path), not an
  8-byte 0x110 frame. `0x405538` (was "anb_can_msg_valid") is a general state flag set
  internally by FUN_0007cb88, read by ~19 fns — not "0x110 received".
- The `{mailbox e400, 0x404188, descriptor 0xb7154}` "record" was **literal-pool adjacency**
  in FUN_00050090's arg list (the real COM group table is built in RAM at 0x406cd0 at init),
  not a bound per-message triple.

**What survives:** the ESP DOES program a hardware RX acceptance filter for ID 0x110
(mailbox 0xfff7e400 = 0x110<<18, written by FUN_00050090) — but it's **dormant/variant**:
w3=0 (no timeout monitor) vs ACC_10's w3≠0, and 0x110 sits in a 7-message provisioned-but-
absent class (0x110,0x61,0x62,0x65,0x66,0x71,0x72) ALL absent from 1.1M route frames, while
every w3≠0 object IS present and high-rate. The route absence is corroboration, not anomaly.
NOT traced: what a *received* 0x110 maps to via the RAM group table — so we can't claim it
does nothing, only that it does NOT drive the ANB target. The reconstructed "AEB message
layout" earlier in this file is retracted along with the 0x110-as-ANB claim.
