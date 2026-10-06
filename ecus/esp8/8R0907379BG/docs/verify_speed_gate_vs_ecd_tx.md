# Independent re-verification: is `cmp #0x78` really speed-gating, and does it set the ESP_05 "ECD not available" CAN bit?

Prompted by a reasonable challenge: *don't assume the `120 × 0.125 = 15 km/h` label is a speed
gate, and verify how the ESP CAN "comfort-braking-not-available" field is actually set.*
Re-done from scratch against the freshly reproduced corpus (Ghidra 12.1.2, `reproduce.sh`,
4884 fns, 89.8% image accounted) **and** independent capstone disassembly of the raw image,
deliberately NOT trusting `symbols.csv` labels. opendbc `vw_mlb.dbc` pulled from `commaai/opendbc`
master as external ground truth.

## Method
- `decode/verify_speed_gate_xref.py` — capstone register-tracking xref over the whole ARM CODE region
  (`[0,0xa2000)`): tracks `ldr rX,[pc,#imm]` literal loads + `mov`/`add` propagation, classifies
  every `ldr*/str*` against a target address as read/WRITE. Label-independent.
- Direct disassembly of `ecd_speed_gate` (0x844fc) and `veh_ref_speed_calc` (0xd170/0xa904).
- Corpus grep for the flag/struct addresses (catches Thumb + indirect that the ARM scanner misses).

## What is PROVEN (independent of repo labels)

1. **The compared quantity is wheel-derived vehicle speed.** `veh_ref_speed_calc` (0xa904) reads
   four wheel-speed sensor inputs (`PTR_wheel_speed_0..3` @0xa8c0/a8bc/a8b8/a8b4), takes a
   median/average, and clamps to **±0x7ff**. It is the vehicle/axle reference-speed processor.
   Two *independent* functions treat these RAM shorts as speed and compare them against a graded
   set of thresholds — `0x78` (15), `0xc8` (25), `0xd2` (26.25) — which is only coherent as a speed.

2. **Scale = 0.125 km/h/bit, externally anchored (so `0x78` = 15.0 km/h, not 12.0).**
   - opendbc `vw_mlb.dbc`: `ESP_v_ref` is a 12-bit signal, scale **0.125 km/h/bit**,
     `Unit_KiloMeterPerHour`, range 0–511.5 — the ESP's own reference-speed unit.
   - On-car (prior comma logs, 4 routes): `ECD_nicht_verfuegbar` flips 0↔1 at **15.0–15.2 km/h**.
     `0x78 × 0.125 = 15.00` matches; `0x78 × 0.1 = 12.0` does not. Rules out the 0.1 km/h scale.

3. **`ecd_speed_gate` (0x844fc) is the SOLE writer of `flag_ecd_speed_avail` (0x403da8/0x403da9),**
   and the flag is a pure function of the two `cmp Rn,#0x78` compares + a 30-cycle debounce
   (xref2: the only WRITEs to 0x403da8/9 in the whole image are inside 0x844fc). Disassembly:
   both axle speeds `< 0x78` → debounce down → **clear bit6**; either `>= 0x78` → reload debounce,
   keep bit6.

4. **The flag gates the COMFORT pressure EXECUTORS.** Two functions read it and zero the brake
   setpoints when it is clear (speed < 15):
   - `ecd_decel_pressure_calc` (0x6de38) @line 31: `if ((*flag & 0x40)==0){ setpoints[+8/+a/+c/+14]=0 }`
   - `0x65cb4` @line 159: the same `& 0x40` test, same setpoint-zeroing.
   So below 15 km/h the ESP physically produces **no comfort ECD pressure**. This is the real,
   code-level actuation gate.

5. **The mode-4 / emergency (ANB) executor is NOT gated.** `ecd_emergency_pressure` (0x9c788)
   only *mentions* the flag in a comment — **no code read** (xref2 + corpus grep). It writes all 6
   setpoints to the requested value regardless of speed → works to 0 km/h (flat/bang-bang).

## What is NOT proven — and corrects a repo inference

6. **The CAN TX bit `ESP_05.ECD_nicht_verfuegbar` is NOT set from `flag_ecd_speed_avail`.**
   No CAN-TX/COM-pack function reads 0x403da9, 0x403f9e (the other speed flag `flag_speed_status`),
   or the axle-speed shorts (0x4022a2/0x402482/0x4022da/0x4024ba) in any statically traceable path.
   - `ESP_05` status is assembled by the generic COM composer (`com_signal_compose` 0x6b00 /
     `esp_msg_pack_525c` 0x525c) from the status struct `esp05_status_src` (0x405f68), which is
     filled by a **table-indexed generic copy** (`esp05_status_route_a6c8`) — the COM-indirect wall.
   - `symbols.csv` itself flags the candidate bit (`esp05_sig_0x405e90`) as
     *"Candidate ECD_nicht_verfuegbar — NOT byte-level confirmed (pack bit-map undecoded)."*

   **Conclusion:** the repo's "`ecd_speed_gate` drives `ECD_nicht_verfuegbar`" is an *inference*,
   supported empirically (the 15.0–15.2 km/h on-car flip) but **not** a proven static dataflow.
   The `0x78` constant is proven to gate comfort **actuation**; whether the identical constant also
   sources the CAN **status** bit is consistent with the evidence but remains COM-pack-undecoded.

## Bearing on the modification goal
Lowering the comfort floor requires patching the **actuation** gate (the `cmp #0x78` immediates in
`ecd_speed_gate` @0x845fc/0x84608), which is what zeros the pressure. Note the separate, unresolved
question of whether the ACC master keeps *requesting* comfort decel once `ECD_nicht_verfuegbar` is
asserted on CAN — if the status bit is raised below 15 by an independent path, the request may be
withdrawn upstream regardless of the actuation patch. That coupling is the open item.

Reproduce: `decode/verify_speed_gate_xref.py firmware/8R0907379BG_0030.bin 0x4022a2 0x402482 0x403da8 0x403da9`;
disasm `ecd_speed_gate` @0x844fc, `veh_ref_speed_calc` @0xd170; DBC `ESP_v_ref` in `vw_mlb.dbc`.
