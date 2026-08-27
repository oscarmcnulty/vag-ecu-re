# "HCA1 torque limiting" on 8K0907144L — the honest answer

## TL;DR

**This EPS has no HCA1 message, so there is no HCA1 torque limit to describe.**

`HCA_01` ("Heading Control Assist") is the **VW MQB** message by which a lane-keep/ADAS
controller requests a steering torque from the EPS, and it is the MQB EPS that enforces the
familiar limits (a ~3 Nm saturation, a rate limit, and a "max torque held too long → fault
& drop out" cutout). openpilot steers MQB cars through exactly that message.

`8K0907144L` is a **B8-platform ZF Lenksysteme EPS from 2013 — a pre-MQB generation**. Its
complete set of received/validated CAN messages (proven from the on-chip `KFC_*` fault enum)
is standard chassis traffic only:

- `ESP_03/04/05/06` — wheel speeds / vehicle dynamics (→ speed-dependent assist)
- `MOTOR_02/03` — engine running / terminal status (→ assist enable)
- `LWI_01` — steering-wheel angle sensor
- `CHARISMA_01` — Audi drive-select mode (comfort/dynamic → assist weighting)
- `LH_EPS_02`, `VIN_01`, `KLEMMENSTATUS_01`, `GATEWAY_11`, `DIAGNOSE_01` — partner/housekeeping

There is **no** HCA, lane-assist, camera, or park-assist message anywhere in the image, and
no corresponding fault, signal, or string. This unit cannot be commanded to steer by
injecting an HCA-style torque request — it isn't listening for one. (This matches openpilot
supporting VW **MQB** and not the older B8/PQ EPS.)

## What torque limiting this ECU *does* implement

It is a **variable power-assist** unit (badged `SCU_B8` / `DYNAMIKLENK.`), so the torque it
controls is the **assist motor torque it generates itself**, computed from the driver's own
steering-wheel torque, vehicle speed, and drive mode — not an external request. The limits
on that internally-generated torque, all evidenced by the `KFC_*` monitor enum, are:

- **Servo power / torque cap** — `KFC_EPS_SERVO_POWER_RANGE`, `KFC_EPS_REV_RESERVE_RANGE`
- **Phase-current limit** — `KFC_PHASE_CURRENT_RANGE`, `KFC_PHASE_IIT_2H_*` (I²t), `KFC_POWERSTAGEDRV_I2H`
- **Thermal derate** — `KFC_TEMP_RANGE`, `KFC_TEMP_HR_T2H`, `KFC_TEMP_LR_T2H`
- **Voltage/supply derate** — `KFC_TERM30_*_U2L/U2H`
- **End-stop torque reduction** — `KFC_END_STOP_2H`, `KFC_END_STOP_LOAD2H_*`
- **Actuator state gating** — the `AssistanceControl` / `StandbyMotorHold` / `SecureRatio`
  state machine only allows assist in the driving states.

The assist magnitude itself comes from a boost-curve calibration (Kennlinie of driver-torque
vs. speed, weighted by the CHARISMA mode), which lives in the cal region `0x50000..0x75000`.

## Status / caveats

- Pinning the exact numeric caps (the servo-power ceiling, the boost curve) to addresses
  requires finishing the V850 analysis (resolve `callt`/`gp`/split-immediate pointers — see
  `RE_findings.md`). The list above is grounded in the firmware's own labels; the specific
  constants are not yet traced.
- If the goal is openpilot lateral on the B8 Q5: this EPS is the wrong lever — there is no
  torque-injection path in it. Options are a steering-angle overlay actuator (if the car has
  Dynamic Steering) or a donor MQB-generation EPS, not an HCA message to this unit.
