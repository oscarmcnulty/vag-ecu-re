# ESP decel/brake control — struct field maps — 8R0907379BG

Field maps for the key RAM structs so the raw Ghidra decompilation (`*(short*)(p + 0x46)` etc.)
reads naturally. Offsets are byte offsets from the struct base. Derived from the traced control
functions; unproven fields marked `?`.

## decel request record — 12 bytes (array built by `decel_req_assemble`, read by `decel_req_arbitrate`)
| off | type | field | notes |
|---|---|---|---|
| +0x0 | s16 | `decel_primary` | slewed request value; MAX-arbitrated (primary) |
| +0x2 | s16 | `aux_a` | winner-copied jerk/limit field |
| +0x4 | s16 | `aux_b` | winner-copied jerk/limit field |
| +0x6 | u8 | `type` | 1/2/4/5 → becomes `ecd_mode` |
| +0x8 | s16 | `decel_raw` | un-slewed value; MAX-arbitrated (secondary/preempt) |
| +0xa | u8 | `type2` | dup of type for secondary channel |
| +0xb | u8 | `mode_flag` | nonzero only for type2 (comfort) |

## `decel_arb_output` @0x405a7c (written by `decel_req_arbitrate`, shaped by `decel_hold_escalation_mgr`)
| off | field | notes |
|---|---|---|
| +0x6 | `winner_aux_a` | aux of the winning request |
| +0x8 | `winner_aux_b` | |
| +0x10 | `decel_primary_max` | winning primary deceleration |
| +0x12 | `decel_secondary_max` | winning raw/preempt deceleration |
| +0x36 | `type_secondary` | secondary winner type |
| +0x37 | `type_secondary_prev` | last cycle (preempt edge-detect) |
| +0x39 | `winner_flag` | mode flag of winner |
| +0x3a | `hold_state` | 0/1/2 escalation (decel_hold_escalation_mgr) |
| +0x3b | `flags` | bit0x20 = secondary-preempt-armed; bit0x80 = type5 enable |
Winning **type byte** is written separately to `ecd_mode` (0x405aba).

## `ecd_ctrl_struct` @0x403a14 (init `ecd_ctrl_struct_init` 0xa10d0; consumed `ecd_actuation_pipeline` 0x9f190)
| off | type | field | notes |
|---|---|---|---|
| +0x0 | u16 | `slot_count` | =6 |
| +0x8 | ptr | `setpoint_ptr` | → the 6 pressure setpoints (0x403d94) |
| +0x10 | ptr | `setpoint_ptr2` | secondary/mirror |
| +0xf..+0x13 | u8 | `phase_timing[]` | e.g. emergency {0x14,10,3,7}; comfort {0x32,7,7} |
| +0x1a.. | s16 | `phase_pressure[]` | per-phase pressure profile |

## `ecd_pressure_setpoints` @0x403d94 — the 6 setpoints
6×s16. `ecd_emergency_pressure` sets all six = the ANB request value (FLAT). `ecd_decel_pressure_calc`
fills a ramp (e.g. 500/1000/2000/2500). Consumed via `ecd_ctrl_struct+8`.

## ECD status struct (param_1 of `ecd_prefill_gate` 0x6f5b8 and the executors)
| off | field | notes |
|---|---|---|
| +0x3c | `v_ref` | vehicle speed (0.125 km/h); <0x28=5km/h checks |
| +0x46 | `demand_front?` | >0 ⇒ active |
| +0x4e | `demand_rear?` | |
| +0x5a | `signed_gate` | <0 branch in pipeline |
| +0x9e | `mode_sub` | |
| +0xc0 | `press_meas?` | <10 ⇒ skip |
| +0xc6 | `counter` | <0x3c gate |
| +0x11c/+0x11e/+0x120/+0x122 | `wheel_press_demand[]` | per-wheel pressure demand |
| +0x14c | `mode` | 0/1/2 |
| +0xd0 | `prefill_cmd` | 0x14 pre-charge / 0 (set by ecd_prefill_gate) |

## `anb_request_struct` @0x407bc4 (psVar14 in `anb_decel_request_build` 0x4bf3c)
| off | field | notes |
|---|---|---|
| +0x0 | `active_ticks` | increments while active (`*psVar14 += 1`) |
| +0xc | `press[6]?` | request pressures |
| +0x16 | u32 `status_flags` | plausibility/exit bits (0x1e..0x1d = release triggers) |
| +0x12 (short6) | `limit=0x2422` | saturation for +0x4 tick counter |
| +0xe/+0x14/+0x16 | counters | `release_ramp_ctr` saturates 0x1e=30 (graceful ramp) |
| +0x2f | u8 `state_byte` | bit0x40 target, bit0x80 → ANB enable to 0x407bbb |
Value at **0x407c0a** = requested decel/pressure broadcast to all 6 setpoints by the executor.

---
See `decel_paths.md` (pipeline), `can_brake_inventory.md` (CAN sources), `symbols.csv` (labels).
