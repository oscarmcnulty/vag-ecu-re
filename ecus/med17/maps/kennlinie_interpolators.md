# The Kennlinie / Kennfeld interpolator family (segment 0xC)

## Why this file exists

MED17 evaluates most limits by **table interpolation**, not by comparing against an immediate. A
threshold like "15 km/h" is normally a breakpoint inside a curve or a map, so searching the code for a
constant in a compare finds nothing even when the behaviour is real. To search this ECU properly you
have to resolve the table argument at each interpolator call site and decode the axes.

The interpolators live in the boot-copied **segment-0xC scratchpad library**. Until the copy table was
decoded and mapped (`ecu.conf` `MEMMAP`, `symbols_merged.csv` `0x800402bc`), every call to them was an
unmapped address and the table arguments were invisible. Mapping it turned ~1,900 call sites into
readable calls.

## The family

All layouts below were read out of the code, not assumed.

### 1-D — Kennlinie: `FUN(tbl, x)`

    tbl[0]         = n             number of breakpoints
    tbl[1 .. n]    = X breakpoints (ascending)
    tbl[n+1 .. 2n] = Y values

| routine | element type | call sites |
|---|---|---|
| `0xc0000638` `Kennlinie_s16` | signed 16-bit | 286 |
| `0xc0000b3a` `Kennlinie_u16` | unsigned 16-bit | 270 |
| `0xc00005e0` `Kennlinie_u8` | unsigned 8-bit | 240 |

Each does a binary search over the X axis, then interpolates. Verified against table `0x803dcd64`:
`n=5`, `X = 200 500 1000 1500 2000`, `Y = 0 0 0 0 0`.

### 2-D — Kennfeld: `FUN(tbl, x, y)`

    tbl[0]                = nx
    tbl[1]                = ny
    tbl[2 .. nx+1]        = X breakpoints
    tbl[nx+2 .. nx+ny+1]  = Y breakpoints
    tbl[nx+ny+2 ...]      = Z values, nx*ny of them

| routine | element type | call sites |
|---|---|---|
| `0xc00004ca` `Kennfeld_s16` | signed 16-bit | 204 |
| `0xc00003a0` `Kennfeld_u8` | unsigned 8-bit | 73 |

Derived from `psVar17 = tbl + 1 + nx` (which walks the Y axis) together with the first X comparison
being against `tbl[2]`.

### Arithmetic helpers in the same library

`0xc0000a8c` (224 calls) is a saturating signed 32/32 → int16 restoring divide. `0xc0000a52` (212),
`0xc000087c` (192), `0xc000083a` (170), `0xc0000926` (161), `0xc0000c96` (158) and `0xc0000b1e` (93)
are the rest of the fixed-point set and are **not yet individually characterised**.

## How to search for a threshold, correctly

Resolve the table argument at each call site, then decode the axes:

1. the argument appears as `PTR_DAT_<calObjTableEntry> + <off>`;
2. the cal object is `*(calObjTableEntry)` — the `a9` table at `0x80103464` (`a9_resolution.md`);
3. the table address is `calObject + off`;
4. decode with the layout above and inspect the **breakpoints**, not the code.

Scale note: functional ACC speed axes are 0.01 km/h, so 15 km/h is `1500`. EGAS-L2 monitor cells are
u8 km/h compared as `cal * 0x80`.

## Result of the sweep

Reachable from the ACC/TSK cluster: **29 one-dimensional curves and 10 two-dimensional maps.**

Exactly three carry a `1500` breakpoint, and none of them shapes low-speed behaviour:

| table | kind | axes | values | verdict |
|---|---|---|---|---|
| `0x803dcd64` | 1-D | X = 2/5/10/15/20 km/h | Y ≡ 0 | inert — see below |
| `0x803de864` | 2-D | X = 5..25 km/h, Y = 400..2400 | Z ≡ 10000 | constant → no shaping |
| `0x803b5a5a` | 2-D | X = ±1500 symmetric, Y = 30..100 km/h | Z ≡ 2 | deviation axis, constant |

`0x803dcd64` spans exactly the low-speed band and is fully zeroed, which looks promising until you
follow it: the *other* branch of its `if/else` is a scalar (`+0x32e`) that is **also 0**, so the term
is zero either way; the result is *subtracted* as an offset rather than used as a limit; and **7 of the
29** ACC-reachable curves are all-zero, so a zeroed curve is unremarkable here. The
`DSM_get_event_status(0x15e)` (path 350) test that selects between those branches therefore cannot
change behaviour whatever its state.

A low-speed function that is present but calibrated inert is consistent with the B8 single-radar
picture, in which the radar never requests below ~30 km/h. That remains a **hypothesis**, not a
finding.

## Also settled by this work

The `±1500` pairs in cal object `0x803c2d34` (`+0x356/+0x358` and again `+0x366/+0x368`) are **clamp
bounds, not a gate**: both pairs are passed as the last two arguments to `FUN_8007ca62` /
`FUN_8007c9f2`, saturating fixed-point integrators over state at `&DAT_d0002ed0` / `&DAT_d0002ecc`.

Together with the scalar sweep (`min_speed_l2.md` §4), this exhausts the calibration search space for
a 15 km/h threshold in the ACC cluster: **there is no such breakpoint and no such scalar.** That
negative is load-bearing — it is why the floor turned out to be `ESP_05` bit 33, declared by another
module (`ecd_relay.md`).

## Still unswept

Not because anything depends on it, but so the boundary of the sweep is honest:

- the **other interpolators** in the family (`c0000754`, `c0000aec`, `c0000c30`, `c0000702`) — few call
  sites each, not covered above;
- tables reached with a **computed** offset rather than a literal `PTR_DAT_x + const`, which the
  regex-based pass cannot see (the `a9` object-table resolution covers 904 of these; a residue
  remains);
- the EGAS-L2 monitor objects (`0x80384xxx…0x8038axxx`) were swept for scalars but not axis-by-axis;
  their speed cells are plain u8 compares rather than curves, so this is a low-yield gap.
