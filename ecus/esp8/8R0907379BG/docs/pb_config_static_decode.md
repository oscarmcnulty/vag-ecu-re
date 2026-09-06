# ESP8 COM PB-config static decode — partial (2026-09-03, fork)

Goal: statically replicate the bump allocator (FUN_0006b936) to compute EPB_01 (handle 0x25b)
EPB_Verzoeg_Anf's buffer. Pure static, no emulation.

## What decoded (proven)
- **Two explicit-buffer signal tables = the app-consumed signal subset:** `0xb038c` (53 signals,
  stride 0x10 `{marker 0x01000000, sig@+4, len@+6, flags@+7, buffer@+8, consumer_fn@+c}`) and
  `0xb06f0` (34 signals, stride 0xc). **87 signals total**, each with a FIXED buffer AND a `+0xc`
  pointer (a per-signal handler/descriptor — the field is polymorphic: some entries point to code,
  some into the 0xa2xxx–0xa8xxx dataset). These are the front-sensor / brake-assist signals the ESP
  actively uses — e.g. sig `0x037f` → buffer `0x403fa2`, a group-2 front-sensor signal.
- **EPB_01's signals are NOT in the explicit tables.** Of ~3000 signals across 214 messages, only
  these 87 have static buffers; the rest (incl EPB) are in the bump-allocated bulk-RX set.
- Explicit-table buffers are **tightly packed within a message** (gap = len), a DIFFERENT format
  from FUN_0006b936's header-bump (`alloc = round_up(size+8,4)`, data at buffer+8).

## The precise blocker (bump replication NOT built)
Two independent reasons a validated bump replication could not be produced:
1. **The nested PB-config did not decode into the allocator's inputs.** FUN_0006b936 reads, per
   descriptor, `+4`->a `.rodata` size-byte array and `+0xd`=bytecount. But the `.rodata` tables at
   `0xb2000-0xb3480` (referenced by `com_signal_compose`) are **signal-ID arrays** (values like
   0x23b,0x23c,0x249...), not the `{size_ptr,mask_ptr,bytecount}` descriptor records; and the
   `0xa7000-0xaea38` PB-config is **handle/id lists** (EPB handle 0x25b @0xa7ba6). Neither yields
   the per-signal SIZE + msg×sig ALLOCATION ORDER the arithmetic needs, without the runtime
   registrar that assembles them.
2. **No bump-allocated anchor exists to validate against.** Every known buffer (the 87 explicit,
   ESP_05 0x405e81, decel sources) is static/code-referenced and uses the tightly-packed format,
   NOT FUN_0006b936's header-bump. So even a computed layout could not be proven correct.

## H1 vs H2 — evidence favors H2 (INFERRED, not proven)
The ESP gives **static, code-referenced buffers** to the front-sensor / brake-assist signals it
actively uses. Bump-allocated bulk-RX signals have no such static buffer (routed/monitored via
runtime addressing only). Note the 4 decel-channel *requests* are not in these explicit tables
either: type2/type4's CAN requests are COM-index-written and type1/type5 are internal
(`four_channels_source_binding.md`). **EPB_Verzoeg_Anf is absent from the app-consumed static set**
— if the ESP executed EPB's decel as a brake demand (H1) it would
have a static buffer + consumer like the decel inputs do. Its absence supports **H2: EPB_01 is
received but its decel is not consumed as a brake command by this ESP**. This is inferred from the
buffer-allocation architecture, not proven by locating the buffer.

## To finish (still in-bin, not bench-gated)
Reverse the runtime REGISTRAR (builds the object-table descriptor arrays from the PB-config; it is
xref-invisible, writing through `*0x4069b4`) to learn how `0xb2xxx`/`0xa7xxx` map to the
`{size,bytecount}` the allocator reads — then the bump replication becomes computable. The blocker
is that specific decode, not the availability of the data.
