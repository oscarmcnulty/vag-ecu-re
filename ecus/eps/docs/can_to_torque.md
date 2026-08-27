# 8R0909144F EPS — full path: CAN RX → control loop → applied torque (labeled)

53 labels in `analysis/symbols_merged.csv` (applied by pipeline step 5). The critical path:

## 1. CAN receive/transmit (hardware → frames)
- `periph_hw_init` (FUN_000289fa) sets up the CAN receive buffers (0xFFFFFD40/D80).
- `can_service_init` (FUN_00015c3a) — 2-channel service init (handles `can_ch0_handle`
  0xfffec62c / +4), from `can_com_init`. Buses: ch1 500 kbps, ch2 1 Mbps.
- `can_service` (FUN_00015d08) runs every control cycle (from `ctrl_task`):
  - **RX**: `can_rx_fifo_ready` → `can_rx_fifo_read` (drain FIFO reg 0xFFFFFD42, count in
    0xFFFFFD48 low nibble, into rxbuf) → `can_rx_frame_reassemble` (FUN_00015eac: header
    counter/type check + payload reassembly).
  - **TX**: `can_tx_fifo_flush` → `can_tx_fifo_write` per queued frame.
- Diagnostic/ISO-TP path is separate: `com_pdu_register/…`, `e2e_crc`, `tp_send`.

## 2. Control loop (signals → torque setpoint)
```
ctrl_task (FUN_00025b9a)                 # runs can_service, then the cycle
  -> ctrl_cycle (FUN_0002ea72)           # ~25 y*_step stages incl. ctrl_stage_io_marshal
       -> steer_ctrl_apply (FUN_0002e52c)        # gather steer_sigblock inputs -> SM
            -> steer_ctrl_statemachine (FUN_00031af2)   # 987-line fixed-point SM, reads cal
       -> steer_ctrl_out (FUN_0002e624)          # write results back to steer_sigblock
```
Central struct: `steer_sigblock` @0xfffec550 (inputs 0x56x/0x58x, outputs 0x55e/560/562/5c2).

## 3. Torque application (setpoint → motor)
Fast motor-control module (`0x0000xxxx`): the setpoint becomes 3-phase PWM on
`motor_pwm_phaseU/V/W` (0xFFFFF1BE/1C2/1C4). `motor_pwm_gate_ctrl` (FUN_0000dc52) /
`motor_pwm_enable` (FUN_0000e394) drive the power-stage gates (`motor_gate_status` x6) and
handle shutoff (bit 0x40) on fault.

## 4. Torque limit / safety
`assist_trq_deviation_monitor` (FUN_000178fa): expected = request x speed-gain; if
|measured - expected| exceeds a speed-proportional tolerance (+0xf8, escalating +0x5ed) for
~70 cycles, latch fault + cut assist. The EPS's torque-envelope cutout.

## Still open (honest)
- Positive identification of which `steer_sigblock` field = HCA torque request vs PLA angle
  request (the RX frame reassembly uses a counter/type header, not raw 11-bit IDs — the
  CAN-ID↔signal map is not yet decoded), and each source's specific limit + the
  `HCA_01_Status_HCA` 5-vs-7 branch (mode fields found at assist_module_state +0x10==5/+0x14==7).
- The remaining ~24 ctrl_cycle stages (labeled generically as the control pipeline; only
  ctrl_stage_io_marshal individually identified so far).
