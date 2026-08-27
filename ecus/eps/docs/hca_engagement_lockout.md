# 8R0909144F EPS — ~6-minute max-continuous-HCA-engagement lockout

Mechanism for the observed behavior: holding the EPS in active HCA (received status 5/7)
continuously for ~6 minutes drops lane-keep assist and will not re-arm while the request is held.

## The timer (VERIFIED — directly read)
- **Counter `hca_engage_time_counter` (0xfffede84)** — 32-bit up-counter. Exactly **three** references
  in the image (grep-confirmed), **no decrement**:
  - `+1` every active-state cycle — `hca_active_during_action` (FUN_0002be80, `0002be80.c:11`)
  - trip test `< 180000` — `hca_max_engage_guard` (FUN_0002ae62, `0002ae62.c:15`)
  - `= 0` — `hca_engage_fsm_idle` state 0xb entry (FUN_0002b8b4, `0002b8b4.c:18`)
- **Threshold = 180000** is a **hardcoded flash immediate** in the guard — NOT a coding/PDU-0x39f value.
  So the 6-minute limit is fixed in firmware; changing it needs a flash patch, not re-coding.
- The guard `FUN_0002ae62` fires the disengage transition when engaged (`bRamfffecb7c&0x20`) AND
  (`hca_engage_time_counter >= 180000` OR supervision flag `bRamfffecb80&0x40`). The max-time exit
  shares the fault-supervision exit — a "engaged too long, hand back" design.

## Tick → 6 minutes (back-solved from the observation)
The engage statechart is a slow RTOS runnable; the scheduler decompiles are corrupted so the period
isn't directly readable. But the loop is closed by the observation itself:
- 180000 counts ⇒ ~360 s observed ⇒ **~2 ms/count** (a clean 20:1 divide of the 100 µs base ISR tick;
  2 ms / 500 Hz is the canonical EPS steering-loop rate).
- **Corroboration:** the same during-action arms a companion timer `hca_engage_warn_timer`
  (0xfffeb678) = **90000** (`0000df94.c`). At 2 ms that is **180 s = exactly 3 min** — the round
  {3 min, 6 min} pair only exists at a 2 ms tick. (At the previously-*derived* 1.2 ms these would be
  3.6 min / 3 min — not round, and ≠ the observed 6 min, so 1.2 ms is rejected for this loop.)

**Tick CONFIRMED empirically (2.016 ms → 6.05 min):** measured on route
`15e6fc3f7f90b0c5/00000144--3b27e0c7dc` (independently reproduced). Over a 4003 s highway drive at
~95% engaged duty, the EPS forced **10** timeouts, spaced **364.7 s ± 0.34** (7→4 handover events at
470/835/1200/…/3753 s); the continuous-engagement windows were **ten at ~362.8 s** then a cliff to
185 s. 362.8 s ÷ 180000 = **2.016 ms/count**. So `ctrl_task` = 1.2 ms (`sw_timer_wheel` FUN_0002ddd6)
but this engage statechart is a **separate ~2 ms (500 Hz) supervision runnable** — the 1.2 ms/3.6 min
reading is **refuted** by the data. The ±0.34 s constancy across 10 trips also confirms the counter is
pure engaged-time (torque swung 0–300 cNm within each window without changing the period).

## CAN observability — the timeout IS visible (as a status-4 handover)
The counter `0xfffede84` itself is **never marshalled to CAN** (3 refs: inc/reset/compare; no TX, no
timeout DTC). But the forced disengage is **distinctly observable** on LH_EPS_03 — correcting an
earlier claim here that it "looks identical to a normal disengage":
- At the trip, transmitted **EPS_HCA_Status goes 7 → 4** (4 = ramp-out/handover), **held ~2.04 s**
  (measured, constant), then **4 → 3** (ready). openpilot already keys off it — on route 144 it drops
  HCA_01 7→3 about ~30 ms after seeing EPS status 4. So a controller CAN detect the timeout on the bus.
- **This distinguishes WHO ended the engagement.** EPS-forced disengage (6-min trip or a fault) =
  `EPS_HCA_Status` **7→4→(~2.04 s)→3**. openpilot-initiated release (normal disengage) = **straight
  7→3, no status-4** (because openpilot drops HCA_01 Status→3/Sendestatus→0/Offset→0 first and the EPS
  follows to ready in ~20 ms). So a leading **status-4** is the specific signature of the forced
  lockout/fault; its absence means it was a commanded release. No other LH_EPS_03 field tracks the
  reset (DSR_Status stays 0, Lenkmoment/angle/quality bits are flat or driver-noise) — `EPS_HCA_Status`
  is the only marker.
- **Behavioral signature of the latch:** if you keep commanding active 5/7 after the trip, the counter
  stays saturated (≥180000, no decrement) and the guard re-trips every cycle → the EPS refuses to
  re-latch active. The ~2 s status-4 handover repeating is the tell.
- **Reset (measured ~2.0 s):** the status-4 window (≈2.04 s) is the sustained non-active interval that
  walks the FSM to idle 0x0b and zeroes the counter; after 4→3, re-request and status returns 3→7
  within ~50 ms with a fresh 6-min budget. Brief single-frame 7→3→7 blips do **not** reset it — route
  144 had ~30 such blips per window and still tripped at 362.8 s every time.

## Reset — it is an EVENT, not a cooldown
- The counter resets **only** when the engage FSM reaches idle state 0xb (`FUN_0002b8b4`). There is
  **no timed drain / no symmetric 6-min cooldown**.
- State 0xb is reachable **only when the received HCA request goes non-active (status 3 / no HCA)** —
  the down-path states clear the engage flags and wait on `_op_mode`.
- **So while an external controller keeps commanding active HCA (5/7), the FSM cannot reach 0xb, the
  counter stays saturated at 180000, and the guard forces disengage every cycle → sustained lockout.**
  This is exactly the observed "hold active → after 6 min it drops and won't re-arm."
- Once the request IS released, the down-walk completes on the FSM's short dwells (the `_op_mode`-wait
  during-actions use ~0x28=40-step ≈ 80 ms timeouts), i.e. **sub-second to ~a couple seconds**, then
  the counter is zeroed. To assist again it re-climbs the engage dwells (state1=400, state2=1000,
  state3=1000 = **2400 steps ≈ 4.8 s at 2 ms**), after which a **fresh 180000 (6-min) budget starts
  from 0**. (Down-path exact dwell: MEDIUM confidence — the transition dispatch is table-driven and
  not in the clean decompile set.)

**Practical: a brief non-active blip (send status 3 for a fraction of a second, before 6 min) resets
the entire budget.** Periodically toggling non-active avoids the lockout entirely.

## Driver-override (internal mode 8) does NOT reset it
Internal **mode 8** (column torque > `_ctrl_cal_block_ptr+0x308` band, hands-on) lives in the torque
worker `FUN_00034d78` — a **different subsystem** from the engage FSM. `hca_engage_time_counter` is a
during-action of the engage chart's **active state**, whose state (`uRamfffede5c`) is driven by the
**received HCA status (5/7)** + `_op_mode`, not by the torque-override mode; the increment
(`0002be80.c:11`) is **unconditional** while the active state runs. So a hands-on override, as long as
the controller still commands 5/7, **keeps the counter ticking — it neither resets nor pauses the
lockout.** (MEDIUM-HIGH confidence.) The only thing that resets it is actually releasing the request.

Empirical status (routes 144/155/178): the torque-independence within each 362.8 s window on route 144
(period constant to ±0.34 s while torque swung 0–300 cNm) is consistent with this, but **no available
route isolates** the "sustained driver override while openpilot still holds HCA_01 = 7" case — a real
hands-on/curve override makes openpilot drop the request first (route 155's near-miss at 358.2 s ended
HCA-first on a driver torque spike to ~198 cNm, resetting via the ordinary disengage path). So
"override keeps accumulating" stays firmware-derived, not yet cleanly measured; confirming it needs a
route with sustained column torque while HCA_01 stays 7, checking whether the ~362.8 s trip still fires.

## Addresses
counter `0xFFFEDE84`; guard `FUN_0002ae62`; increment/during `FUN_0002be80`; idle-reset `FUN_0002b8b4`;
FSM state `0xFFFEDE5C`; supervision-trip bit `0xFFFECB80 & 0x40`; companion 3-min timer `0xFFFEB678`;
re-engage dwell counter/target `0xFFFEDE72`/`0xFFFEDE74`.
