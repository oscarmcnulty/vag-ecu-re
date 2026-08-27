# ECD_nicht_verfuegbar / 15 km/h floor — ESP8 8R0907379BG (PROVEN)

## ANSWER
**The 15 km/h ECD floor is HARDCODED in code as an immediate `#0x78`, not a calibration/coding
value.** Proven by decompilation AND confirmed empirically. Where it is set, precisely:

### The 15 km/h gate — `ecd_speed_gate` (FUN_000844fc)
```c
if ((axle_speed_a < 0x78) && (axle_speed_b < 0x78)) {   // both < 120 = 15.0 km/h  (@0x845fc/0x84608)
    ... ~30-cycle debounce countdown ...
    flag_ecd_speed_avail[1] &= 0xbf;      // CLEAR bit6  (speed NOT ok)
} else {                                  // speed >= 15 km/h
    flag_ecd_speed_avail[1] |= 0x40; *flag_ecd_speed_avail = 0x1e;  // SET bit6, reload debounce
}
```
- Speeds `axle_speed_a`=0x4022a2, `axle_speed_b`=0x402482 (signed, **0.125 km/h/bit**, so `0x78`
  = 120 = exactly **15.0 km/h**; unit verified via vw_mlb.dbc `ESP_v_ref` scale 0.125).
- Clean threshold + short debounce, **NO 25 km/h hysteresis** — matches the observed behavior.
- Output: **`flag_ecd_speed_avail` (0x403da9) bit6** = "vehicle speed >= 15 km/h".

### The ECD function it disables — `ecd_decel_pressure_calc` (FUN_0006de38)
Reads `*flag_ecd_speed_avail(0x403da9) & 0x40`:
- **bit6 == 0 (speed < 15 km/h) -> ZEROS the ECD brake-pressure setpoints** (iVar2+8/10/0xc = 0):
  ECD produces no deceleration -> **ECD unavailable**.
- bit6 == 1 (speed >= 15) -> computes ECD decel pressures (300..0xc80=3200..8000).

So **below 15 km/h the ESP's Electronic Controlled Deceleration is switched off**, which is
reported to the engine as `ECD_nicht_verfuegbar` on ESP_05. THIS is "where the 15 km/h minimum
speed for ECD is set."

## Empirical confirmation (comma logs, opendbc)
ESP_05 (CAN 0x106) `ECD_nicht_verfuegbar` (byte4 bit1): `0->1` @15.21 km/h (down), `1->0` @15.14
km/h (up) across 4 logs — a clean ~15 km/h threshold. Matches the hardcoded `0x78` + short debounce.

## CAN egress (decompilation-proven, one hop inferred)
`ECD_nicht_verfuegbar` = ESP_05 byte4 bit1; the ESP originates it (engine ECUs are receivers).
Egress: app ECD-availability status -> `com_signal_compose` (0x6b00) unpacks status struct
`esp05_status_src` (0x405f68, itself memcpy-filled via config table 0xb6b20 from app status bytes)
into per-signal RAM bytes -> transmit. The exact bit-for-bit map `flag_ecd_speed_avail` ->
ESP_05 byte4 bit1 runs through the generic table-driven COM signal router (config @0xb6b20,
`com_signal_route_copy`=memcpy 0x9c8c0); the FUNCTIONAL gate (15 km/h -> ECD off) is fully proven,
the final CAN-bit packing index is the one still-generic hop.

## For openpilot
To lower/remove the floor: patch the two `cmp Rn,#0x78` immediates in `ecd_speed_gate`
(file offsets 0x845fc / 0x84608 in the de-XOR'd image; in the .sgo add 0x200 then XOR 0xFF),
and optionally the `0x74`/`0x141` neighbors. It is a **code constant** — no cal/coding edit can
change it. Reflash needs the XOR-0xFF + SGO container + checksum/security handled.

All addresses labelled reproducibly in ecus/esp8/symbols.csv (ApplySymbols.java).

## Low-speed braking: hold path + flashing the 15 km/h gate (2026-08-22)

### Q1 — hill/hold and CAN-commandable low-speed braking
- **type1 (0x403fac) is NOT a hill-hold CAN command.** It is COM-double-buffer-fed
  (com_decel_double_buffer memcpy) and its requester `FUN_0003a2f8` is an internal
  per-corner ECD phase state-machine (states 0..6 at +0x90, timers +0x8a/8c/8e). It is
  ALSO read by ecd_speed_gate → speed-gated like comfort. Not an openpilot lever.
- **Hold escalation `decel_hold_escalation_mgr` (0x42a5c)** escalates the *arbitrated*
  request to state "3" (hold) when the active source's status byte (type1 0x403fb3 /
  type2 0x403a37 / type4 0x407bbb / type5 0x403d7d) has **bit 0x4** set; latches the decel
  (clamp 0x80..0x3ffe), **no 0x78 speed check here**. BUT it is post-arbitration and the
  comfort executor (ecd_decel_pressure_calc) still ZEROS setpoints <15 km/h — so a held
  *comfort* request is still killed at the executor. Only mode-4 (ANB) bypasses that.
- **Net:** the only works-to-standstill executor is mode-4/ANB (ecd_emergency_pressure,
  ungated) — reachable over CAN only via 0x110 (event-only, never in normal driving) or by
  arbitration selecting type4. There is **no clean stock-CAN signal** openpilot can send to
  get comfort braking below 15 km/h. The reliable path is to move the gate itself (Q2).

### Q2 — flashing the 15 km/h comfort-braking floor
- The threshold is a **hardcoded ARM instruction immediate**, not calibration. Four sites,
  each a single-byte patch (BE word low byte = imm7:0, 0.125 km/h/bit):
  | addr | insn | patch byte | 0x78→ |
  |------|------|-----------|-------|
  | 0x845fc | `cmp r4,#0x78` (ecd_speed_gate front) | **0x845ff** | e.g. 0x08=1km/h, 0x00=disable |
  | 0x84608 | `cmp r0,#0x78` (ecd_speed_gate rear)  | **0x8460b** | " |
  | 0x0d1bc | `cmp r2,#0x78` (veh_ref_speed_calc)   | 0x0d1bf | (also has 0xc8=25km/h engage hyst nearby) |
  | 0x0d1c8 | `cmp r0,#0x78` (veh_ref_speed_calc)   | 0x0d1cb | " |
  To lower ONLY the comfort-ECD floor, patch the ecd_speed_gate pair (0x845ff, 0x8460b);
  the veh_ref_speed_calc pair drives the broader flag_speed_status bit2 (25/15 hysteresis)
  used elsewhere — change only if intended.
- **Reflash feasibility (partly unresolved, honestly):** requires SA2-unlocked programming
  session (KEY IN HAND, op_abs_dump SA2) + the bootloader accepting a modified ASW. The
  bootloader is NOT in the .sgo/image, so its acceptance criterion can't be proven statically.
  Evidence gathered: no inline CRC32 poly (0x04C11DB7/0xEDB88320 absent) and no obvious RSA
  self-check in the ASW; VW_Flash's CRC-fix (lib/checksum.py) is Simos-only, not this Bosch
  ABS. Domain fact: B8-era (~2012-2016) Bosch ESP8 chassis ECUs use **checksum-protected SGO
  flashware** (ODIS/VCP flashable), pre-dating the RSA-signed cybersecurity ECUs (~2019+), so
  a checksum-corrected modified ASW is *very likely* accepted — but the only way to CONFIRM
  is an actual programming-session flash attempt. Remaining engineering: patch bytes → fix
  container checksum → repack SGO (body is XOR-0xFF).

## ANB arm conditions + speed-range validation (2026-08-23, EMULATION-VERIFIED)
Emulated anb_decel_request_build (0x4bf3c), ecd_emergency_pressure (0x9c788), exp_anb_speed.py
+ exp_anb_exec_scale.py.

ARM GATE (exact): ANB arms (statusword 0x407bf0 bit28) iff decel-estimator 0x4066e0 >= 0x461.
  0x460 -> idle, 0x461 -> ARMED (emulation-confirmed, exact). The OTHER conditions I'd listed
  from static reading (freigabe 0x40553b, master 0x405cac==0x10, quality 0x4055b4>0xc, counter
  0x4055e4<0x37, substate 0x405abe in{0,4}) do NOT gate the bit28 arm in emulation -- toggling
  each still arms. So arming ~= purely the decel-estimator threshold (those others affect later
  state progression, not the arm).

SPEED INDEPENDENCE (the key result): identical ARMED state (sw=0x1000c060) at EVERY injected
  speed 0..128 km/h (0x0..0x400 @0.125), incl 0 km/h and across the 15km/h(0x78) boundary.
  => the ANB arm is NOT speed-gated.

MODE-4 EXECUTOR: ecd_emergency_pressure writes all 6 setpoints (0x403d94) = the SAME requested
  value (0x1500) whether flag_ecd_speed_avail(0x403da9 bit6) is SET (>=15) or CLEAR (<15) --
  IDENTICAL. => executor ignores the 15km/h flag; full pressure produced at low speed / standstill.

CONCLUSION: the ANB/emergency (mode-4) brake path works at ALL speed ranges INCLUDING STANDSTILL,
  unlike comfort ECD (mode-2) which zeros <15km/h. The 15km/h floor applies ONLY to comfort.

SCALE (0x461 -> m/s²): NOT cleanly derivable. 0x4066e0 is an internal RECURSIVE decel-ESTIMATOR
  (anb_decel_from_wheels 0x7c1d4 computes it via `mul_div_scale(prev*0x1579 + wheel*req*0x40, ...)`
  -- a filter, not a linear scale; also note it stores to neighbour 0x4065e4 and only reads/flags
  0x4066e0, a discrepancy in the exact write path). Internal thresholds cluster: arm 0x461,
  secondary 0x480/0x481, sub-gates 0x2f/0xa4/0xcd/0x66/0x120. Physical m/s² needs estimator
  modeling with known input scales -- earlier "~1.12 m/s²" guess is UNSUPPORTED, retracted.

## ANB triggering path — FULL model (2026-08-23)
ACC_10 (0x117) AEB command fields (DBC, decoded on idle route = all zero / 0.0 m/s²):
  decel VALUE: ANB_Zielbrems_Teilbrems_Verz_Anf (bit29, 10b, 0.024,-20.016 m/s², raw 834=0.0)
  gates/releases: ANB_Teilbremsung_Freigabe(28), ANB_Zielbremsung_Freigabe(39), AWV2_Freigabe(18),
    ANB_CM_Anforderung(25), AWV1_Anf_Prefill(16), AWV1_ECD_Anlauf(44=ECD pump startup),
    AWV_Halten(41=hold at standstill w/ driver monitoring).
  => MULTIPLE fields must be set together (decel value + release bits) -- deliberate interlock;
     a decel value alone (freigabe=0) is ignored.

ARM-GATE ESTIMATOR (0x4066e0 >= 0x461): written by FUN_00090520 (PRIMARY) which computes a
  weighted sum of 4 PER-WHEEL values (0x400ad0/4016b8/401cac/4010c4, wheel-data region; wheel ptr
  array 0x402590) via mul_div_scale; ALSO fed by anb_decel_from_wheels (0x4065e4, external-request-
  modulated via 0x4054c4 gate + 0x4085ce) and FUN_00057a80/FUN_000a0210.
  => the arm magnitude is DOMINANTLY WHEEL-DERIVED (actual measured deceleration), MODULATED by the
     external ACC_10 request+freigabe. Emulation (exp_anb_estimator.py): static external inputs alone
     do NOT drive 0x4066e0 to threshold -- it needs real wheel-deceleration dynamics.

INTERPRETATION: ANB is a brake-ASSIST / confirmation mechanism -- it amplifies/confirms ACTUAL
  hard deceleration under external permission (freigabe), NOT a direct "apply X m/s²" command from
  the radar. The external ACC_10 fields PERMIT/MODULATE ANB; the magnitude comes from wheel dynamics.
  Reconciles: (a) user correct that an external signal is required (freigabe/permission), AND
  (b) the magnitude being wheel-derived (why static/emulated command alone won't arm it).

OPENPILOT IMPLICATION: ANB emergency (mode-4) executor is speed-independent (works to standstill),
  BUT you cannot directly COMMAND a from-scratch emergency decel via ACC_10 at cruise/standstill --
  arming needs measured deceleration. The DIRECT commandable brake path is COMFORT/ECD (type-2,
  ACC_10 decel -> decel_src_comfort -> mode-2), which is 15km/h-gated. => the standstill lever
  remains the 15km/h comfort-gate patch, NOT an ACC_10 ANB message.

## ANB wheel/braking condition — EMULATED (2026-08-23, exp_anb_wheels.py)
The arm-gate estimator FUN_00090520 combines 4 per-corner {sign-flag, decel-value} pairs:
  flags  0x400ad0/4016b8/401cac/4010c4 (bit23=inactive), values 0x40138a/401f72/40197e/400d96.
  output uVar7 = 0x2c (floor) if all flags inactive, else mul_div_scale(Σ flag_i·value_i)
  -> written <<0xd into 0x4066e0 (the arm gate).
EMPIRICAL (emulation):
- 0x4066e0 TRACKS the per-wheel decel value ~1:1 (it's a MAX/representative, NOT a sum:
  1/2/3/4 wheels active all give the same output 0x300 for value 0x300).
- ARMS when the per-wheel decel value >= 0x461 (1024->no arm, 1536->ARM). 0 wheels active -> 0x2c.
- So: the ANB arm requires the car to be ACTUALLY DECELERATING with a per-wheel decel estimate
  >= 0x461 on at least one corner. Confirms brake-ASSIST: ANB engages off measured deceleration,
  not off a raw command.
UNIT (0x461 -> m/s²): still NOT pinned. The per-wheel value 0x40138a is COMPUTED (no static writer,
  computed-address) and is SHARED with veh_ref_speed_calc (0xa904, the wheel-speed processor).
  If it were raw wheel speed (0.125 km/h/bit) 0x461=1121 would be ~140 km/h (nonsensical for a decel
  gate) -> so it is a DECEL/gradient quantity, not raw speed, in an unresolved internal unit.
  Pinning m/s² needs tracing 0x40138a's computation (differentiated wheel speed + its scale).

## AWV_Halten / standstill-hold path (2026-08-23, part b)
ACC_10 AWV_Halten (bit41) = "Request to ESP to hold vehicle at standstill with driver monitoring".
Investigated whether the ESP decel/ANB/ECD paths can serve it:
- ANB (mode-4) CANNOT hold at standstill: EMULATION (exp_anb_hold.py) shows ANB goes active->IDLE
  the moment the decel demand drops below 0x461 (0x1000c060 -> 0x80001060, latch clears). ANB is
  purely REACTIVE to ongoing wheel-deceleration; at standstill measured decel=0 -> ANB releases.
- Comfort (mode-2) is 15km/h-gated (releases <15).
- The ECD hold sequencer (ecd_press_stage_state 0x6a35c apply/hold/release) is only called within
  the speed-gated ECD pipeline; no dedicated CAN-triggered auto-hold (AVH) function was found.
=> The ESP's decel/ECD/ANB control paths do NOT provide a standstill pressure-hold. AWV_Halten
   must drive a SEPARATE mechanism: a hydraulic Auto-Vehicle-Hold (not clearly present in this
   basic ESP8) and/or the EPB handoff (ESP sends ESP_Anforderung_EPB in ESP_05 bit62 to engage the
   parking brake). Consistent with [[epb-b8-firmware]]: EPB as the static standstill backup.
- AWV_Halten's exact ESP consumption = the known runtime-COM-routing wall (unproven). But it is
  functionally EXCLUDED from the ANB/decel path by the release-at-standstill behavior above.
OPENPILOT: a standstill HOLD cannot be produced by commanding decel via ACC_10 (comfort gates at
  15, ANB releases at 0). Holding requires the EPB (discrete engage, per epb notes) or a hydraulic
  AVH if present. The lever for LOW-SPEED BRAKING (down to stop) remains the comfort-gate patch;
  the lever for STANDSTILL HOLD is the EPB, not ACC_10.

## ANB internal deceleration UNIT + 0x461 in m/s² (2026-08-23, fork)
ANCHOR (proven): anb_target_from_can (0x8390c) clamps the ANB decel target to
[DAT_83b04, DAT_83b00] = [-20000, +20000] (0x83b00=0x4e20=20000, 0x83b04=0xffffb1e0=-20000).
The ACC_10 signal it targets, ANB_Zielbrems, has DBC full-scale deceleration = -20.016 m/s².
=> internal ANB decel unit = 20.016/20000 = 0.001001 ≈ **0.001 m/s²/bit (mm/s²)**.
The wheel-decel arm-gate estimator (0x4066e0/0x40138a) feeds the SAME ANB builder
(anb_decel_request_build 0x4bf3c) and its thresholds live in the same module, so it shares
this unit. Converting the arm/estimator constants:
  arm threshold  0x461  = 1121 -> **1.12 m/s² (~0.11 g)**
  secondary      0x480/0x481   -> 1.15 m/s²
  estimator clamp 0x1680 = 5760 -> 5.76 m/s² (~0.59 g)  [max per-wheel decel considered]
  sub-gate       0xa4   = 164  -> 0.16 m/s²
  floor          0x2c   = 44   -> 0.044 m/s²
INTERPRETATION: ANB ARMS once measured deceleration reaches ~1.12 m/s² (light braking) -- a
pre-arm/monitoring threshold, NOT full emergency braking. It then amplifies toward the commanded
target (clamp 20 m/s²). Consistent with brake-ASSIST: it begins watching at gentle decel, ramps
to emergency levels. CONFIDENCE: unit MEDIUM-HIGH (clean 20000<->20.016 m/s² anchor, proven in the
ANB target path); wheel-estimator sharing the identical scale is strongly implied (same builder)
but NOT directly proven -- the per-wheel decel writer (wheel_struct+0x2c6) is computed-address and
was not isolated statically or by emulation (candidate functions took early-exit, no write).
