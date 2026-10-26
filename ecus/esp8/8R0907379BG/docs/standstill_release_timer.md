# The ~5.8 s standstill brake-release timer — resolved (openpilot EPB_01-decel inject)

ESP8 8R0907379BG (B8 Q5, Bosch, ARM BE32). Resolves the long-open question of **where the ~5.8 s
release that ends an openpilot-injected standstill hold lives, what it is, and whether it can be
defeated without a reflash.** Companion / corrected docs: `autohold_and_standstill_handoff.md`,
`verf_guard_and_dtc.md`, `epb_dynamic_braking.md`, `decel_paths.md`.

**Method: firmware-only (no bench/on-car tests were run).** The timer is characterised from (a) the
ECU's own CAN outputs in existing openpilot rlogs — ground-truth ESP behaviour, not a model — cross-
checked against `opendbc/dbc/vw_mlb.dbc`, and (b) static firmware RE of the reachable actuation path.

---

## TL;DR

- **(A) The timer is in the ABS/ESP itself** — NOT the EPB module, NOT an ACC interlock. Proof: the
  ESP drops its **own** `ESP_Verz_EPB_aktiv` + `ESP_Status_Bremsdruck` (and releases its own hydraulic
  pressure) **while the injected `EPB_Verzoeg_Anf` request is held perfectly constant with a valid,
  advancing rolling counter.** Nothing external changed at release. *This overturns the prior docs'
  "No ~5.8 s timer in the ABS … likely EPB-module / ACC-interlock" claim.*
- **(B) It is a standstill-anchored hold-duration limiter.** It counts from the ABS's **own wheel-speed
  standstill** (`ESP_01` speed = 0), **not** from request onset, and fires at **5.72–5.76 s** (the
  "~5.8 s"). At expiry the ESP emits a single-frame `ESP_Anforderung_EPB = 1` handoff request
  (~0.19 s before release), then drops `ESP_Verz_EPB_aktiv → 0` and `ESP_Status_Bremsdruck → 0`
  (hydraulic pressure released) → the car creeps. Because the ESP saw `EPB_Status = 0` /
  `EPB_Spannkraft = 0` the whole time (the panda spoofs EPB_01), this is a **fixed duration limiter
  with a courtesy EPB-clamp request at expiry**, not a wait-for-confirmation loop.
- **(C) Defeat without reflash:**
  - **(i) Jitter / varying the value every cycle — DOES NOT WORK (verified, falsified).** The injected
    decel varied (−0.53…−0.62 m/s²) and the E2E counter advanced on 100 % of frames, yet release still
    occurred at a **fixed** ~5.75 s after standstill. The timer is **not** staleness/freshness-based.
  - **(ii) Momentary drop-to-0 then re-assert — UNRESOLVED (see below).** Not empirically testable
    (the inject never dipped during a hold) and the counter's reset guard is behind the COM/dispatch
    wall. Best-supported reasoning below; **not** firmware-proven.
  - **No injection pattern is proven to hold a true standstill indefinitely.** The deterministic,
    architecturally-correct indefinite hold remains the **EPB static clamp handoff** (achieve/report a
    real `EPB_Status = clamped`), consistent with `autohold_and_standstill_handoff.md`.

---

## Empirical proof (rlogs, route `00000354--734f31b6f2`, segs 1–3)

Low-speed test loop; openpilot longitudinal engaged; secondary panda `SAFETY_VW_EPB_RELAY` rewrites
`EPB_01` (0x104) on every bus to inject `EPB_Verzoeg_Anf ≈ −0.53 m/s²` + `EPB_Freig_Verzoeg_Anf = 1`
(the EPB dynamic-brake / "Notbremsfunktion" request; see `epb_dynamic_braking.md`). The ESP executes
it as real hydraulic service-brake pressure below 15 km/h and holds at standstill — then releases.

**Signal decode (DBC-verified, `vw_mlb.dbc` BO_262 ESP_05, BO_260 EPB_01):**
- `ESP_05` (0x106) byte7: `ESP_Autohold_aktiv`=bit56, `ESP_Verz_EPB_aktiv`=bit58 (VzEPB),
  `ECD_Bremslicht`=bit59, `ESP_Verzoeg_EPB_verf`=bit60 (verf), `ESP_Status_Bremsdruck`=bit61 (StBrkP),
  `ESP_Anforderung_EPB`=bits62-63 (AnfEPB).
- `EPB_01` (0x104): `EPB_Verzoeg_Anf`=byte2 (×0.048, −7.968 m/s²), `EPB_Freig_Verzoeg_Anf`=bit15
  (byte1 bit7), E2E rolling counter = byte1 low nibble, checksum = byte0.
- `ESP_01` (0x100) bytes[4:5] LE ×0.01 km/h = vehicle speed (the ABS's own reference).

**Two clean standstill-hold → release events (anchors in seconds, ABS wheel-speed standstill):**

| event | req active *before* standstill | **standstill → release** | AnfEPB=1 pulse lead | decel during hold | E2E cnt advancing |
|---|---|---|---|---|---|
| A (seg1 ~62 s) | 4.40 s | **5.760 s** | 0.200 s | [−0.62, −0.53] | 100 % |
| B (seg1 ~105 s) | 12.64 s | **5.721 s** | 0.181 s | steady ≈ −0.53…−0.62 | 100 % |

**Why this proves (A), (B), (C-i):**
- **Standstill-anchored, not request-anchored:** request-active-before-standstill differs 3× (4.40 vs
  12.64 s), yet standstill→release is invariant (5.760 vs 5.721 s; 0.039 s = 2 CAN frames of jitter).
  ⇒ the counter is **held at 0 during the moving approach** and only runs once `ESP_01` speed = 0.
- **Internal to the ESP:** across the hold, `EPB_Freig_Verzoeg_Anf=1`, `EPB_Verzoeg_Anf` asserted,
  E2E counter advancing every frame, `EPB_Status=0`/`Spannkraft=0` — **nothing on the bus changed at
  release.** The ESP alone decided to drop VzEPB + StBrkP and vent pressure.
- **Release sequence:** `AnfEPB 0→1` (1 frame, ~20 ms) → ~0.19 s later `VzEPB 1→0` → ~0.26 s later
  `StBrkP 1→0` → car creeps (`ESP_01` speed rises within ~0.3 s). `verf` stays 1 throughout (healthy).
- **Not staleness:** `decel_mode_state_set` (0x8c1e8) is a ~0.4 s decel-staleness watchdog
  (counter `PTR_DAT_0008c360[0xe]`, thr 0x27 ≈ 39 ticks). Our inject never goes stale (counter
  advances 100 %), and the decel value jitters, yet the 5.75 s is unchanged ⇒ a **separate
  hold-duration limiter**, not a staleness/freshness timer. (So `jitter` is falsified as a defeat.)

Reproduce: `scratchpad` scripts `rl_anchors.py` / `rl_dur.py` / `rl_final.py` over
`/home/om/routes/00000354--734f31b6f2--{1,2,3}/rlog.zst` (parser:
`/home/om/openpilot-emac-rebase/.venv` LogReader).

---

## Tick rate & count estimate

The decel task ticks **~10 ms** (from `decel_mode_state_set` 0x8c1e8: >39 ticks ≈ 0.4 s ⇒ ~10.3 ms).
At 10 ms, **5.75 s ≈ 575 counts ≈ 0x240** (a 16-bit counter — too large for a byte). A 5 ms inner-loop
alternative gives ~1150 ≈ 0x480. The threshold is **not byte-pinned** (see wall below); likely a
cal-resident constant (as `decel_mode_state_set` loads its own threshold through a pointer, default
0x310). Plain code-literal scans for 0x240/0x480/0x244/0x488 are swamped by decel-magnitude and
struct-offset homonyms, so the literal alone is not evidence.

---

## Firmware trace & the static wall (reconfirmed, not a narrow-search artifact)

The release ACTION is reachable: `esc_valve_apply_wheel` (0x8fcb8, the hold-valve bank →
MMIO 0xfff7d400/d500/d600) is driven only by `esc_actuation_task_step` (0xa18ec), indirectly
dispatched; per-wheel apply/hold/release valve params are selected by `FUN_00042d04` on a mode byte
`*DAT_0004320c ∈ {0,1,2,4,5}`. But the **EPB-decel / standstill-hold state machine that owns the
counter, sets `ESP_Verz_EPB_aktiv`, and raises `ESP_Anforderung_EPB`** is behind the runtime COM +
task-dispatch wall. Independently reconfirmed four ways here:

1. **COM source bytes `0x405e68–0x405e96`** (incl. VzEPB/verf/AnfEPB) are written via a **base +
   computed offset** (router `esp05_status_route_a6c8` 0xa6c8 from the runtime object table), so Ghidra
   attributes **no WRITE xref** to any specific byte — only packer READs (`esp_msg_pack_525c` 0x525c,
   `esp_msg_pack_3458` 0x3458) + literal-pool DATA refs. (Verified by a full Ghidra `getReferencesTo`
   sweep of the whole region.)
2. **The periodic task-step functions** (0xa18ec, 0xa224c, 0xa1950, …) appear in **no flash pointer
   table** (searched the whole image for their BE32 addresses and for 0x9c000–0xa3000 pointer
   clusters) ⇒ the scheduler is RAM/SBOOT-built, like the EPB module's was before
   `swc_dispatch_resolved.md`.
3. **The COM object table / `.data` is SBOOT-initialised and absent** from this ASW image
   (`com_routing_decoded.md`), so config-init emulation can't bootstrap (3× confirmed) and
   `EPB_Verzoeg_Anf`'s runtime buffer (handle 0x25b) has no flash literal to xref.
4. The flash COM signal→buffer tables (0xb038c, 53 recs; 0xb06f0 PDU, 34 recs — fully parsed here)
   contain **no EPB_01 cluster** (EPB signals are in the runtime object-table RX set).

**Exhaustive 16-bit-counter scan (the "redo it properly" pass, not the old narrow 4-constant scan).**
Enumerated **every** function in the 4295-fn corpus with a true 16-bit counter increment
(`*(ushort*)X = *(ushort*)X + 1`) — **69 functions** — and classified each; **none is a standstill→
release timer**:
- COM E2E/confirm counters-to-3 (`0x63cc0/0x63e38/0x63f9a`; the `0x28c`=652 there is a COM group-ID
  **argument** to `com_signal_route_copy`, not a tick threshold);
- COM signal-age saturating counters to a **cal** limit (`0x5497c` < `DAT_00054ef4`, `0x987a4` <
  `_DAT_00098860`) that only pack a status byte (COM TX) — no pressure/VzEPB action;
- DTC maturation debouncer (`0x9b5ac` → 0x3e9=1001, fires DTC-event reports — not a brake release);
- sensor-statistics windows (`0xf2750` → 513-sample; `0x101d4c` → 200-sample avg; its `0x235` is a
  **struct offset**, not the counter);
- struct offsets misread as thresholds (`0x8f526/57e/878`: `0x474`/`0x478` = `iVar+offset`, confirmed).
The only 16-bit/byte counters touching speed/valve/pressure are `veh_ref_speed_calc` (0xa904),
`anb_decel_request_build` (0x4bf3c), and `decel_mode_state_set` (0x8c1e8, the 0.4 s staleness
watchdog) — none a 5.75 s standstill hold. The only direct writer of the ESP_05 EPB source block
(`FUN_001007b8`, SEG2) is the COM TX composer (its own counter wraps at 0xf0=240, a COM update
window) and it reads upstream state, it does not compute the hold.

⇒ The exact counter RAM address, its reset guard, and the threshold constant are **not recoverable by
static analysis of this ASW-only image**, and emulation can't reach them (SBOOT-dependent). This is a
genuine, now multiply-reconfirmed limit — **not** the earlier narrow search (the full 69-counter sweep
above is what makes this an exhaustive negative). What static work *does* establish is the reachable
release actuator and that the owner is the ESP's EPB-Verzoeg/standstill-hold SWC (consistent with the
base-ESP "active-pressure" controller of `epb_output_trace.md`).

---

## (C) Defeat analysis & recommendation

- **(i) Jitter (vary decel every cycle): FALSIFIED.** Verified above — advancing counter + jittering
  value still released at a fixed ~5.75 s. Do not pursue.
- **(ii) Temp-0-then-reassert: UNRESOLVED, best-reasoned verdict.** The counter is proven
  standstill-gated (held at 0 while moving). Whether its in-standstill increment guard is *standstill
  alone* or *standstill AND hold-active (VzEPB)* decides (ii):
  - If gated by *standstill alone* → dropping decel to 0 does **not** reset it (and vents the brakes
    meanwhile) → (ii) fails.
  - If gated by *standstill AND hold-active* (the natural "duration of THIS hold" architecture, and
    the reason the single AnfEPB pulse + VzEPB drop look like a hold teardown) → withdrawing the
    request ends the hold and a re-assert starts a **new** ~5.75 s hold → (ii) resets the timer, **but
    each cycle briefly releases the brake** (VzEPB=0, pressure=0) so the car creeps a little every
    ~5.5 s. Not a clean indefinite hold.
  Neither branch is firmware-provable from this image, and the inject never dipped mid-hold in the
  rlogs, so **(ii) cannot be declared verified.** The architecture leans toward the second branch:
  **every** reachable hold/debounce counter in this image (the 69-counter sweep) resets when its
  gating condition drops — e.g. `decel_mode_state_set` (0x8c1e8) clears its stale-counter on
  request re-validation, `0x5497c` clears its age-counter when the enable bit clears. By that
  pattern the standstill limiter most likely increments while (standstill AND EPB-decel-request-
  active) and resets when either drops ⇒ a temp-0 would restart the window, **but** clearing the
  request also drops VzEPB and vents the brake, so the car creeps during the 0-phase and the window
  merely restarts on re-assert — periodic reset, periodic creep, **no seamless indefinite hold.**
  Treat this as a strong structural inference to confirm on-car when that path reopens, not as proven.
- **Deterministic indefinite hold (recommended):** hand the standstill off to the **EPB static clamp**
  — i.e. drive the real EPB to clamp and/or present `EPB_Status = clamped` + rising `EPB_Spannkraft`
  to the ESP so its handoff completes (the AnfEPB pulse at expiry is the ESP *asking* for exactly
  this). This is the same conclusion as `autohold_and_standstill_handoff.md` §recipe and the EPB-clamp
  work in `ecus/epb`. The 5.8 s limiter is the ESP refusing to hold hydraulic pressure for an external
  requester indefinitely; the EPB clamp is the intended holder.

## Corrections to prior docs (applied)
- `autohold_and_standstill_handoff.md` and `verf_guard_and_dtc.md`: "No ~5.8 s timer in the ABS …
  EPB-module / ACC-interlock" is **overturned** — the limiter is an ABS/ESP standstill hold-duration
  timer on the EPB-Verzoeg path (proof above).
