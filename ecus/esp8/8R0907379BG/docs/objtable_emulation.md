
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
