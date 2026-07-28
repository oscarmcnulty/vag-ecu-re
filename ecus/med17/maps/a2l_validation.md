# A2L validation & change log — `med17_openpilot_lowspeed.a2l`

Every CHARACTERISTIC is validated three ways (raw byte read at the claimed scale; `cal_objects.csv`
membership; an actual decompiled read site). Firmware sha256
`3f95531a0537cadd261e8d390f9e3c27dc26f1baa0ccfbdc94ff5566a086c4fe` (matches `ecu.conf` EXPECT_SHA). The A2L
re-parses clean with `core/maps/a2l.py` and every value re-decodes.

> ## ⚠ REVISED 2026-07-27 — the A2L was rewritten after the 8-agent L2-monitor investigation
> The earlier A2L (18 cells) treated many EGAS-L2 monitor cells (#148, #215) as ACC floors to "move in
> lockstep" with the functional L1 cells. That was **wrong**. The corrected A2L (12 cells) and
> `maps/l2_monitors.md` establish:
> - **The ACC min-speed lockout is ONE hysteresis pair in cal #208: `0x80389809`=15 (SET) + `0x8038980e`=7
>   (CLEAR).** Both are live: `dc87` (the permit memory) is persistent (never reset), SET at 15 / CLEAR at 7.
>   **15 = arm-from-scratch** (with `dc87`=0 you must exceed 15 to arm); **7 = re-arm floor** (once `dc87`=1
>   you can re-engage down to 7; below 7 it clears). The lockout is engaging with `dc87`=0 below 15 (fresh
>   engage / after dropping below 7). Set **15→0** (arm at any speed) **and 7→0** (never clear) for a fully
>   re-engage-robust fix. Empirically: ACC <15 km/h latches a non-volatile fault (key-off-on). See
>   `maps/l2_monitors.md` "The fault mechanism".
> - **The #148 / #215 cells are NOT the ACC floor** and are no longer in the primary group — #148 provably
>   self-disables below ~12 km/h, #215's crawl trip is a failsafe branch (signal 0x3fc stale).
> - **No "move L1/L2 together".** The functional L1 cells and the L2 monitor are independent; the lockout is
>   #208's 15/7 alone. Functional cells are behavioural only.

## Validation results (current A2L, 12 CHARACTERISTICs)

- **Raw byte + cal-object membership:** all PASS (e.g. `0x80389809` ∈ #208 `0x803896ec` +0x11d = 15;
  `0x8038980e` +0x122 = 7).
- **Decompiled read site:** all PASS — the #208 permit floor at `FUN_800f006c:737` (SET) / `:742` (CLEAR),
  etc. Sites cited in each CHARACTERISTIC.
- **`a9` chain re-derived from firmware:** `a9=0x80103464`; the folded pointers resolve to the exact cal
  objects. Functional path reads `d0008f5e`/`d0008c22` (0.01 km/h); L2 monitors read `d0007b8a` (1/128 km/h)
  — no function mixes them.

## Finding 1 — the hard decel rail is NOT calibratable (firmware-patch only) [unchanged, valid]

The internal ±500000 (≈±5.0 m/s²) decel authority ceiling is **hardcoded immediate literals**, not a cal read
(`FUN_801434de:27-28`, `FUN_801455ae:241/242/283/338/339`); the on-wire `TSK_Verzoeg_Anf` saturates at
−3.984 m/s² in the Com config. An A2L edit can reshape decel (#247/#269 maps) but not raise the ceiling —
firmware patch only. Irrelevant to controlling to 0 (a min-*speed* problem, not a decel-*magnitude* one).

## Finding 2 — the `* 0x80` speed-vs-torque trap [corrected]

The mechanical "every `cal[off] * 0x80` is a speed floor" scan **over-counted** (it produced a bogus 28-cell
list). `* 0x80` is used both for monitor speed (×128) **and** for torque/accel scaling. The 8-agent pass
re-derived each site: e.g. #213's `0x8038a4d7/d8/d9`(16/18/16) and `0x8038a4ee`(12) are **torque-rail
coefficients, not speeds**. Only genuine `veh_speed_MON_128` compares count as speed floors — and only #208's
15/7 gates ACC. (The #215 `0x8038a5c9/ca`=6 cells are real speed compares but sit in the failsafe crawl
branch, so they're in GROUP 3 "verify on bench", not the primary edit.)

## Finding 3 — `cal #260` window offsets (functional, unchanged) [valid]

`FUN_802c35d8` reads two paired plausibility windows on `d0008c22`: `[+0x8c=0, +0x8a=20]` (`:201`) and
`[+0x90=80, +0x8e=140]` (`:517`). These are self-contained speed-signal plausibility windows, NOT ACC engage
floors. No effect on the openpilot conclusion.

## Bottom line

- **The openpilot edit = set #208 `0x80389809` (15) and `0x8038980e` (7) both to 0.** That removes the sub-15
  lockout and holds the permit through standstill. GROUP 2 (#208 secondary bands) and GROUP 3 (#213's 25,
  #215's crawl) only if a bench test shows a fault reappearing at a lower speed.
- **Cal edits are necessary but openpilot still supplies the sub-floor request itself** — engagement is a
  table-driven state machine with no speed gate (`maps/engage_state.md`), the functional decel/hold path is
  cal-map-driven to standstill, and the B8 radar floor is a hardware property (openpilot injects ACC_01).
- After any cal edit, **recompute the cal-block checksum** (`core/checksum`) or the ECU rejects the flash.
