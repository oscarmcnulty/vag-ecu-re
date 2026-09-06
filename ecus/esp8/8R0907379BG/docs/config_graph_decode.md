# ESP8 COM config-graph static decode — partial + blocker

## Decoded cleanly (static, in-bin)
- **Mailbox config** @0xaea38, 31 records stride 0x18: `{+0 RX HW reg 0xfff7e6xx, +8 filter 0xfff7eaxx,
  +0xc DLC, +0xd..e CAN-id, +0xf..10 handle, +0x11 mask, +0x17 type}`. Full canid->handle map recovered.
  **EPB_01 0x104 -> handle 0x25b** (3 mailbox entries, masks 0x00/0x40/0x1c, type 0x02).
- **Config root** @~0xa7e14: 12-byte records `{count<<16, ptr_a, ptr_b}` (counts 2-9), ptrs into
  0xae9xx/0xaeaxx/0xafxxx/0xb0xxx. This is a **routing/gateway grouping** (small counts, pairs of
  tables) — NOT the per-message signal list (EPB has ~18 signals, no count matches).
- **Registrar mechanism** (dispatcher cases): 0xd3 FUN_000814c2 processes ONE signal/call from staging
  `{handle@+4, sig_index@+6, bytecount@+7}`, writes `objtable[handle].descr[sig_index]+0xd = bytecount`,
  space-checks against pool limit `*0xbda34`; 0xd4 FUN_00089f90 per-msg allocs descriptor array; 0xe0
  FUN_0008e298 populates. Objtable base `*0x4069b4=0x40a1a8`.
- **0xb2000-0xb3480**: flat u32 arrays of **signal IDs** (0x226,0x196,0x195,...) — signal-group
  membership lists, indexed by a pointer array @0xb4600. NOT descriptor size/mask arrays (those are RAM,
  runtime-filled).

## The precise blocker for the bump replication
The bump allocator needs, per message in msg×sig order, each signal's **byte-size** (the `bytecount`
written to `descriptor+0xd`). That value is filled into the RAM staging `0x4069a6` by the registration
DRIVER, which reads several config tables (config root + membership lists + a size source) through
**RAM base pointers** — none referenced by a code literal, so static xref cannot walk to the size source.
Two independent gaps remain:
1. The per-handle **{ordered signals, byte-sizes}** is assembled at runtime, not a single static table.
2. **No bump-allocated buffer anchor** exists to validate a computed layout (all known buffers are
   static: explicit tables 0xb038c/0xb06f0, ESP_05 0x405e81). The parent flagged this; it holds.
Also CAUTION: `*0xbda34` (pool limit per the registrar) reads as CODE bytes in flash, so the pool
memory model needs verification (likely a runtime/.data value), reinforcing that these are runtime slots.

## Net
Graph partially decoded (root format, full mailbox canid->handle map incl EPB->0x25b, registrar
mechanism, membership lists). The signal-grouping-with-sizes layer — the bump allocator's actual input —
is runtime-assembled via base pointers and not statically decodable here, and has no validation anchor.
EPB_Verzoeg_Anf's buffer was not resolved.
