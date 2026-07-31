# MED17.1.1 — calibration findings & ACC target status

## Capability achieved

Reproducible labeled Ghidra project via `./ecus/med17/reproduce.sh`:

| Metric | Value |
|---|---|
| Functions (canonical, alias collapsed, orphans claimed) | **5900** |
| Decompile outcome | ok=5895, degraded=6, bogus=0, fail=0, absent=0 (**99.9% clean**) |
| Decompiled code | 1,419,416 bytes = **78.0% of the live code region** |
| Orphan code (disassembled, no function) | 1,434 bytes = 0.1% (was 621 KB before `ClaimOrphanCode`) |
| Undefined non-zero remainder | 361,764 bytes — data, not code (0 referenced seeds) |
| Calibration window | `0x80380000..0x80400000`, 99.9% typed |
| Cal references (alias-folded, deduped) | 1422 → 1215 distinct cal addresses |
| Base registers | `a0=0xd000c420`, `a1=0x8002f298`, `a8=0xd000c420` |

See README.md "Coverage" for the full byte-level accounting and the evidence that the
remaining 19.9% of the code region is data rather than undiscovered functions.

## ① Calibration object table — SOLVED (the significant find)

`0x80103464 .. 0x80104390` is a flat table of **971 pointers**, sorted strictly
ascending, covering `0x803824B8..0x803E3C3C` — i.e. every calibration object in the
image. It sits *outside* the cal region, which is why an entropy/axis scan of the
cal area alone never reveals it; it surfaced as 970 "references into cal from code
that belongs to no function" in `cal_ghidra_xref.csv`.

This is **an A2L index with the names stripped**. Because the entries are sorted and
the objects are packed, the gap to the next pointer gives each object's *size* —
which is exactly the boundary information that is otherwise unobtainable without a
DAMOS/A2L, and without which maps cannot be safely named or edited.

```bash
python3 core/maps/cal_object_table.py ecus/med17/firmware/8R0907115N_0006.bin \
    --cal 0x80380000:0x80400000 --out ecus/med17/maps/cal_objects.csv
```

→ `maps/cal_objects.csv` (index, addr, size, file_offset). Size distribution:
126 scalars (≤2 bytes), 696 curves/maps (≥8 bytes); most common sizes 2, 4, 6, 8, 12.

The tool locates the table generically (longest run of 4-byte pointers that both
target the cal window and increase monotonically), so it should transfer to other
MED17 variants; it rediscovered this table independently of the xref route.

## ③ ACC longitudinal path ACC_01 → TSK — TRACED

The cruise/ACC function is located via the CAN anchor. Full
write-ups: **`maps/acc_flow.md`** (the ACC_01→TSK longitudinal trace) and
**`maps/can_signal_map.md`** (the CAN infrastructure). Headlines:

- **This ECU is generic table-driven Vector CANbedded IL / AUTOSAR-Com over an external
  CAN controller (Infineon MLI link)** — not Simos8.5's per-message mailbox handlers.
- The spine is verified end-to-end: **ACC_01 (0x109, MO#59)** → generic RX `FUN_80099600`
  → ACC-request struct `*(a9+0x3ec)` → **`FUN_801455ae`** (ACC/ESP decel coordinator, gate
  `d000a454==2`) → decel `d0005f20`/state `d000ab01` → **`FUN_8014322e`** bridge →
  **`FUN_80140922`** (TSK_02 handler) → generic Com → **TSK_02 (0x10C)**. TSK_04 status =
  `d000ab01` (=`STATE_DCC` analog); TSK_01 24-bit status via packer `FUN_80143a68`.
- **Internal decel authority rail = ±500000** (`FUN_801434de` `d0005cd0`/`d0005cf4`;
  clamp `0xfff85ee0`), ≈ ±5.0 m/s²; the on-wire `TSK_Verzoeg_Anf` then saturates at
  −3.984. The decel-shaping maps are 24× lookups in `FUN_801418ea`.

**The catch — reconciles with §"cal addressing is absolute":** the bulk of cal *is*
absolute (`movh.a`+`lea`, the 971-object table), but the **ACC control path reaches its
calibration indirectly through the base register `a9`** (`*(a9+0x3dc)` cal-struct ptr,
`*(a9+0x3ec)` RX signal struct). `SetBaseRegs` pinned `a0/a1/a8` but **not `a9`** (loaded
in the un-decompiled task dispatcher), so those cal cells and RX shadows stay symbolic —
the direct analog of Simos8.5's `a1` unlock. **This is the one blocker between the traced
path and editable decel/min-speed flash addresses.**

**`a9` is resolved by boot emulation — see `maps/a9_resolution.md`.**
`a9` is the running task's data base, loaded per-context by `FUN_8009624e` as
`a9 = *(0xd0014c7c + core*4)` (uncached-aliased if flash). For the application context it =
**`0xa0103464`** = the uncached-flash alias of the **cal-object table `0x80103464`** (this section, #1).
So **the ACC code indexes the cal-object table**: `*(a9+off)` = the cal object at table-index `off/4`.
Cracked with `research/emulation/EmulA9.java` (PSPR relocation + flash→PSPR call bypass + phase-chain
into the OS inits + write-watch); confirmed because every ACC `*(a9+off)` resolves to a valid
`cal_objects.csv` entry.

**This unlocks the ACC calibration directly:**
| ACC access | cal object | address | size |
|---|---|---|---|
| `*(a9+0x3dc)` = ACC cal struct (decel-shaping maps in `FUN_801418ea`) | #247 | **0x803b4834** | 1768 B |
| `*(a9+0x3ec)` = ACC "request" cal | #251 | 0x803b5230 | 96 B |
| `*(a9+0x434)` = big ACC map block (kennlinien) | #269 | 0x803b5bfc | 5268 B |

`a9=0x80103464` (cached form) is now in `ecu.conf` `BASEREGS`; re-running `reproduce.sh` folds every
ACC `*(a9+off)` cal read to a concrete cal-object address in the decompiles (the a1-unlock analog).
The **decel / min-speed lever** is a field within cal object #247 (0x803b4834) / #269 (0x803b5bfc) —
the openpilot edit target, now addressable with object boundaries from `cal_objects.csv`.

## ② ACC / cruise minimum speed

The ACC min-speed gate is the **EGAS-L2 cal #208 permit-floor hysteresis pair
`0x80389809`=15 (SET) + `0x8038980e`=7 (CLEAR)** in `FUN_800f006c`/`FUN_800f027c` (gated on cruise-active
`d000a113`) → the persistent permit memory `dc87` → `MON_cru_permit_flags` bit7. It is a **self-recovering,
speed-gated permit**: below the floor the ECU withholds the ACC command (no fault) and re-arms/resumes the
moment speed exceeds 15 (a MED17 openpilot user sees ACC re-enable at ~15 = the SET edge). There is **no
key-off-on lockout on MED17** — the MED17 corpus has no non-volatile store in this path (all volatile RAM).
openpilot edit: set both cells →0. Only #208 gates ACC; the other EGAS-L2 monitors are general torque/speed
supervision, not ACC. ACC *engagement* itself is a table-driven state machine with no speed gate. See
**`maps/l2_monitors.md`** (authoritative) + `maps/min_speed_l2.md` (functional-cell inventory) +
`maps/med17_openpilot_lowspeed.a2l`.

The floor is code-identified as the #208 permit pair, not a stray scalar — a raw value-range scan of the
catalogued cal objects does not find it:

- Scanning the 971 catalogued objects for a scalar encoding a 15–45 km/h threshold
  (u8, u16 in km/h, u16 in 0.01 km/h) yields only 4 candidates: `0x803C3382` (26),
  `0x803CC36C` (3300 = 33.0), `0x803E1C92` and `0x803E1CAA` (35).
- **All four are read only by the object table itself, not by code**, so a value-range
  shortlist is not a lead to the speed gate.
- No embedded label strings: the image contains no calibration label table
  (132 alpha strings total, all version/ID banners). Bosch keeps labels in the
  external DAMOS, so there is nothing in-binary to bridge label→address.

### Why this ECU is still the better bet than simos85

1. **Cal addressing is absolute** (`movh.a`+`lea`), not base-register-relative, so a
   cal byte's readers appear directly in the xref graph.
2. **The object table gives every map's address *and size*** — simos85 never got
   object boundaries without its A2L.
3. MED17.1.1 is heavily tuned publicly, so an A2L/DAMOS/XDF label set is far more
   likely to exist. With the object table in hand, such a list only has to match by
   *order*, not by address — a much weaker requirement.

### Next steps, in order

1. **Get a stock `8R0907115N_0006` read and diff it.** This image is a WinOLS
   export tagged `ACC_ENABLE` with checksums off — someone already modified the
   ACC calibration in it. The diff would point straight at the ACC bytes. Highest
   value by far, and it is an input problem, not an RE problem.
2. **The cruise/ACC function is located via the CAN anchor** (see ③ and `maps/acc_flow.md` /
   `maps/can_signal_map.md`). The ACC_01→TSK path is traced to the
   `FUN_801455ae`/`FUN_80140922` cluster; the `a9` pointer that gates the cal cells is
   resolved (see ③).
3. **Align a public MED17.1.1 label list to `cal_objects.csv` by index.**
