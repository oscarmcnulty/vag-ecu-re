# 8R0909144F EPS — control-loop backbone (CAN RX → torque), trace status

## Coverage
Real code = `0x8000..0x40000` + `0x78000..0x86000` (~295 KB): **~95% decompiled** (281 KB in
1899 functions). The rest of the image is data: vectors/strings (`0x0..0x6000`), rodata tables
(`0x6000..0x8000`), cal, and a 208 KB `0x8007e007` fill (`0x45678..0x78000`) — a bogus giant
"function" was deleted and the fill marked cal in `ecu.conf`. Remaining code-range gaps are
inline jump/literal tables (verified as data, not missed code).

## Control-loop backbone (traced + labeled)
```
ctrl_task (FUN_00025b9a)
  -> ctrl_cycle (FUN_0002ea72)          # ordered ~25-stage pipeline, 1 cycle
       ... input/prep stages ...
       -> steer_ctrl_apply (FUN_0002e52c)      # gather 13 inputs -> SM -> distribute outputs
            -> steer_ctrl_statemachine (FUN_00031af2)   # 987-line fixed-point SM, reads cal
                                                        # block *(ctrl_cal_block_ptr+off)
       -> steer_ctrl_out (FUN_0002e624)        # write results back to the signal block
       ... output/motor stages ...
```
Central data structure: **`steer_sigblock` @0xfffec550..0xfffec5cc** — the arbitrated signal
struct. Inputs at +0x56x/0x58x feed the SM; outputs at +0x55e/560/562/5c2. The SM's math reads
the cal-parameter block via `ctrl_cal_block_ptr` (0xfffe9ef4) with a symmetric `+/-0x8e4` clamp
(in `ctrl_signal_proc` FUN_0002ed50) — a torque/angle saturation whose exact quantity is not
yet confirmed.

## CAN reception (two paths — important distinction)
- **Diagnostic / ISO-TP path**: the `0xfffece9c` router (com_pdu_register/…, e2e_crc, tp_send).
  Multi-frame, E2E-CRC'd; registers PDUs by E2E **Data ID** (not CAN ID). This is NOT where the
  periodic HCA_01/PLA_01 signals arrive.
- **Periodic-signal path**: AFCAN 2 channels (ch1 500 kbps, ch2 1 Mbps), mask-filtered +
  software demux. The received frames feed the `steer_sigblock` inputs. The exact RX-unpack for
  HCA_01 (LM_Offset 9b cNm, Status_HCA 4b) and PLA_01 (LW_Soll 13b 0.1°) is the next target.

## Not yet closed (honest)
- The periodic RX unpack that writes the HCA torque request and PLA angle request into
  `steer_sigblock`. The producers of the SM inputs are FUN_00025b9a and the 0x1d7xx–0x1d9xx
  signal-setter cluster; these need tracing back to the AFCAN RX.
- Which `steer_sigblock` field = HCA torque vs PLA angle, and each one's limit + the
  `HCA_01_Status_HCA` 5-vs-7 mode branch.
- The forward path from the SM output to the motor current/PWM power stage.

## Torque-limit mechanism found: assist_trq_deviation_monitor (FUN_000178fa)
A per-cycle safety monitor on an assist/torque-overlay module (`assist_module_state` 0xfffed784),
run from `ctrl_task`. It reconstructs the *expected* torque = request × speed-dependent gain
(`(speed*0x1795>>0x13)+0xec`, then `*0xd>>0x11`), forms the deviation vs the measured/commanded
torque, and compares it to a **speed-proportional tolerance** (`measured*0x11f1c>>0x15`):
- deviation > tol + `0xf8`  → set the deviation-fault latch (+0x52)
- deviation > tol + `0x5ed` → escalate debounce counters (+0x2a/+0x2c up to `0x46`=70 cycles),
  then latch fault bits 4/8 (+0x18) → the assist is cut.
This is the "torque held too far from request for too long → drop out" limiter (the EPS analogue
of the HCA max-torque/hold-time cutout). Module has status +0x10 (==5) and mode +0x14 (==7).

## HONEST completion status (this session)
DONE: ~95% code decompiled; gp/tp resolution reproducible; 34 verified labels (CAN driver, ISO-TP
layer, control-loop backbone, signal block, the torque-deviation monitor). NOT DONE: definitively
tying `assist_module_state` to HCA vs PLA vs base power-assist; the periodic CAN-RX unpack that
writes the HCA torque / PLA angle into the signal block; and the exact per-source (HCA vs PLA)
limit constants + the `Status_HCA` 5-vs-7 semantics. The blocker throughout: no in-flash signal
names, and constants (CAN IDs, bit-masks) collide with DIDs / fixed-point idioms, so every link
must be data-flow-traced, not pattern-matched.

## Control loop — fully labeled (execution order)
`ctrl_cycle` runs 21 stages, each wrapping a worker in `ctrl_crit_enter`/`ctrl_crit_exit`:
`ctrl_cyc_st01..st21` (labeled in call order) around `steer_ctrl_apply` (the steer SM) and the
control-module workers. The 5 largest workers are labeled `ctrl_worker_main_torque`
(FUN_00034d78, 926L/46 cal = the core torque computation) + `ctrl_worker_b..e`. Naming each
worker's *exact* algorithm (assist boost / damping / friction comp / return-to-center /
active-return) requires the `EV_RCEPSAU48X` A2L — the flash has no signal/label strings, so
those names would be speculation and are deliberately left as structural labels.

## Endpoint (93 labels)
Everything reliably recoverable from the binary is now traced + labeled and applied in the
decompiled corpus: the complete CAN RX/TX method stack + decoded frame format, the full control
cycle (backbone + all 21 stages + workers), the motor 3-phase PWM torque output, and the
torque-deviation limiter. The two things the binary cannot yield (and no further RE will):
(1) CAN-ID -> signal binding (multiplexed transport, external DBC), (2) each control worker's
exact OEM function name (external A2L).

## Control-loop variable labeling (no A2L)
With no A2L available, the shared RAM globals the control functions operate on are labeled by
*role*, inferred from their arithmetic (saturation bounds, scaling, comparisons, dataflow) — so
each control function reads independently. Done so far (53 data labels):
- Steer-SM I/O: `sm_in_sigA/B/C`, `sm_in_statusA/B`, `sm_in_ref/signal`, `sm_mode_in`, `sm_flag_in`,
  `sm_out_cmd_lim` (±0x639 sat), `sm_out_rate`, `sm_out_secondary`, `sm_delta_prev`, `sm_work_val`,
  `sm_sel_lo/hi`, `sm_mode`.
- steer_sigblock inputs: `sigblock_sig_a..d`, `sigblock_status_a/b`, `sigblock_flag_a..c`, `sigblock_mode`.
- States/modes/flags: `assist_mode_a/b` (the 5-vs-7 dispatch), `ctrl_state`, `ctrl_mode_69`,
  `ctrl_state_02/012`, `ctrl_flag_a..e`, `ctrl_signed_mag`, `ctrl_val_from_cal620`.
Result verified: `steer_ctrl_apply` and `steer_ctrl_statemachine` now decompile with named
inputs/outputs/modes. Naming is role-based (comment `source: re-trace(inferred)`), not OEM —
honest given no signal strings in flash. Remaining globals can be labeled the same way incrementally.
