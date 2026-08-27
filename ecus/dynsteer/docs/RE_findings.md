# 8K0907144L — RE findings

## Architecture identification (the hard part)

The `.sgo` container is byte-identical in structure to the Bosch ESP8 ABS one, so the
container is no guide to the core. Every plausible arch was imported into Ghidra and scored
on linear-sweep self-consistency + auto-analysis function yield over the code region:

| language | invalid-rate | verdict |
|---|---|---|
| `tricore:LE:32:tc176x` | ~40% | reject (incoherent, wild branch targets) |
| `PowerPC:BE:64:VLE-32addr` | ~55% | reject |
| `PowerPC:BE:32:e500` | ~60% | reject |
| `SuperH:BE:32:SH-2A` | ~11% | reject — but the SH prologue halfwords (`4f22`, `2fe6`, `rts;nop`) are ~absent, so the low rate is just SH's permissive decode of non-SH bytes |
| `ARM:LE:32:Cortex` | ~5% | reject — low rate is ARM's dense decode tables; call targets show **no** function reuse |
| **`V850:LE:32:default`** | **0%** | **ACCEPT** |

Clinching evidence for V850, little-endian, base `0x00000000`:
1. A LE **data-pointer table** immediately before the `KFC_*` fault-name block decodes to
   flash `0x000xxxxx` and RAM `0x03FFxxxx` — the classic V850 on-chip RAM/peripheral window.
2. That `0x03FF0000` is exactly what the ECU's own K-Line debug monitor writes to
   (`wr 0x03FF0000 0x...` in the decoded help text).
3. Disassembly is full of V850-only opcodes: `callt`, `switch`, 3-operand `movhi`
   split-immediates (which is *why* no absolute string pointer exists anywhere in the image),
   `sld/sst [ep]`, `satadd/satsubr/mulh`.

## Deobfuscation

Whole file XOR-`0xFF`; firmware = inverted bytes `[0x200:]`, mapped 1:1 to CPU `0x0`.
Confirmed by the decoded part# / version / ZF strings and by clean V850 disassembly.
The header's SA2 seed/key script is `6805814A05870A221289494C` (runs on the sa2_seed_key
interpreter). The `22` in it is an SA2 bytecode op — **not** a container cipher; the body has
no extra codec layer.

## Function recovery status (the "fully decompile" caveat)

Auto-analysis + orphan/bracket recovery = **373 functions**, decompiler emits C. BUT the
image is only partially wired because the pipeline was built for TriCore, not V850:
- **`callt` calls** go through the CALLT base table (CTBP) — unresolved, so many callees are
  never discovered and the call graph is sparse (max ~4 callers/fn).
- **`movhi+movea` / gp-relative** data addresses are not constant-propagated, so there are
  **zero** resolved references into the string/cal region.
To truly "fully" decompile, the next step is V850-specific: set CTBP + resolve `callt`,
set `gp`, and propagate split-immediate pointers. That is net-new tooling (`core/` has none).

## CAN inputs (from the KFC_* fault enum — the definitive monitored set)

ESP_03/04/05/06, MOTOR_02/03, LWI_01, LH_EPS_02, CHARISMA_01, VIN_01, KLEMMENSTATUS_01,
GATEWAY_11, DIAGNOSE_01, + ACAN/DCAN/SCAN bus-off/timeout monitors.

**No HCA, no lane-assist, no camera, no park-assist message.** See `torque_limit.md`.
