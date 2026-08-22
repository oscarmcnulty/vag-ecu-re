# AL551 TCU — calibration (CAL) structure

CAL region `0x190000`–`0x1FFD5F` (523 KB), CRC32 stored at `0x180244`. Big-endian.
Addresses from `tcu_8R_plaintext/8R_full_flash.bin` (8R0927158AM SW1003, the Q5 ECU).
No calibration label strings are embedded (production build) — labels below are derived
from firmware structure + axis-value heuristics, not a manufacturer DAMOS.

## Header / identity (0x190000)
`ZFADINFO*ZX8S3600*VAG*8HPXY*...`, `0014S36_ZX8S3600`, part `J217 8R0927158AM`,
`ZN2X8S361003`, `EV_TCMAL551211`, appl `0BK 30TFSIUSA` (3.0 TFSI, US) — confirms 8HP,
ZX8S36 dataset.

## Object model (reverse-engineered)
The calibration is **pointer-table driven**. 153 pointer tables (runs of ≥4 word-aligned
CAL pointers) hold ~10,000 object pointers → `al551_cal_ptr_tables.csv`. Largest:
`0x05b7a0` (1884 ptrs), `0x05ff80` (530), `0x04fae0` / `0x05267c` (473). Code reaches a
calibration object by indexing one of these tables, not by a direct PC-relative load — which
is why map lookups are table-driven rather than a single central interpolator.

### Axis format (CONFIRMED)
An axis/breakpoint array is self-describing:
```
u16  0x0000            ; marker
u16  count  (2..32)
u16  breakpoint[count] ; strictly increasing
```
2509 such axes found (word-aligned + referenced) → `al551_cal_axes.csv`. They pack
contiguously into an axis pool spanning `0x19134f`–`0x1e68f8`. Example @`0x197228`:
`[0,8, 20 50 100 200 300 400 600 800]` (8-pt), immediately followed by @`0x19723c`
`[0,8, 500 1200 1700 2500 3000 4000 5000 6500]` (8-pt RPM).

### Map data
Grid data is a separate object: signed int16, `nx*ny` cells (e.g. `0x1966b4`:
`125 -125 500 30 -60 …`). A 2D map = descriptor {x_axis_ptr, y_axis_ptr, data_ptr};
axes carry their own `count`, so the data block size follows from the two axes.

## Axis physical-type distribution (heuristic, from value ranges)
| n | inferred quantity | typical range |
|---|-------------------|---------------|
| 811 | temperature / low-speed | ≤1600 |
| 517 | engine/turbine speed [rpm] | 400–8500 |
| 491 | percent / gear / index | ≤110 |
| 337 | pressure [mbar] / torque [Nm] | 16k–32k |
| 228 | signed delta / torque | contains negatives |
| 101 | vehicle speed [km/h·100] | 8.5k–16k |

## Status / next
- **Located & structurally typed**: all axes + pointer tables + object inventory (CSVs).
- **Not yet semantically named per-map**: needs either the ZF/Bosch DAMOS, or per-consumer
  tracing (the table-driven access makes this map-by-map work). Priority targets for the
  openpilot standstill/longitudinal goal: creep torque (Kriechmoment), torque-converter
  lockup (WK) schedule, shift-point maps, input-torque limit, line pressure.
