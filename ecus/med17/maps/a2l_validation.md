# A2L validation — `med17_openpilot_lowspeed.a2l`

What the A2L is, what each CHARACTERISTIC has been checked against, and — important — what editing it
will and will not achieve.

Firmware sha256 `3f95531a0537cadd261e8d390f9e3c27dc26f1baa0ccfbdc94ff5566a086c4fe` (matches `ecu.conf`
`EXPECT_SHA`). The file re-parses clean with `core/maps/a2l.py` and every value re-decodes.

## Scope, honestly stated

The A2L describes the **EGAS Level-2 speed-monitor cells** (cal #208 and its neighbours) plus a few
functional low-speed cells for reference. That is a real and useful thing to have: #208 is a genuine
ECU-side speed gate, it is calibratable, and it will bite at 15/7 km/h on the monitor-path speed.

**It is not the ACC minimum-speed floor.** The ~15 km/h floor is `ESP_05` (`0x106`) frame bit 33
`ECD_nicht_verfuegbar`, declared by the ESP/ABS and relayed by the engine — see `ecd_relay.md`. No
edit in this A2L changes an ESP decision. Flashing the #208 pair to 0 is a **necessary companion
edit**, so that the monitor does not reimpose its own boundary once the ESP-side constraint is
addressed; on its own it will change nothing observable.

Read `l2_monitors.md` for the #208 mechanism before editing.

## Validation method

Every CHARACTERISTIC is checked three ways:

1. **Raw byte read** at the claimed address and scale — all PASS
   (e.g. `0x80389809` = 15, `0x8038980e` = 7, `0x8038980a` = 17, `0x80389808` = 2, `0x8038a4ed` = 25,
   `0x8038a5c9`/`ca` = 6, `0x803b528e` = 1000, `0x803b5a30` = 2000, `0x803b88ae` = 300).
2. **`cal_objects.csv` membership** — all PASS (`0x80389809` ∈ #208 `0x803896ec` +0x11d;
   `0x8038980e` +0x122).
3. **A decompiled read site**, cited in each CHARACTERISTIC — all PASS (the #208 permit floor at
   `FUN_800f006c:740` SET / `:745` CLEAR, etc.).

The `a9` chain is re-derived from firmware: `a9 = 0x80103464`, and the folded pointers resolve to the
exact cal objects (`a9_resolution.md`). The functional path reads `d0008f5e`/`d0008c22` (0.01 km/h)
and the L2 monitors read `d0007b8a` (1/128 km/h); **no function mixes the two scales**, which is what
makes the two COMPU_METHODs safe.

## Finding 1 — the decel rail is not calibratable

The internal ±500000 (≈ ±5.0 m/s²) decel authority ceiling is **hardcoded immediates**, not cal reads
(`FUN_801434de:27-28`, `FUN_801455ae:241/242/283/338/339`), and the on-wire `TSK_Verzoeg_Anf`
saturates at −3.984 m/s² because of its 8-bit range. An A2L edit can *reshape* decel through the
#247/#269 maps but cannot raise the ceiling — that needs a firmware patch. Irrelevant to low-speed
operation, which is a min-*speed* problem rather than a decel-*magnitude* one.

## Finding 2 — the `* 0x80` speed-vs-torque distinction

`* 0x80` scaling appears both for monitor speed (×128) and for torque/accel, so `cal[off] * 0x80` is
not by itself a speed compare. Each site resolves individually: #213's `0x8038a4d7/d8/d9` (16/18/16)
and `0x8038a4ee` (12) are **torque-rail coefficients**, not speeds. Only genuine `veh_speed_MON_128`
compares are speed edges, and only #208's are gated on cruise/ACC being the active controller.

## Finding 3 — cal #260 windows are plausibility, not floors

`FUN_802c35d8` reads two paired windows on `d0008c22`: `[+0x8c = 0, +0x8a = 20]` (`:201`) and
`[+0x90 = 80, +0x8e = 140]` (`:517`). Self-contained speed-signal plausibility checks with no cruise
reference. No effect on low-speed control.

## Bottom line

- **The ECU-side edit is #208: `0x80389809` (15 → 0) and `0x8038980e` (7 → 0).** GROUP 2 (#208
  secondary bands) and GROUP 3 (#213's 25, #215's crawl window) only if a bench test shows a fault
  reappearing at a lower speed.
- **That edit does not lift the floor by itself.** The ESP still declares ECD unavailable below
  ~15 km/h and the engine still obeys. Expect no change from a #208-only flash, and do not read that
  as the edit having failed to land.
- **After any cal edit, recompute the cal-block checksum** (`core/checksum`) or the ECU rejects the
  flash, and **read the bytes back over UDS** before drawing any conclusion from a test drive.
- **Verify the right thing.** The meaningful test is whether `TSK_Verzoeg_Anf` (`0xd0008d5a`,
  TSK_02 56\|8) goes non-zero below 15 km/h — not whether `TSK_04` reports a grant.
