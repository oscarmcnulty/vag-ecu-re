# HCA vs PLA on 8R0909144F EPS — traced from firmware (no openpilot/DBC assumptions)

## (a) HCA status 5 vs 7 — DELIVERED torque is identical; the only 5/7 difference is in the monitor plane
Received HCA status flows CAN RX (pla_rx_gate FUN_00026984, msg case 0x11) -> hca_status_get_a/b ->
hca_status_a/b (0xfffec595/6) -> hca_status_worker_a/b (0xfffee294/8) -> the control workers.

This answer was reversed twice; this is the VERIFIED end state (actuation path traced to the motor):
1. first pass said "identical" (only saw FUN_00034d78);
2. second pass found a mode-indexed gain in FUN_0003857e and (wrongly) called it delivered torque;
3. actuation trace proved that gain is MONITOR-ONLY. Delivered torque for 5 and 7 is identical.

**Delivered-torque path (verified):** steer_ctrl_statemachine (FUN_00031af2) -> sm_out_rate(0xfffee1ba)
-> steer_ctrl_out (0002e624) -> sm_torque_setpoint(0xfffec560) -> motor_cmd_stage (FUN_0002a740) ->
motor_current_setpoint (FUN_0000cf56): `uRamfffeb6f6 = clamp(|sm_torque_setpoint|*0x4b >> 8, 0xffd)`
-> motor PWM. The gain is a **FIXED 0x4b**; the only per-call selector (cf56 param_2, from sigblock
status bits fffec55e) is normal/hold/max — NOT the assist mode. cf32 records the mode nibble as a
status only. In the MAIN worker FUN_00034d78, 5 and 7 are always grouped (enable {5,6,7}; active
predicate (==5)||(==7); max-torque cap +0x306; rate +0x2fe/+0x304 chosen by speed) — never split.
=> a lateral/PID controller sees IDENTICAL commanded->delivered gain for 5 and 7, no discontinuity.

**The 5/7 mode gain (FUN_0003857e / ctrl_worker_d) is a MONITOR, not actuation.** At 0003857e.c:182-210
it computes `mon = torque_sum * gain >> 16` with gain = cal+0x10 (mode 7) / cal+0xe (mode 5) / 0xffff
(else). But its output hca_mode_gained_monitor(0xfffee12a) and siblings feed ONLY: the inverse-
redundancy safety RAM (0002e06e: fffee31a=val, fffee446=~val), plausibility comparators (000374ae ->
ctrl_task 00025b9a:247-271 fault flags), and diagnostic/UDS/CAN-TX telemetry. ctrl_worker_d writes
NONE of the motor-command sigblock outputs (fffec55e/560/562/5c2). So cal+0xe vs +0x10 can only shift
**fault/plausibility behavior** between 5 and 7 — e.g. how much torque-tracking deviation is tolerated
before a cut — NOT the torque the motor produces.

**Reconciliation with tester reports of "7 > 5":** consistent, via the monitor plane. If the mode-7
plausibility gain is more permissive than mode-5's, mode 5 could trip the torque-deviation cut
(assist_trq_deviation_monitor / the ctrl_task comparators) sooner under sustained high demand, so
mode 7 *sustains* high torque without being cut — perceived as "more torque" even though the
instantaneous commanded->delivered map is identical. This is a HYPOTHESIS: the two gain cells are RAM
0xfffe8a4a (mode 5) / 0xfffe8a4c (mode 7), coding-loaded from PDU 0x39f, NOT in the static image, so
their ordering/effect on fault thresholds is unverified from this dump. Confirming it needs the 0x39f
coding values or a bench test watching for a mode-5-specific plausibility DTC under high torque.

**Mode 8** is internal-only, NOT commandable: a received status 8 fails the {5,6,7} enable gate. It is
reached by an internal ratchet from 5/7 (FUN_00034d78:259-262) gated on a torque-band handshake
(hca_mode8_torque_band cal+0x308 via cVar33/cStack_51 — engaged + measured column torque over the band,
i.e. driver-override/hands-on) AND coding byte hca_mode8_enable_coding (cal+0x2f5). openpilot cannot
set it via the status field; it would only occur under physical column load. In mode 8 the monitor
gain is 0xffff (full) — again a monitor-plane effect, not delivered torque.

CAVEAT (numeric magnitudes unread): all the cal cells above (+0x306/+0x2a2/+0x2fe/+0x304/+0xe/+0x10/
+0x308/+0x2f5) live in the RAM parameter block (base 0xfffe8a3c, `_ctrl_cal_block_ptr = param_1+0x158`)
loaded from CAN PDU 0x39f — coding-resident, NOT in 8R0909144F_0507.bin (the file=addr−0x12000 rule is
for static flash only). Factory defaults likely in FRF cal blocks DB_3/4/5, needing the 0x39f ODX/A2L
layout to decode.

NOTE: 0xfffed784 (eps_assist_status) is the EPS's INTERNAL assist status, not the received command.

## (b) PLA control loop (park-assist ANGLE path) -- from code
Flow: CAN request/angle -> gating (pla_rx_gate, pla_request_entry FUN_0002b2a0, pla_engage_predicate
FUN_0002b036) -> 3-ch angle limiter pla_angle_limiter_state(0xfffed3b4)/pla_angle_limiter(FUN_0003df8e)
-> pla_angle_out(0xfffeca54..58) -> pla_actuator_write(FUN_00024608). Cyclic: pla_cyclic(FUN_00027e62),
limiter every 4th tick.

RESTRICTIONS (all must hold):
- SPEED GATE (calibratable, NOT a hard EPS overspeed lock): enable requires
  veh_speed(0xfffecaa2) <= pla_speed_gate_cal (=_ctrl_cal_block_ptr+0x1EA, abs 0xfffe8c26), plus a
  secondary gate +0x1EC and a re-check on servo commit (FUN_0002b66a). The threshold is a
  CODING/parametrization value loaded from CAN PDU 0x39f -- not a fixed flash constant. (The hard
  "Geschwindigkeitsueberschreitung" overspeed abort is in the ESP, not this EPS.)
- PLA request status pla_request_status(0xfffec9f0) == 0x0A, held 5 cycles (debounce).
- Operating mode op_mode(0xfffec9e8) == 7.
- Internal assist handshake eps_assist_status == 5 + flags bRamfffecb7c/b82 + supervision.
- Extra cal angle/torque gates: +0x1C2/1C4/1C6/1DA/1DC, cal flag +0x1C9.

MAX RATE OF CHANGE: per-update tracking-term clamp +/-0x30 (+/-48 raw) in pla_angle_limiter, applied
every 4th cyclic tick (tick period is RTOS-scheduled, not in the decompiles). Plus a command-curve
saturation +/-limiter[0xf].

MAX APPLIED: angle-command output clamped to [0, 0x620] (1568 raw) in the limiter; actuator write
re-clamped to 0x640 (1600 raw). Effective ceiling 0x620. Defaults init to 0x320 (800). Units are raw
counts (no scale applied).

## openpilot implication (for controlling the car)
- (a) **Delivered torque is identical for 5 and 7** — same fixed 0x4b motor gain, same main-worker cap
  (+0x306) and ramp (+0x2fe/+0x304). A PID sees no gain change or discontinuity between them. Still
  prefer **7** (it matches stock MLB), because the one real 5-vs-7 difference is in the plausibility/
  monitor plane (FUN_0003857e gain cal+0xe vs +0x10): mode 7 *may* tolerate more torque-tracking
  deviation before a cut, so 5 could trip a plausibility DTC sooner under sustained high torque. That
  is a hypothesis (coding-resident cells, unread) — but there is no downside to using 7.
- (b) PLA is a genuine ANGLE-command path (higher authority than HCA torque in principle) with a
  defined rate limit (+/-0x30/update) and ceiling (0x620). It is NOT hard-locked to parking speed by
  the EPS -- the gate is a coding value (+0x1EA). BUT engaging it needs the full choreography:
  request status 0x0A + op_mode 7 + assist handshake + flags. Sending PLA_01 alone will not engage
  it; you must satisfy (or spoof) the APS/mode/handshake state as well.
