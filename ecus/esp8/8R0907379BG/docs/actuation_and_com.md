# ESP actuation chain + AUTOSAR COM mechanism — 8R0907379BG

Completes the two ends of the control path: the pressure→valve actuation stages (downstream)
and the AUTOSAR COM signal routing (upstream). Both are code-verified as far as static analysis
reaches; the exact terminal edges (solenoid MMIO, per-message signal binding) are pointer/hardware
-driven — see "Boundaries" below.

## Downstream: setpoints → wheel-pressure actuation (VERIFIED chain)
```
6 pressure setpoints (0x403d94)
 → ecd_ctrl_struct (0x403a14)                          [+8 = setpoint ptr]
 → ecd_actuation_pipeline (0x9f190)  dispatches 8 substeps in order:
     ecd_mode_sync            (0x9dc8c)  reconcile mode (+0x18 = 1/2/0x10)
     ecd_press_stage_slew     (0x9576c)  PT1 slew of pressure command (0x330/0x33)
     ecd_press_stage_anb      (0x76cec)  ANB-branch pressure math, clamp +-0x2800
     ecd_press_stage_track    (0x784fc)  track vs measured wheel pressure (+0x76/+0x44/+0x46)
     ecd_press_stage_ctrl     (0x69fc0)  MAIN wheel-pressure controller: PT1 (0xd130/0xd13) + gain-curve
     ecd_press_stage_state    (0x6a35c)  apply/hold/release phase state machine (+0x13 = 1/2/3)
 → per-wheel pressure/valve DEMAND (in the pressure-controller structs)
 → [valve-current / pump-PWM driver + solenoid MMIO]   <-- pointer/ISR-indirect, not statically reached
```
All stages are pure control math (PT1 lag filters, `interp_lookup` (0x58f94) gain curves,
`mul_div_scale` (0x9720c)) over pointer-indirect RAM structs. No MMIO literal appears — the final
solenoid write is behind a RAM-pointer/hardware-ISR indirection.

## Upstream: AUTOSAR COM signal mechanism (DECODED format)
- `can_rx_indication` (0x8e3ec) — generic: copies each received frame into its per-message buffer,
  then triggers signal extraction (→ FUN_000a1888 → `com_pdu_router` 0x9546e).
- `com_group_ready` (0x4fff8) — readiness test: `(*(com_sig_group_table[grp*0x18].status_ptr +8) &
  ready_mask) == ready_mask`, grp id passed in.
- `com_signal_commit` (0x4fee8) — the low-level signal write: critical section (SWI 3/2), copies
  `src → dest+8` for `len` bytes per a descriptor `{[0]=value,[3]=bit-index,[4]=dest-buf,[5]=len,[2]=src}`,
  sets the group ready mask.
- `com_sig_group_table` (0xb6a44, DAT_00050110) — the routing config: indexed `grp*0x18`, a
  nested variable-length descriptor stream with embedded `{tag,count,buffer_ptr}` signal descriptors.
  Signal buffers point into the 0x407c-range (ANB/ACC signals) and 0x406c-range.
- `com_pdu_descriptor` (0xb6ffc, stride 0x14) — `{status_ptr, src, dst, buf, bitmask}`; per-bit ptrs
  decrement by 1.

## Boundaries (why the two terminal edges need more than static xref)
1. **CAN-id → decel-source binding**: the COM routing (`com_sig_group_table`) associates signals to
   buffers by signal-group id and message *handle* (index), computed at init. The raw ACC_10 buffer
   (0x404588) has zero payload xrefs. Decoding the full nested stream would bind every signal but is a
   large, error-prone parse; **emulation** (feed one frame, watch buffers) closes it decisively.
2. **pressure → solenoid MMIO**: the valve/pump driver is reached through a RAM pointer in the
   pressure-controller structs and/or a hardware timer/ISR; the peripheral map of this Bosch ASIC is
   not in the image. **Chip datasheet or emulation** required to name the terminal registers.

Neither boundary blocks the openpilot goal: the *control behaviour* (which message brakes, gated vs
not, ramp vs flat, priority, limits) is fully mapped in `decel_paths.md` / `can_brake_inventory.md`.

## Reproduce
`EspDumpTable.java b6a44 70 24 6` (signal-group table), `EspDecomp.java 4fee8 4fff8 9546e`
(COM primitives), `EspDecomp.java 9576c 76cec 784fc 69fc0 6a35c` (actuation stages).
