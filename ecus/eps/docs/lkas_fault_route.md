# LKAS "Restart the car" fault — route 35258b7bb90057ff/00000005--af6565b8cb

## What happened (from the rlogs)
- t=0.0s: EPS reports `EPS_HCA_Status = READY (3)`.
- t=1.0s: EPS -> `FAULT (2)` **on its own**, BEFORE openpilot sends any HCA (first HCA_01 tx @8.95s).
  Stays FAULT the entire 933s route. Car stationary/park; panda in `elm327` until 9.13s then
  `volkswagenMlb`. No bus-0 message dropped at t=1s -> the EPS faulted itself (expected for a car with
  no factory lane assist: it advertises "no HCA controller present").
- openpilot: `steerFaultPermanent=True` from t=2.7s -> alert **"LKAS Fault: Restart the car to engage"**.
- openpilot EVER sent `HCA_01_Status_HCA` = **{3}** only (off) -- never 5 or 7, never engaged
  (`carControl.enabled=False` whole route).

## Root cause = openpilot/EPS deadlock (not a firmware bug)
`opendbc .../volkswagen/carstate.py::update_hca_state`:
```py
self.eps_init_complete = ... or (hca_status in ("DISABLED","READY","ACTIVE") or self.frame>600)
perm_fault = in_drive and hca_status=="DISABLED" or (self.eps_init_complete and hca_status=="FAULT")
```
The boot-time READY sets `eps_init_complete=True`; the subsequent FAULT then trips `perm_fault`, which
hard-blocks engagement. But whether the EPS *itself* can still recover is a separate, EPS-side question
answered by the multi-route data below.

## Multi-route findings (VERIFIED, log-measured) — corrects the earlier recovery model
The EPS boot fault is NOT simply "only clears on a {5,7} engage stream" (an earlier claim here). It has
a **recoverable soft-fault window then a hard latch**:

| route | EPS 3→2 (FAULT) | openpilot HCA_01 starts | Status sent | EPS outcome |
|---|---|---|---|---|
| `00000001` | 0.709 s | 7.26 s | **3 only** | **RECOVERED 2→3 (READY) at 7.78 s** |
| `00000002` | 0.517 s | 7.08 s | 3 only | latched FAULT (power-cycle) |
| `00000000` | 0.659 s | 11.68 s | 3 only | latched FAULT |
| `00000005` | 1.043 s | 8.95 s | 3 only | latched FAULT 923 s |

Key corrections (all verified by direct `EPS_HCA_Status` measurement):
- **FAULT(2) → READY(3) recovers with `Status_HCA = 3`** — it does NOT require a {5,6,7} request. Route
  00000001 proves it (2→3, ~0.5 s after HCA_01 appeared, openpilot sending only status 3). The
  reception supervision clears once valid HCA_01 is simply *present in time*.
- The **{5,6,7} requirement is for READY(3) → ACTIVE(7)** (actually engaging/steering), a *different*
  transition — not for clearing the fault to READY. The earlier doc conflated the two.
- Routes that stayed latched (00000000/00000002/00000005) are ones where HCA_01 arrived **after** the
  supervision committed a hard DTC → then nothing on the bus clears it; only a power cycle does.
- The recoverable/latch boundary is **marginal and not monotonic in openpilot-time** (00000001 recovered
  with HCA at 7.26 s; 00000002 latched with HCA *earlier* at 7.08 s). The deadline is measured against
  the EPS's own power-up clock, whose offset to log-start differs per route — so at openpilot's ~7 s
  application-layer start it is effectively a coin-flip.
- NOT verified: the claim (from a since-killed agent) that 00000001 "LKAS actively steered 46%" — its
  later segments aren't uploaded and the readable segments show openpilot sending only Status=3
  (READY/standby, not active steering).

## Adversarial refinements (a skeptic pass broke 3 overstated claims — all verified)
- **Bit 0x100 is not single-sourced.** Besides `hca_fault_bit_recompute` (FUN_0001d906), a second
  writer `hca_fault_aggregate_gate` (FUN_0001d972, dispatched *after* it for supervision idx 0xa2/a3/a6
  — likely the redundant-HCA domain) force-sets `_sigblock_status_a |= 0xc1f9` (incl. 0x100) and SKIPS
  the recompute when any of `fffea1a0/1ac/19c` is stale. So recovery needs those aggregates fresh too,
  not just the two HCA channel flags.
- **"Nothing clears the freeze bit" was wrong.** Bit0 is the LSB of a 4-bit supervision *state* nibble;
  `superv_timestamp_countdown` (FUN_0007881e) writes states 2/8 (bit0=0) at runtime. BUT that recovery
  branch requires the entry's timestamp != 0, and `superv_freeze_msg` zeroes it — so a *frozen* entry's
  recovery path is inert and it stays latched. No reachable runtime clear of a latched HCA entry was
  found (the re-init gate `DAT_fffecaa5` has no nonzero setter); a UDS ClearDTC path could not be
  confirmed or excluded. Net: still power-cycle in practice, but via a zeroed-timestamp inert path,
  not an immutable bit.
- **The streams are NOT byte-identical.** Measured: the recovered route (00000001) has a pristine 20 ms
  HCA_01 cadence with 0 inter-frame gaps >30 ms; all three latched routes are jittery (~30 ms gaps in
  the critical window). Per-frame content (counter continuity, checksum) is still valid in all, and the
  jitter is likely too small to trip the 601-tick E2E timeout — and 00000002's HCA arrived *earlier*
  (7.075 s) than 00000001's (7.260 s) yet latched — so the boot-clock timing race survives as the core
  explanation, but "not content" is false and the jitter/`0xa2-a6` aggregate remain unexcluded confounds.

## Open items from the adversarial pass — now resolved
- **The `0xa2/a3/a6` aggregate = the redundant HCA sub-channels, not a foreign fault.** Those indices
  get state-4/5 handling in `hca_superv_state_to_freshflag`, and states 4/5 are the C/D channels of the
  same HCA E2E state machine; `superv_dtc_process_cycle` passes `hca_rx_superv_struct` (0xfffed66c) for
  them. So `hca_fault_aggregate_gate` (FUN_0001d972) is the HCA fault aggregated over all 4 redundant
  channels. Refinement to the model: recovery to READY needs **all 4** HCA channels fresh, not just the
  2 primary flags — a single stock HCA_01 feeds them (route 00000001 recovered on Status=3 alone).
- **Jitter is NOT the cause (H4 confound closed).** The ~30 ms "gaps" were on openpilot's `src==128`
  sendcan-queue timestamps, not verified bus reception; the E2E **rolling COUNTERs were continuous with
  zero sequence errors** — i.e. no HCA frame was actually lost. E2E freshness keys on counter
  continuity plus a staleness timeout, and the channel timeout is **601 cycles** (`0x259` in `d2f2`),
  so sporadic 30 ms TX-queue jitter cannot accumulate to trip it. The determinant therefore stands as
  the boot-clock **timing race** (first valid HCA vs the missing-message confirmation deadline), with
  jitter demoted from confound to artifact.

## The real recovery model — NOT a pure timer (a 4-channel + assist-active gate)
Empirical fact that broke the pure-timer model: on a MOVING drive, openpilot can cold-boot 30 s+ (EPS
already faulted), start HCA_01, and the fault clears in a few seconds. A fixed boot-clock deadline
can't do that. Traced + verified mechanism:

`hca_rx_e2e_statemachine` (FUN_0001d2f2) aggregates **4** supervision channels into `+0x28`, and the
two redundant HCA DTC indices (`0xa2`=msgid 0x6c, `0xa6`=msgid 0x6d) only BOTH heal when the aggregate
is state **1 or 3** (`d5ec`: 0xa2 heals at {1,3,4}, 0xa6 at {1,3,5}). Sources:
- **ch1 (`+0x14`) = the boot-clock race.** Fresh iff `boot_tick-0x2c9c > const`, else times out after
  601 cycles and sets the `+0x36` latch. Aggregate state 1. Winning this = recovery even parked.
- **ch2 (`+0x10`) = ASSIST-ACTIVE.** Fresh (code 5) iff `eps_status_flags2(0xfffecb7c) & 0x40 == 0`,
  which (debounced ~300-count) = **`hw_assist_status_sfr(0xfffff400)` bit 4** (`FUN_0002919e`) — a
  motor-drive/safing 'assist active' hardware discrete, NOT vehicle speed. Aggregate state 3.
- **ch3/ch4 (`+0x18`/`+0x1c`) = HCA_01 reception itself.** Give aggregate state 4 or 5, which each heal
  only ONE redundant index, so `hca_fault_aggregate_gate` (FUN_0001d972) still force-sets bit 0x100.
  **=> pure HCA_01 presence cannot clear the fault by itself.**

And the confirmed-DTC commit (`hca_missing_msg_dtc_commit` d4aa:33, flags 0x31 => needs `+0x10==2`) is
BLOCKED while ch2 is fresh. So ch2/assist-active both **rescues** the fault and **prevents the latch**.

This explains every case:
| route | vEgo@window | boot race | assist(ch2) | outcome |
|---|---|---|---|---|
| 00000001 | parked | **won** | quiescent | recover (via ch1) |
| 00000002 | parked | lost | quiescent | **latch** |
| 00000005 | parked | lost | quiescent | **latch** |
| 00000000 | parked | lost | quiescent | **latch** |
| user's drives | MOVING/steering | lost (30 s late) | **active** | recover (via ch2) |

(Data note: 00000001/00000002 were both parked for the first ~16-18 s despite a high whole-segment
moving%, so among these 4 the split is the ch1 boot-race; the ch2 rescue is what saves the user's
moving drives.) Confidence: wiring verified; MEDIUM only on `0xfffff400` bit4's exact meaning/polarity.
Decisive bench test: park + hand-steer (assist engaged) with valid HCA_01 — if it recovers while a
still-wheel park latches, the gate is "assist/steering active," not "vehicle moving."

**Spoofability / recovery of a parked latch:** ch2's only input is `hw_assist_status_sfr` (0xfffff400)
bit 4 — a READ-ONLY hardware readback from the safing/motor-driver chip (never written in firmware).
So it CANNOT be spoofed over CAN or software. The only way to flip it is physical: apply steering
torque -> base power-assist drives the motor -> the chip's bit4 goes active -> (~300-count debounce)
ch2 fresh -> fault clears. Consequences: (a) a stuck PARKED LKAS fault clears if the driver briefly
turns/wiggles the wheel (with valid HCA_01 present); (b) openpilot cannot self-recover a parked latch
(its only actuator is faulted HCA torque; it can't turn the wheel) -> the panda boot-grace HCA_01
heartbeat remains the ONLY automatic fix for standstill; (c) moving drives auto-heal because normal
steering keeps bit4 active.

## Fix (prevent in future drives)
Two independent layers:
1. **Prevent the fault (primary, boot-timing):** get a valid neutral `HCA_01` (Status=3, correct rolling
   counter/checksum) on the bus **within the EPS's ~1 s power-up grace**, well before the latch. The
   openpilot application layer can't (it starts ~7–12 s), so this belongs in **panda firmware** (panda
   boots <1 s). Route 00000001 shows a *present* HCA_01 is sufficient to clear the soft fault; it just
   has to arrive before the EPS gives up.
2. **Respond correctly if already faulted (carstate):** in `update_hca_state`, treat EPS `FAULT` as
   temporary (honor the code's own comment) so openpilot keeps trying rather than latching
   "steerUnavailable". This cannot rescue a *hard-latched* EPS (00000005 stayed FAULT 923 s with valid
   HCA_01 present), so it's complementary to (1), not a substitute. To then ENGAGE, openpilot must send
   Status=7 + valid counter/checksum with torque ramped gently from 0.
