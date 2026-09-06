# EPB output-trace: is EPB dynamic braking anywhere in the ECD actuation path? — NO (code-proven)

Method: invert the search. The reception side (EPB_01 handle 0x25b) is runtime-allocated and opaque,
but the actuation side is static code. Enumerate every writer of the ECD actuation structures and
subtract the known type1/2/4/5 path; any remainder would be a separate EPB/HHC/HBA pressure channel.

## Writers of the 6 ECD pressure setpoints (0x403d94-0x403da0) — PROVEN, exhaustive
Every writer is inside the ECD state machine or its sub-executors — NO outsider:
- `ecd_state_machine` (0x633fc) — the mode/substate dispatcher
- `ecd_decel_pressure_calc` (0x6de38) — type2/comfort executor (speed-gated)
- `ecd_emergency_pressure` (0x9c788) — type4/ANB executor (ungated)
- substate handlers called only from the state machine: `FUN_0006e014`, `FUN_0006e08c`,
  `FUN_00088c50` (substate 8), `FUN_00088cd4` (substate 4)

## Writers of ecd_mode (0x405aba) — PROVEN
Only `decel_req_arbitrate` (0x94a70) and `decel_ctrl_top` (0x9b7b4). The mode the executors dispatch
on comes ONLY from the 4-source arbitration. `decel_hold_escalation_mgr` writes the neighbour byte
0x405abb (the "type 3" hold). `decel_arb_output` (0x405a7c) is written by the arbitration + an init
(`FUN_0009aa78`). `ecd_ctrl_struct` (0x403a14) is only initialised (`ecd_ctrl_struct_init` 0xa10d0).

## The actuation pipeline reads no external pressure request — PROVEN
`ecd_actuation_pipeline` (0x9f190) dispatches its 8 substeps passing ONLY the ECD ctrl struct
(0x403a14, = pointer to the 6 setpoints) + scratch params. The main wheel-pressure controller
`ecd_press_stage_ctrl` (0x69fc0) works purely over the ctrl struct + internal PT1/curve filter states.
There is no separate "external"/"driver"/"EPB" additive pressure input anywhere in this chain.

## CONCLUSION
The output-trace on the ECD subsystem is exhaustive and finds **no EPB injection point at any level**.
Combined with the prior proof that the ECD has exactly four external decel inputs (type1/2/4/5) and
none is EPB, this strengthens the finding: **EPB dynamic braking does not use the ECD subsystem at
all** — not as a decel source, not as a mode, not as a setpoint writer, not as an actuation input.

Therefore EPB's hydraulic braking (if implemented in this variant) must run through the **base ESP
active-pressure-buildup subsystem** (the ABS/ESP hydraulic controller that also does yaw/ABS pressure),
which is a *separate* subsystem NOT covered by this ECD-actuation trace. That base-ESP pressure
controller — and whether it accepts an external "Fremdbremsung"/EPB deceleration request — is the next
target. It is also possible (weaker, note-only) that this variant's EPB path does not command
autonomous ESP hydraulic braking at all.

STATUS: EPB handler NOT found. Ruled out: the entire ECD pressure path (proven exhaustive). Next
target: the base ESP active-pressure/"external brake request" controller (untraced here).
