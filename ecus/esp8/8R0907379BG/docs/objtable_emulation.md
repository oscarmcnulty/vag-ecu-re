
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
