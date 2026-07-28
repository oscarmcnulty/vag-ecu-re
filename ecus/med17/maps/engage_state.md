# ACC mode / engage state machine — the table-driven precondition (MED17.1.1)

Resolves the open item "the ACC master-engage precondition is table-driven via `800accac` / descriptor
`0x8003f374`" (acc_flow.md §8). Investigated 2026-07-27. Tags: [C]=read code/bytes, [I]=inferred, [G]=gap.

## What `800accac` actually is [C]
Not bespoke ACC logic — it's a generic **Bosch state-vector engine** ("Zustandsautomat"): it validates a
packed *condition vector* and latches each field into an output shadow variable. Flow:

1. **Build the condition vector** (`abStack_4c`, 52 bytes) by bit-unpacking a 10-byte mask via `FUN_800aba88`.
   The mask is the RUNTIME vector `DAT_d0009b63` when it validates, else the FLASH coding default `DAT_803def94`
   (selected by `DAT_d000b9ae = FUN_800aca8c()`, a checksum/consistency check over the vector using the same
   table). `FUN_800aba88` is a pure bit-splitter, e.g. `cond[0x1c] = (mask[5] >> 5) & 3`.
2. **Latch conditions → output shadows** via the decision table at `PTR_DAT_8003f374 = 0x80044772`
   (`DAT_8003f378 = 134` records of 4 bytes `{cond_idx, expected, out_idx, out_val}`):
   `if cond[cond_idx]==expected then out[out_idx]=out_val`. The 134 records implement a near 1:1 copy of the
   ~40 condition fields to the ~40 output shadows `DAT_d000a3bd..a3ec`.
3. `FUN_800abc46(&table, vector)` runs the same table as a sequenced state check (→ `DAT_d0008c34`,
   `DAT_d000791c`) — the validation/latch gate; it does not itself compute `a3c1`.

## The master ACC state `a3c1` [C]
**`DAT_d000a3c1 = abStack_74[0x1b]`, and out_idx 0x1b is produced ONLY by these 4 records:**

| record | condition | → a3c1 | meaning |
|---|---|---|---|
| 94 | `cond[0x1c]==0` | 0 | ACC/cruise OFF (not available) |
| 95 | `cond[0x1c]==1` | 1 | **GRA** (basic cruise) |
| 96 | `cond[0x1c]==2` | 2 | **ACC/DCC** |
| 97 | `cond[0x1c]==3` | 3 | ACC extended |

So **`a3c1` is a pure pass-through of condition field `0x1c`** — a 2-bit "cruise mode" field of the condition
vector. `802c806e` then maps a3c1 → the output selector `a454` (1→GRA path, 2/3→ACC path). `cond[0x1c]` is a
pure INPUT — no table record writes out_idx 0x1c from ACC logic (the only records touching 0x1c copy
`cond[0x1d]`→`a3d0`, unrelated).

## Where the mode field comes from [C mechanism / G source]
- **Runtime:** `cond[0x1c]` = bits 5-6 of byte 5 of `DAT_d0009b63` — the runtime condition vector. `d0009b63`
  has NO direct-assignment writers in the corpus; it is populated via computed pointers by the ACC-availability
  arbitration (driver ACC on/off + system availability), then checksum-validated by `FUN_800aca8c`
  (`FUN_800abcc8` hash vs `DAT_d0009b5a`). **Which upstream signals set field 0x1c to 2 = GAP** (one layer
  further, in the vector packer).
- **Flash fallback (this image):** with `b9ae==0` the vector = coding `DAT_803def94`; byte 5 = `0x26`, so
  `cond[0x1c] = (0x26>>5)&3 = 1 = GRA`. i.e. the *default/fallback* mode on this bin is GRA; ACC (2) is asserted
  at runtime by the arbitration, not by this static coding. (`DAT_803def94 == DAT_803ded00` here, so the
  coding-mask combine is idempotent.) [C]

## Bottom line for openpilot / the min-speed question
- **This state machine imposes NO speed floor.** Its 40 condition indices are abstract packed booleans; none is
  a `speed < X` compare (verified: no speed variable or cal appears in `800accac`/the table). The ACC min-speed
  lockout is the **EGAS-L2 cal #208 permit floor `0x80389809`=15 + `0x8038980e`=7** (see `maps/l2_monitors.md`),
  NOT this table and NOT the functional low-speed cells (those are behavioural only).
- **The "engage precondition" here = mode arbitration** (OFF / GRA / ACC / ACC-ext), gated on the condition
  vector being valid. For openpilot: the car must be in ACC mode (`a454==2`), i.e. driver ACC enabled + coded
  for ACC so the arbitration sets `cond[0x1c]=2`. openpilot operates as ACC master within that mode; it does not
  need to defeat this table, and there is no hidden speed gate in it.
- **Remaining GAP (one hop up):** the exact upstream inputs that drive `cond[0x1c]` to 2 (the ACC-enable
  arbitration that packs `d0009b63`). Tractable via tracing the computed-pointer writer of `d0009b63` /
  `FUN_800aca8c`'s callers — a focused follow-up if the precise ACC-enable inputs are needed.

## Key addresses
- state engine `FUN_800accac`; vector validator `FUN_800aca8c`; bit-splitter `FUN_800aba88`;
  table engine `FUN_800abc46` / `FUN_800ac32a` / hash `FUN_800abcc8`.
- decision table `0x80044772` (134 × 4-byte `{cond_idx,expected,out_idx,out_val}`); count `DAT_8003f378`.
- runtime condition vector `DAT_d0009b63` (validated) / flash coding default `DAT_803def94`; select `DAT_d000b9ae`.
- master state `DAT_d000a3c1` (=cond[0x1c]) → `FUN_802c806e` → `DAT_d000a454` (output-path selector).
