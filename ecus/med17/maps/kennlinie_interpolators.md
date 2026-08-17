# The Kennlinie / Kennfeld interpolator family (segment 0xC)

## Why this file exists

Searching this ECU for a threshold by looking for a constant in a comparison **does not work**, and
that cost this project a lot of time. MED17 evaluates most limits through table interpolation, so a
value like "15 km/h" is usually a **breakpoint inside a curve or map**, never an immediate in a
compare. An exhaustive sweep of all 5,877 resolvable scalar calibration reads in the corpus found no
15 km/h gate anywhere — because there isn't one to find at that level.

The interpolators themselves live in the boot-copied **segment-0xC scratchpad library**. Until the
copy table was decoded and mapped (see `ecu.conf` MEMMAP and `symbols_merged.csv` 0x800402bc), every
call to them was an unmapped address, so the ACC/TSK decompiles were full of dead ends and the table
arguments were invisible. Mapping it turned ~1,900 call sites into readable calls.

## The family

All layouts below were read out of the code, not assumed.

### 1-D — Kennlinie: `FUN(tbl, x)`

    tbl[0]        = n            number of breakpoints
    tbl[1 .. n]   = X breakpoints (ascending)
    tbl[n+1 .. 2n]= Y values

| routine | element type | call sites |
|---|---|---|
| `0xc0000638` | signed 16-bit | 286 |
| `0xc0000b3a` | unsigned 16-bit | 270 |
| `0xc00005e0` | unsigned 8-bit | 240 |

Each does a binary search over the X axis and then interpolates. Verified against table
`0x803dcd64`: `n=5`, `X = 200 500 1000 1500 2000`, `Y = 0 0 0 0 0`.

### 2-D — Kennfeld: `FUN(tbl, x, y)`

    tbl[0]                     = nx
    tbl[1]                     = ny
    tbl[2 .. nx+1]             = X breakpoints
    tbl[nx+2 .. nx+ny+1]       = Y breakpoints
    tbl[nx+ny+2 ...]           = Z values, nx*ny of them

| routine | element type | call sites |
|---|---|---|
| `0xc00004ca` | signed 16-bit | 204 |
| `0xc00003a0` | unsigned 8-bit | 73 |

Derived from `psVar17 = tbl + 1 + nx` (which walks the Y axis) together with the first X comparison
being against `tbl[2]`.

### Arithmetic helpers in the same library

`0xc0000a8c` (224 calls) is a saturating signed 32/32 → int16 restoring divide. `0xc0000a52` (212),
`0xc000087c` (192), `0xc000083a` (170), `0xc0000926` (161), `0xc0000c96` (158) and `0xc0000b1e` (93)
are the rest of the fixed-point set and are **not yet individually characterised**.

## How to search for a threshold, correctly

Resolve the table argument at each call site, then decode the axes:

1. the argument appears as `PTR_DAT_<calObjTableEntry> + <off>`;
2. the cal object is `*(calObjTableEntry)` — the `a9` table at `0x80103464`;
3. the table address is `calObject + off`;
4. decode with the layout above and inspect the **breakpoints**, not the code.

Scale note: ACC speed axes on this ECU are 0.01 km/h, so 15 km/h is `1500`.

## Result of the sweep (2026-08, this method)

Reachable from the ACC/TSK cluster: **29 one-dimensional curves** and **10 two-dimensional maps**.

Exactly three carry a `1500` breakpoint, and **none is the 15 km/h floor**:

| table | kind | axes | values | verdict |
|---|---|---|---|---|
| `0x803dcd64` | 1-D | X = 2/5/10/15/20 km/h | Y ≡ 0 | inert — see below |
| `0x803de864` | 2-D | X = 5..25 km/h, Y = 400..2400 | Z ≡ 10000 | constant → no shaping |
| `0x803b5a5a` | 2-D | X = ±1500 symmetric, Y = 30..100 km/h | Z ≡ 2 | deviation axis, constant |

`0x803dcd64` looked the most promising — a curve spanning exactly the low-speed band, fully zeroed —
but it does not hold up: the *other* branch of its `if/else` is a scalar (`+0x32e`) that is **also 0**,
so the term is zero either way; the result is *subtracted* as an offset rather than used as a limit;
and **7 of the 29** ACC-reachable curves are all-zero, so a zeroed curve is unremarkable here. The
`DSM_get_event_status(0x15e)` (path 350) test that selects between those branches therefore cannot
change behaviour, whatever its state.

This is consistent with a low-speed function that is present but calibrated inert — which matches the
B8 single-radar 30 km/h picture — but that is a **hypothesis, not a finding**.

## Also ruled out by this work

The long-hypothesised "symmetric fifteen" is resolved and is **not** a floor. Cal object `0x803c2d34`
holds `-1500/+1500` at `+0x356/+0x358` and again at `+0x366/+0x368`. Both pairs are passed as the last
two arguments to `FUN_8007ca62` / `FUN_8007c9f2`, which are saturating fixed-point integrators over
state at `&DAT_d0002ed0` / `&DAT_d0002ecc`. They are **clamp bounds**, not a gate.

## Where to look next

The scalar and 1-D/2-D-breakpoint search spaces are now exhausted for the ACC cluster. What remains
unswept:

- the **other interpolators** in the family (`c0000754`, `c0000aec`, `c0000c30`, `c0000702`) — few call
  sites each, but not covered by the sweeps above;
- tables reached with a **computed** offset rather than a literal `PTR_DAT_x + const`, which the
  regex-based sweep cannot see;
- the possibility that the floor is not engine-side at all. The rail mechanism is already established
  (`FUN_80143b8a` disengage zeroes `a350`/`a362`, railing both TSK channels at once), so the productive
  question may be what drives that state machine rather than which constant equals 15.
