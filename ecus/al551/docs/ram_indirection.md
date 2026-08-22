# AL551 — resolving the RAM-pointer indirection

The RTE reaches its calibration/shift/torque descriptors through a **RAM pointer table** that
the boot init populates from flash. Statically, those reads decompile as opaque `*(base+off)`
or `&DAT_fff84xxx` (pass-by-reference), so the descriptor tree looked unreachable.

## Key finding: the init installs are statically recoverable (no CPU emulation needed)
The boot init runs a table of **install stubs** (function-pointer array at flash `0x0f17c8`+).
Each stub is `*DAT_A = DAT_B;` — i.e. `mem[u32[A]] = u32[B]`, where A and B are **literal-pool
words**. So every install is a pair of constants readable straight from flash — a full CPU
emulator is unnecessary; a deterministic static pass recovers the RAM image with no peripheral
faults or loops. (`analysis/extract_ram_bases.py` does this: scans the corpus for the stub form,
dereferences the pool words, emits `ram_addr,value`.)

## What it resolves
- **156 RAM pointer slots** installed → `analysis/ram_bases.csv`.
- 149 form a contiguous **RAM descriptor pointer table `0xfff847f4`–`0xfff84b1c`** →
  flash descriptor tree **`0x181700`–`0x18a28c`** → cal/shift/torque data (e.g.
  `0xfff84a00 → 0x18852c → shift-record pointers 0x1cc7xx`; `0xfff847f4 → 0x181700 → cal group`).

## How the Ghidra decompile is updated to handle it
- `ecu.conf` `MEMMAP=` adds the SH-2A `RAM`/`PERIPH` blocks (raw BinaryLoader lacks them).
- `ecu.conf` `RAM_DATA_IMAGE=analysis/ram_bases.csv` drives pipeline **step 6c**
  (`core/ghidra/ApplyRamDataImage.java`): it **surgically initializes only the const
  pointer-table regions** (clustered from the CSV) and writes each slot's flash target, typing
  each as a pointer. Mutable RAM scalars stay uninitialized/symbolic (no power-on folding), so
  only the genuinely-const descriptor tree is folded. `reproduce.sh` rebuilds this every run.
- Effect: RAM base reads resolve to their flash descriptor targets; the descriptor tree is
  navigable, and direct `*(base+const)` reads fold. (Pass-by-reference `&slot` accessors still
  need per-callee propagation — the slot is typed+labelled so the target is one xref away.)

## Remaining
A handful of subsystem context bases are installed by *computed* init (a config passed as a
function arg, e.g. `FUN_00071428: _DAT_fff91a68 = param_1`) rather than a const stub, so they
are not in `ram_bases.csv`. Resolve by reading the init table `(init_fn, config)` pairs at
`0x0f17b0`+ (or a small targeted EmulatorHelper run over just the init sequence).

## Update: emulator supersedes static extraction (init-emu, verified more correct)
The static init-stub deref (`extract_ram_bases.py`) mis-resolved **72 of 154** pointer slots
(e.g. `0xfff84a00`: static `0x18852c` vs true `0x5b7a0`) — Ghidra's `DAT_` pool-symbol naming
did not always equal the instruction's real PC-relative target. **`core/ghidra/InitEmu.java`**
runs the 309 install-stub functions under Ghidra's SH-2A `EmulatorHelper` (RAM+peripherals
mapped zeroed → no faults; 385 entries ran, 0 aborted) and reads the resulting RAM — the
authoritative values. `analysis/gen_ram_bases.sh` regenerates `ram_bases.csv` this way;
The buggy static extractor was removed; `gen_ram_bases.sh` (InitEmu) is the sole generator.
Two RAM descriptor pointer clusters resolved: **A** `0xfff847f4-0xfff84944 → 0x181700+`
(CAL-block descriptors), **B** `0xfff84a00-0xfff84b1c → 0x5b7a0+` (the master tree, mirrors
flash `0x5fcac`, → shift records `0x1cc7xx`).
The remaining "param-passed" bases (e.g. `0xfff91a68`) turned out to be **runtime** per-message
contexts set by the CAN handler `FUN_65d46` (dispatched on DLC), NOT boot-init const bases — so
they are correctly excluded. The 154 emulated installs are the complete const-base set.
