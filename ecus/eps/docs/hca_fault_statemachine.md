# EPS HCA "not available" fault/init state machine (8R0909144F) — from firmware

Problem: car has no stock lane-assist, so HCA_01 isn't sent until openpilot starts. On HCA start the
EPS reports "not available" and refuses to steer; after seconds-to-minutes it clears. Below: why, and
how to force a few-second clear. State object: `eps_assist_status` @0xfffed784.

## The "available/ready" signal
`ctrl_task` (FUN_00025b9a) each cycle sets `eps_status_flags(0xfffecb7f) bit 0x20 = READY` iff ALL:
1. `eps_assist_status+0x10 == 5` (torque channel in-band [0x1dbc,0x5444), set by assist_trq_plausibility FUN_000177aa)
2. `eps_assist_status+0x50` latch clear (fault_debounce_b FUN_00017cd2)
3. `eps_assist_status+0x51` latch clear (fault_debounce_a FUN_00017b2a)
The internal status (+0x10) is transmitted via tx_assist_status (FUN_00016294) = what the external
controller reads as HCA-available. Separately, the master engage FSM `hca_engage_fsm_state`
(0xfffede5c) must walk 0->5 (state5 = hca_engage_state5 FUN_0002b626 sets assist_engaged bit).

## Why "not available" at first, and why the delay VARIES
Two stacked debounces, both of which RESTART on disturbance:
1. **Engage-FSM dwell timers** (irreducible floor): each state arms hca_dwell_counter(0xfffede72) up
   to hca_dwell_target(0xfffede74) = 400/1000/1000 cycles; fsm_transition_gate (FUN_0002bfe6) only
   advances when counter>=target AND guards met (_op_mode==3, plausibility ==2, cRamfffede70==0).
   Unmet guard => stuck in-state indefinitely (minutes).
2. **Fault-qualification counters** +0x22/+0x24 (fault_debounce_a/b): start 0, increment ONLY while
   assist_engaged (bRamfffecb7e bit1), threshold 0x9bf=2495 cycles (state2). 
3. **Torque-deviation monitor** (assist_trq_deviation_monitor FUN_000178fa) is the RESET source:
   counters +0x2a/+0x2c climb to 0x46=70 whenever |measured-expected| > tol (+0xf8, escalate +0x5ed);
   at 70 it latches +0x18 fault bits + sets +0x52 -> restarts qualification.
=> smooth engage: dwell + one 2495-cycle pass ~= a few seconds. Any torque step / driver counter-torque
/ stream gap re-trips FUN_000178fa or drops the engaged bit -> counter never reaches threshold -> minutes.

## How to guarantee a few-second clear (from code)
1. Send HCA_01 immediately + continuously with a valid rolling COUNTER + CHECKSUM. hca_status defaults
   to 3(off) in steer_sigblock_init; a rejected/gapped frame reverts status to off and resets the
   engaged bit. Never gap the stream.
2. **Ramp torque from ~0, keep it small and smooth — no torque steps.** This is THE lever: it keeps
   |measured-expected| under the +0xf8 tolerance so FUN_000178fa never latches -> no qualification
   restart -> the minutes-long case disappears.
3. Hold status at a full-engage value (5 or 7), never 6(limited) or 3(off), so the engaged bit stays
   set and the qualification counter increments every cycle.
4. Satisfy FSM guards so dwells don't stall: normal run mode (_op_mode==3), allowed speed window,
   torque-sensor supply in range, and DON'T fight the wheel (driver counter-torque trips FUN_000178fa
   and can force the FSM back toward deinit, FUN_0002b7e4 state->10).
You can't beat the fixed dwell floor, but avoiding every reset condition collapses the clear to that
floor (a few seconds). The minutes case is almost certainly torque steps tripping FUN_000178fa and/or
an invalid HCA_01 counter/checksum getting the stream rejected.
