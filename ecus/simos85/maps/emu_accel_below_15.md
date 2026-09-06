# Emulation validation: acceleration below 15 km/h (ACC_01 path)

**Question (openpilot ACC_01 integration).** Deceleration drops out below ~15 km/h because the ESP
withdraws ECD. Is *acceleration* independently gated below 15 km/h anywhere in the engine, or will the
Simos honour a positive `ACC_01.ACC_Sollbeschleunigung` all the way down?

**Answer: the engine's acceleration/torque path has no 15 km/h floor** — its only internal speed gate
is `C_VS_MIN_CRU = 3.0 km/h` (a near-standstill / integrator-reset branch, not a torque cutoff), and the
15 km/h values in the image are the reporting-only L2 crawl monitor (`low_speed_floors.md` §1) that never
touches the torque path. **But in practice both accel and decel still die at ~15 km/h**, because the ESP
asserts `ECD_nicht_verfuegbar` there, which `801408bc` turns into `d000b296 = 0` + the `a5a2` inhibit and
the CRUC state machine **deactivates** the whole ACC (`low_speed_floors.md` §2, confirmed on-car). So the
torque path would honour a positive request down to 3 km/h, but it never gets the chance — the ACC drops
to standby at 15. The lever is the ESP's ECD speed threshold, not an engine cal.

This was already the static conclusion; below is the **p-code emulation** that confirms it on the real
image. Firmware cal values (read direct from `8R0907551F_Original.bin`): `C_VS_MIN_CRU @0x8007a26a` = raw
384 = **3.0 km/h** (1/128 scale); `C_VS_MIN_AC_CTL_CRU @0x80079536` = 384 = 3.0; `C_VS_MIN_CRU_MON
@0x800794ef/f2` = **15**; `cal_acc_frame_select @0x80043bc6` = 0x0900 (ACC_01 active); ECD-select
`@0x80043cd0` = 0x01 (`ECD_nicht_verfuegbar` operative).

## Method

Ghidra `EmulatorHelper` (TriCore 1.3), one function at a time, to completion. Harness sets CSA/FCX/LCX,
base regs `a0/a1/a8` (per `ecu.conf`), SP `a10`, a return sentinel in `a11`, and **mirrors the flash cal
window `0x80040000-0x800a0000` into the `0xa0` uncached alias** — the in-image cal base pointers are the
`0xa0…` form (`*0x80090f94 = 0xa007a204`, `*0x80090f80 = 0xa00793a0`) and this image does not map that
alias, so cal derefs fault without the mirror. Scripts: `ghidra_scripts/EmuAccelFloor.java`,
`ghidra_scripts/EmuDecelGate.java`. Reproduce:

    source ../../.env.sh
    "$GHIDRA_HOME/support/analyzeHeadless" ghidra_proj Simos85 -process 8R0907551F_Original.bin \
      -noanalysis -scriptPath ghidra_scripts -postScript EmuAccelFloor.java 801e9b86 4000000

## Result 1 — torque controller `cruise_torque_pi_controller` (0x801e9b86), ego-speed sweep

Seeded a regulating state (positive accel request `d0007bac`, `e2c1`/`cVar14` path live), swept ego speed
`d000d644` (1/128 km/h). Observed `d000e2c5` = the near-standstill branch flag (the single speed compare,
line 293: `d000d644 < cal[+0x66]`), the torque outputs, and total step count.

| ego km/h | e2c5 (standstill) | e2e8 / e2e2 / e2ec / e2f0 (torque terms) | steps |
|---|---|---|---|
| 0  | **1** | 0 / 10000 / 10000 / 0 | 426 |
| 2  | **1** | 0 / 10000 / 10000 / 0 | 426 |
| 3  | 0 | 0 / 10000 / 10000 / 0 | 428 |
| 4  | 0 | 0 / 10000 / 10000 / 0 | 428 |
| 5  | 0 | 0 / 10000 / 10000 / 0 | 428 |
| 10 | 0 | 0 / 10000 / 10000 / 0 | 428 |
| 14 | 0 | 0 / 10000 / 10000 / 0 | 428 |
| 20 | 0 | 0 / 10000 / 10000 / 0 | 428 |

- The near-standstill flag flips **exactly at 3.0 km/h** (raw 384; strict `<`, so 3 km/h already reads
  "moving"). That is `C_VS_MIN_CRU`, confirmed live.
- **Everything at 5, 10, 14, 20 km/h is byte-identical** — same outputs, same 428 steps. There is **no
  branch, no output change and no step-count change at 15 km/h**, or anywhere between 3 and 20. The
  controller never reads the 15 km/h cal.
- So a positive acceleration request is regulated identically at 5 km/h and at 20 km/h. No 15 km/h accel
  floor exists in the torque path.

## Result 2 — brake formation `acc_brake_request_formation` (0x8013c5d4)

Two sweeps. **(A)** fix ego = 10 km/h, vary the ESP ECD mode `d000b296` ∈ {0,1,2}. **(B)** fix mode = 2
(ECD available), vary ego speed. Ran to completion (RET); observed the brake request `Ramd0007c9a` and
the execution path length.

| sweep | variable | brake path flow |
|---|---|---|
| A: ego=10, mode 0 | b296=0 | 6171 steps |
| A: ego=10, mode 1 | b296=1 | 6171 steps |
| A: ego=10, mode 2 | b296=2 | **6168 steps** |
| B: mode=2, ego ∈ {2,5,10,14,20} | ego | **6168 steps at every speed (identical)** |

- **Ego-speed invariant:** at ECD mode 2 the brake-formation function executes identically for 2, 5, 10,
  14 and 20 km/h — no ego-speed branch exists in it.
- **ECD-mode sensitive:** changing `d000b296` from 2 to 0/1 changes the path (the three `mode == 2`
  gates at lines 554 / 695 / 1025). So the decel path tracks the **external ECD verdict**, not vehicle
  speed. (`Ramd0007c9a` itself saturated to `0x7237` = −3.0 m/s² under the synthetic max-decel input, so
  its magnitude is not the discriminator here; the flow divergence is.)

## Consequence for the ACC_01 injection

- **Accel below 15 km/h needs no engine change.** The Simos regulates a positive `ACC_Sollbeschleunigung`
  identically from 20 km/h down to 3 km/h; below 3 km/h it enters the standstill/integrator regime
  (`C_VS_MIN_CRU`), not a hard cutoff. Editing the 15 km/h cals (`0x800794ef/f2`) changes only the 0x5C0
  telltale, never torque.
- **Decel below ~15 km/h is the ESP's call**, delivered through `ECD_nicht_verfuegbar` → `d000b296 ≠ 2`.
  Not fixable from this image; needs the ESP to grant ECD (see the ESP8 pack) or a different actuator.
- **Scope caveat (honest):** these runs validate the *torque-production* and *brake-formation* gates in
  isolation. Whether ACC stays *engaged* at low speed is the CRUC state machine
  (`acc_flow.md` §4.3 — no internal speed floor either, regulates to 0 km/h), whose permission inputs
  (`a587`, ESP flags, radar) are computed outside this image and were not emulated here.

---

# Full-ECU emulation

Asked to validate this by booting the whole image rather than isolated functions. Two things came out
of it: a cold-boot attempt that does **not** converge, and a link-by-link emulation of the real
longitudinal pipeline that does.

## Whole-ECU boot: escaping the boot loop and reaching the scheduler

The first cold-boot attempt stalled forever in an init poll. Iterating on the boot harness
(`research/emulation/EmuBoot2.java`) got the whole ECU **out of the boot loop and into the run-mode
scheduler with the cyclic tasks executing**. What it took:

1. **Root-caused the boot loop.** `main` (`0x80021140`) runs an init chain
   (`FUN_801b3db8`) full of `do { r = ready(); } while (r == 0)` gates whose ready-flags are set by
   ISRs/callbacks that never fire under a sequential emulator. The first trap was
   `while (DAT_d000177a == 0)` at `0x800aa29c` (`FUN_800aa4e0` returns byte `0xd000177a`, set by the
   ISR-style `init_system_state` @`0x800aa4d0`). ~5.5 M steps span there.
2. **Reference-based flag poking.** The harness's `loadEA` couldn't resolve an absolute load operand
   (`ld.bu d2,0xd000177a`), so it never poked that flag. Added `refReadEA()` using Ghidra's computed
   data references; the small-loop spin-breaker now pokes any `0xd000xxxx` completion flag it polls.
3. **Generic poll-breaker.** For ready-checks too large for the ≤120-PC spin window, added a
   backward-conditional-branch breaker: a branch taken >40 000 times within a decaying window is forced
   to fall through, regardless of the ready-function's size. Broke the `0x801b3ddc` poll.
4. **Catch `Throwable`, suppress the WARN flood, stub the reset handler.** Ghidra's p-code throws
   `Error` (not `Exception`) on some ops; catching only `Exception` silently killed the run. Widened
   RAM zeroing to kill the ~1 M "uninitialized read" WARN lines, and added the terminal reset handler
   `0x8002ed60` to the return-stub set.
5. **Bridge to run-mode.** `main`'s `fullInit` path is stubbed to force CAN init (needed to bring the
   Com context up). Once the Com context materialised (`c03fc37c = 0x800860ec`, ~step 2 M), bridging
   `pc` to the run-mode scheduler `FUN_80021214` (`0x80021214`) — the call `main` itself makes on the
   normal path — ran the scheduler.

**Result:** boot runs the full init sequence (1950 functions executed, Com context live) and the
run-mode scheduler dispatches its cyclic tasks — **`0x80028348`, `0x8002837e`, `0x8002842c` all
execute** (`tasks_ran`), the scheduler context advancing to `0x80030be0`. Reproduce:

    "$GHIDRA_HOME/support/analyzeHeadless" ghidra_proj Simos85 -process 8R0907551F_Original.bin       -noanalysis -scriptPath ../../research/emulation       -postScript EmuBoot2.java 80021140 12000000 -1 -1 -1 -1 1 3500000

**Ceiling (honest).** After the first task pass the ECU heads into a reset/limp region (`0x8002exxx`):
internal L2/watchdog monitors expect real interrupt cadence and sensor data that a sequential p-code
emulator cannot supply, so a monitor trips. That is a monitor firing, not a boot loop, and sustaining a
steady multi-cycle run would mean modelling those monitors and a timer-ISR tick. The escape from the
boot loop and the single scheduler pass are real and reproducible; they do not change the accel-floor
conclusion, which the pipeline runs below establish directly.

## Pipeline emulation — ingress → torque, on real code

`ghidra_scripts/EmuAccIngress.java`. Crafted an E2E-valid ACC_01 (0x109) frame carrying **+1.0 m/s²**
and ran it through the real decoder, then fed the decoded command into the torque controller.

- **Frame** `73 01 00 6c 06 00 00 10` — XOR-all-8 = 0x08 (the MLB E2E seed for 0x109), byte1 low-nibble
  nonzero (first-frame counter sync), `(b4&7)<<8|b3 = 0x66c`.
- **Link 1 — `canrx_ACC_01_DCC1_109` (0x801383e8):** decodes `d0007bac = 0x66c = +1.00 m/s²`, E2E error
  flag `a3c0 = 0` (accepted), `ACC_Status_ACC = 1`. The decoder reads **no ego-speed variable**, so it
  accepts the same accel command at any speed.
- **Link 2 — `cruise_torque_pi_controller` (0x801e9b86)** fed that decoded command, ego sweep: standstill
  flag flips at 3 km/h; identical at 5/10/14/20 km/h (Result 1 above), now with the accel value that
  came out of the real decoder rather than a hand-set one.
- **Link 3 — `acc_brake_request_formation` (0x8013c5d4):** decel flow tracks the ECD mode byte, not speed
  (Result 2 above).

So every real link from CAN bytes to engine-torque gate was executed on the firmware: a valid ACC_01
positive-accel command is accepted and regulated identically from 20 km/h down to 3 km/h, and nothing on
that path consults a 15 km/h threshold. The 15 km/h effect is confined to deceleration via the external
ESP ECD verdict. The one thing not reconstructable in-image is whether ACC is *engaged* at all
(CRUC permission word), which is a radar/ESP-domain input, not a speed floor.

---

# Is there an L2 (EGAS) gate that faults on acceleration below 15 km/h?

**No.** The EGAS Level-2 acceleration-side monitor reads no vehicle speed, and its fault does not key on
15 km/h. Traced:

- `egas_l2_cruise_torque_monitor` (`0x8009c0b4`) and its companion (`0x8009cf94`), refresh (`0x8009ffd0`)
  and cal-init (`0x800a0c9c`) read **none** of the ego-speed variables (`d000d644`, `d000da54`,
  `Ramd0005618`, `d0007ce8`) — verified by grep (0 hits each).
- The `15`-valued cals in the L2 path (`C_VS_MIN_CRU_MON` twin `0x800456c0`/`0x456bd`, and
  `WORD_ARRAY_800456dd[2]/[3]`) are used as **debounce-cycle counts / `^0xff` ASIL shadow constants**
  (compared against the debounce counter `d000ae80`), **not** against vehicle speed.
- Despite its name, `egas_l2_cruise_speed_monitor_fault` (`d000a040`) is a **torque** fault: set at
  `8009c0b4:460` when permitted torque `< ` requested ACC torque (`acc_engine_torque_request >> 8`) after
  a ~12-cycle debounce (`FUN_8009110c`). No speed input.
- The aggregate `d000a03b` (`= a03c || a040 || d1856`, `8009c0b4:837`) is documented re-trace as
  **speed-independent**; it feeds Route-A fault bit 0x40 → `a59c` → CRUC **status 3**
  (`Fehler_GRA_ACC_nicht_moeglich`) and latches the GRA fault `a551`.

**So the L2 layer that CAN deactivate ACC is a torque-envelope check, not a speed gate.** It fires — at
any speed, including below 15 — if the requested ACC engine torque exceeds the L2-permitted torque for
the current ACC state, debounced ~12 cycles. It does **not** fire merely because speed is under 15 km/h.

Separately, `ac_min_cru_plausibility_monitor` (`0x800c553c`) faults when the integrated accel setpoint
leaves **[−3.0, +2.0] m/s²** (cals `0x80043514`/`0x80043512`) — a magnitude window, also **speed-independent**,
and **DTC-only** (functionally isolated; does not deactivate ACC or cut torque).

**For openpilot:** commanding acceleration below 15 km/h does not itself trip an L2 error. What the L2
layer constrains is torque magnitude vs the permitted envelope for the ACC state (deactivates on
violation) and the accel setpoint staying within ~[−3.0, +2.0] m/s² (DTC only). Keep the request inside
those and the L2 monitor is quiet at any speed.
