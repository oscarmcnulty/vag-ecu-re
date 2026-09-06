# ESP8 8R0907379BG — control loops for EPB_01 (0x104) and ACC_10 (0x117)

Full function-level trace of the two received brake-request messages that carry a decel field, from
CAN reception to hydraulic actuation. Every address is code-verified in the corpus unless marked
INFERENCE. Companion: `decel_paths.md` (arbitration/executor), `can_message_inventory.md` (rx/tx),
`four_channels_source_binding.md` (decel sources).

## Shared reception + arbitration backend (both messages)
```
CAN frame -> HW mailbox (0xaea38) -> handle -> object table 0x40a1a8[handle] -> descriptors
          -> can_rx_indication (0x8e3ec, generic copy) -> per-message state_ram (0x404558+4*i)
          -> COM signal extraction (object-table-driven; runtime-indexed) -> signal buffers
```
The 4 typed decel sources are arbitrated MAX-wins: `decel_req_preprocess` (0x7f4ec, 4-tick slew) ->
`decel_req_assemble` (0x86798, tags type 1/2/4/5) -> `decel_req_arbitrate` (0x94a70, winning type ->
`ecd_mode` 0x405aba) -> `decel_ctrl_top` (0x9b7b4, clamp) -> `ecd_state_machine` (0x633fc, dispatch
on mode). Executors write the 6 pressure setpoints (0x403d94) -> `ecd_actuation_pipeline` (0x9f190,
8 substeps incl main wheel-pressure controller `ecd_press_stage_ctrl` 0x69fc0) -> per-wheel valve/
pump demand -> terminal driver (`base_actuation_dispatcher` 0xa0da0 -> FUN_000a1d88; the ECD tail
reaches a CAN-TX pressure packer `esp_pressure_tx_packer` 0x70ec0, the solenoid MMIO is behind the
HW-ISR/peripheral 0xfff7xxxx indirection).

## ACC_10 (0x117) — ANB / emergency braking loop (COMPLETE, code-verified)
ACC_10 carries `ANB_Zielbrems_Teilbrems_Verz_Anf` (0.024, −20.016) + `ANB_*_Freigabe`. RX: msg_cfg
`0xa9fc0` rec#13, routine `0x8e3ec`, state_ram `0x404588`.

1. **Signal conditioning.** `radar_msg_signal_proc` (0x2c554) assembles 16-bit values from received
   byte-pairs into conditioned buffers (0x40559c, 0x405474, …).
2. **ANB request build.** `anb_signal_conditioning` (0x3bf58) reads those + 4-wheel validity, writes
   the **external ANB decel request `0x4054c4`** and the **freigabe gate `0x40553b`**.
3. **Arm-gate magnitude.** `anb_decel_from_wheels` (0x7c1d4) combines the external request `0x4054c4`
   (clamped ±0x1ff, primary term) + `0x4085ce` + per-wheel dynamics (0x402590+0x566 ×4) -> the ANB
   arm magnitude `anb_decel_magnitude 0x4066e0`. (So the ANB arm IS externally influenced by the
   received request, combined with vehicle dynamics.)
4. **Target shaping.** `anb_target_filter` (0x8390c) PT1-filters the target; `anb_decel_jerk_shaper`
   (0x75f34) jerk/rate-limits it (coeffs 0xd/0x7f, 0x111) -> 0x407906.
5. **Type4 producer (latched state machine).** `anb_decel_request_build` (0x4bf3c): idles until
   `anb_decel_magnitude >= 0x461` (arm), also needs master-enable `0x405cac==0x10`, quality
   `0x4055b4>0xc`, counter `0x4055e4<0x37`, `0x405abe in {0,4}`, no fault, 4-wheel plausibility;
   emits `decel_src_type4 0x407bb4` (via staging 0x407bac + `com_decel_double_buffer` 0x64ce4).
6. **Arbitrate -> mode 4.** type4 record wins MAX -> `ecd_mode = 4`.
7. **Executor (ungated).** `ecd_state_machine` (0x633fc) -> `ecd_emergency_dispatch` (0xa15d0) ->
   `ecd_emergency_pressure` (0x9c788): sets ALL 6 setpoints to the requested value (**flat step**),
   fixed timing {0x14,10,3,7}; does NOT read `flag_ecd_speed_avail` -> **active below 15 km/h**
   (bang-bang, rough).
8. **Actuation.** shared backend above.
**CAN edge:** the received ANB request feeding step 2 is ACC_10 by naming/inference (the extraction
is object-table-indexed, so not byte-pinned), strongest DBC match `ANB_Zielbrems_Teilbrems_Verz_Anf`.

## EPB_01 (0x104) — dynamic-brake request loop
EPB_01 (sender EPB_D4, so RX) carries `EPB_Verzoeg_Anf` (byte2, 0.048, −7.968 m/s²) +
`EPB_Freig_Verzoeg_Anf` (enable, bit15). RX: `can_id_array 0xafae0` idx 8 (`0xafb00`), object-table
handle **0x25b** (mailbox 0xaea38, HW reg 0xfff7e610).

1. **Not in ECD (proven exhaustive, `epb_output_trace.md`).** EPB feeds none of the type1/2/4/5 ECD
   sources; no non-ECD writer of the 6 setpoints / `ecd_mode` / actuation exists. type5 is inactive,
   so EPB->type5 is disproven.
2. **Execution path = the base ESP active-pressure controller ("Fremdbremsung").** EPB dynamic
   braking, when executed, runs through the base ABS/ESC hydraulic controller (the yaw/slip/ABS
   pressure-buildup subsystem), separate from ECD, whose terminal valve/pump writes are behind the
   HW-ISR/MMIO (0xfff7xxxx) indirection and are not statically reachable in the ECD-actuation thread.
   Note: the ANB external-request buffer `0x4054c4` (step 2 above) is produced by conditioning that
   "mixes internal + received" signals — whether `EPB_Verzoeg_Anf` is one of those conditioned
   inputs (routing EPB decel into the type4/ANB emergency path) is plausible but NOT statically
   pinnable (object-table-indexed extraction). This is the one open edge.
3. **Status feedback.** The ESP reports EPB-decel state back on **ESP_05 (0x106, TX)**:
   `ESP_Verz_EPB_aktiv` (bit58), `ESP_Verzoeg_EPB_verf` (bit60), packed by `esp_msg_pack_525c` /
   `com_signal_compose` from the esp05 status source struct `0x405f68` (pointer-written).

## Net
- **ACC_10 -> ANB/type4 -> emergency executor** is a complete, code-verified loop (ungated, flat
  step, works to 0 km/h) — the below-15 km/h brake path.
- **EPB_01** is received and carries a decel request, but its hydraulic execution does not use ECD;
  it uses the base-ESP pressure controller (behind MMIO) and/or the ANB external-request term. The
  ESP tracks it via ESP_05 EPB-status signals. The exact EPB->hydraulic edge is the remaining open
  item, sitting behind the same object-table/MMIO indirection.
