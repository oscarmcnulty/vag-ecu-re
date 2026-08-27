# Route analysis: ACC_10 below-15 behaviour — 35258b7bb90057ff/0000000c--5b26ad8041

Empirical decode of the low-speed route cross-referenced to the firmware. It resolves both the
"~2 s max engage" and the "sometimes doesn't engage" behaviours to ONE mechanism — the 15 km/h ECD
speed gate — and CORRECTS the earlier premise that ACC_10 works below 15 km/h in this route.

## What the log shows (openpilot TX bus 128 vs ESP_05 response bus 0, + ESP_01 speed)
- **openpilot NEVER set `AWV1_ECD_Anlauf` or `AWV_Vorstufe`** (0/16255 frames). Every request used
  only `ANB_Teilbremsung_Freigabe`/`ANB_Zielbremsung_Freigabe` — i.e. the *partial-braking* request,
  which routes through the **speed-gated comfort ECD path (mode 2)**, NOT the ungated mode-4 emergency.
- **`ECD_nicht_verfuegbar` flips 0↔1 at exactly 15.0–15.2 km/h**, both directions (n=16 940). That is
  the code's `cmp #0x78` (0x78 = 120 = 15.0 km/h at 0.125 km/h/bit) to the bit.
- Every ESP engagement STARTS above 15 km/h (median 16.4); 36 % of engaged *samples* dip below 15,
  but only as the car decelerates *through* 15 before release.

## (a) The "~2 second max engage" = deceleration through the 15 km/h gate (NOT a timer)
Example @196 s: ESP engages at 18 km/h; ~2 s later the car reaches 15 km/h, `ECD_nicht_verfuegbar`
latches 1, and braking releases. The "~2 s" is simply the time to decelerate from the engagement
speed down through 15 km/h, plus the `ecd_avail_debounce` (0x1e=30 cycles) lag. No max-duration
timer is involved — long requests (up to 19.5 s) get only 1.4–3.9 s of braking, exactly bounded by
when speed crosses 15.

## (b) The "sometimes doesn't engage" = request arrives already below 15 km/h (NOT a refractory)
Example @244 s: the ACC_10 request begins at 244.5 s when speed is already 14.5 km/h and
`ECD_nicht_verfuegbar` is already 1 → the comfort executor never engages. The "refractory" look is
because a prior braking event pulled the car below 15 and it *stayed* below 15, so the gate stayed
closed. 2/8 request intervals failed this way; both while speed was <15.

## Where in the code each is triggered (labelled)
1. **`ecd_speed_gate` (0x844fc)** — reads `axle_speed_a/b` (0x4022a2/0x402482); `cmp #0x78`
   @0x845fc/0x84608. Below 15 km/h it counts `ecd_avail_debounce` (0x403da8) down from 30 then
   **clears `flag_ecd_speed_avail` (0x403da9 bit6)**. That flag is broadcast as `ECD_nicht_verfuegbar`.
   Empirically re-confirmed under emulation (`emu/exp_speedgate.py`): the flag clears at ≤14 km/h.
2. **`ecd_decel_pressure_calc` (0x6de38)** — the comfort (mode-2) executor and the ONLY reader of the
   flag: `if ((*flag_ecd_speed_avail & 0x40)==0) { zero setpoints +8/+0xa/+0xc/+0x14 }` → braking
   releases. Above 15 it looks up `ecd_pressure_curve` (0xaeb60) via `interp_lookup`.
   Both functions now have every global labelled (see symbols.csv `p_*`/`ecd_*`) so they read standalone.

## Root cause + fix for smooth below-15 braking
The comfort ECD path is speed-gated at 15 km/h by design; partial-braking ACC_10 (Anlauf=0) uses it,
so it cannot brake below 15. The **mode-4 ANB executor is NOT gated** (`ecd_emergency_pressure` never
reads the flag — proven in code + emulation). To reach it, openpilot must assert the **emergency
escalation** (`AWV1_ECD_Anlauf` / the ANB emergency Freigabe), which it currently never does.
CAVEAT: the exact `Anlauf → mode-4` routing is COM-indirect (not statically proven) — verify on-car by
sending an ACC_10 with the emergency bits set and watching whether `ECD_Bremslicht` holds below 15.
Smoothing still needs openpilot-side rate-limiting (the mode-4 executor is a flat step).

## Reproduce
`emu/exp_speedgate.py` (gate), and the route parser in scratchpad (`route_anb.py` + `route_speed.py`).
