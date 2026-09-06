# The −3.0 m/s² ACC deceleration limit

The engine ECU caps ACC deceleration at **−3.0 m/s²**. When the ACC decel demand reaches −3.0 the engine
clamps its outgoing `TSK_Verzoeg_Anf` (TSK_02 / CAN 0x10C) at exactly −3.000 **and** latches an ACC
fault — `ACC_Status_ACC → 6` and `TSK_04` (0x10E) `TSK_Status_GRA_ACC_02 = 3`
("Fehler, GRA/ACC nicht möglich") — which holds until a key cycle. This is engine-side, not ESP
(`ESP_Konsistenz_TSK = 0`, `ECD_Fehler = 0` throughout).

**Three distinct mechanisms**, all in-image and statically decompiled:

| # | mechanism | what it does |
|---|---|---|
| 1 | functional **saturation clamp** in `8013c5d4` | delivers exactly −3.000, speed-independently |
| 2 | **L2 plausibility monitor** `800c553c` (`AC_DCRU_PLAUS`) | the latching fault |
| 3 | separate **engine-torque** decel limit in `801e6df0` | caps engine braking at −0.82 m/s² |

Encoding matters here more than anywhere else in the pack: the internal setpoint domain is
**u16 offset-binary, 850e-6 m/s²/LSB** (`phys = (raw − 0x8000) · 850e-6`), so −3.0 = `0x7237`, not a
signed −3529. The L2 monitor uses a completely different scale, **0.001 m/s²** signed, so −3.0 = −3000
there. Addresses are load base `0x80000000`; file offset = `addr & 0x1FFFFFFF`.

## On-car ground truth (comma rlogs, five drive routes)

- **The fault occurs at a −3.000 sent command** — `ACC_Sollbeschleunigung` raw 844 (0.005 m/s²/bit),
  `TSK_Verzoeg_Anf` raw 41 (0.024, offset −3.984).
- **~100 ms debounce** — the demand holds at −3.0 for ~5 cycles before the latch fires.
- **Fixed ceiling, not speed-interpolated** — the five faults span **51–116 km/h and all trip at −3.0**
  (route `00000143` faulted at −3.0 at 116 km/h; a speed-dependent curve would have capped near −1.25
  there). This is what the flat Kennlinie predicts.
- **Causal chain** (route `00000178`, t ≈ 2456 s): `TSK_Verzoeg_Anf` reaches −3.000 → same cycle
  `TSK_Status_GRA_ACC_02` 1→3 → next cycle `ACC_Status → 6`, command zeroed. No driver brake, no ESP
  inconsistency, no CAN error at the trip; the driver's `MO_BLS` only appears ~400 ms later.
- **Confirmed-safe software floor: −2.95.** The monitor's granularity is coarse (~0.064 m/s², §2), so
  −2.96…−2.99 are **not** reliably safer than −2.95 — they can land on the same faulting byte step. Do
  not hug the wall; for more authority raise the cal (§4), don't shave the software clamp.

## 1. Functional saturation clamp — `8013c5d4` (`acc_brake_request_formation`)

```c
// 8013c5d4:221-233   FR family C_AC_SP_LIM_NEG / IP_AC_SP_MIN_*
input = Ramd0007ce8;                                          // filtered vehicle-speed class
if (DAT_d000a757 == 0) { vals=0xa005b71c; axis=0xa005a4c4; }  // GRA   (LV_DCC_ENA = 0)
else                   { vals=0xa005b728; axis=0xa005a4f4; }  // Basic-ACC
limit = lookup_kennlinie_800a2cd0(vals, axis, input);         // -> 0x7237 = -3.000
uRamc00010b2 = limit;                                         // :231
sRamc00010e4 = min_value_selector(...);                        // :233 first saturation
// second saturation at :429-430:
Ramd0007c9a = max_u16_MISNAMED_min(uRamc00010fc, uRamc00010b2);  // -> max(request, 0x7237)
```

- **⚠ `min_u16_800a4bbc` is a Ghidra misnomer — its body returns the MAX**
  (`p1·(p2<p1) + p2·(p2>=p1)`; verified numerically: `800a4bbc(0x6f00, 0x7237) = 0x7237`, i.e. a harder
  request of −3.6 is clamped **up** to −3.0). So `:429-430` reads `Ramd0007c9a = max(request, 0x7237)` =
  truncate braking to −3.0, the textbook clamp, matching the on-car "openpilot < −3.0 → truncated to
  −3.0". The plain `min_u16` at `0x800a4c..` **is** a genuine min — do not confuse the two. This name is
  recorded in `symbols_merged.csv` as `max_u16_MISNAMED_min`.
- **The curves are flat**, which is why the cap is −3.000 speed-independently (CONFIRMED, firmware read):

| curve | file offset | axis | cells |
|---|---|---|---|
| GRA — `IP_AC_SP_MIN_CRU` | `0x5b71c` | `0x5a4c4` (N=6) | 6 × `0x7237` (−3.000) |
| Basic-ACC — `IP_AC_SP_MIN_DCC` | `0x5b728` | `0x5a4f4` (N=6) | 5 × `0x7237` then `0x8000` (0) in the last cell |
| Follow-to-stop — `IP_AC_SP_MIN_DCC_FOL_2_STOP` | `0x5b734` | — | all `0x8000` (empty — F2S not compiled in) |

  The two live curves overlap into one contiguous **11-cell `0x7237` cluster at `0x5b71c–0x5b730`**, so a
  single edit region covers both coding variants. Which one is operative is set by long-coding cell 27
  (`STATE_DCC_TYP` → `d000a757` = `LV_DCC_ENA`).
- The packer `80137a00` then applies a **hard clamp `[0x6db1 = −3.984, 0x89b6 = +2.112]`** (the byte
  saturates to 0x00 / 0xFE) — the CAN signal's outer range, below the −3.0 curve.
- **State dependence:** the `c9a → cb8` passthrough is CRUC-state dependent. Handlers `8013e3f8`,
  `8013e47c` and `8013e13c` pass it through, but `8013e674` **replaces** it
  (`Ramd0007cae = −1 − uRamc0001134`, or a cal `uRam80043062`), and `8013ef46:951-963` only forwards
  `cae → cb8` when the decel enable `d000a58c != 0` (else `cb8 = 0x8000` = 0). So the −3.0 cap describes
  the normal active-brake behaviour, not literally every state. See `acc_flow.md` §4.

## 2. L2 plausibility monitor — `800c553c` (`ac_min_cru_plausibility_monitor`, FR `AC_DCRU_PLAUS`)

```c
// 800c553c:55-72
iVar13 = abs_and_mask_800a5640(..., sRamc0001732);
if ( (cRam80043510*0x40 <= iVar13)            // rate limit exceeded
   || (sRamc0001732 < sRam80043514)           // setpoint < -3000   (STRICT '<')
   || (sRam80043512 < sRamc0001732) )         // setpoint > +2000   (STRICT)
     goto FAIL;                               // d000154b := 0x8004368d (reload debounce)
else d000154b = decrement(d000154b);
d0001551 = (d000154b != 0);                   // debounced plausibility-fault flag
```

- Cals (CONFIRMED, firmware read): **`0x80043514 = −3000`** (−3.0), `0x80043512 = +2000` (+2.0),
  rate `0x80043510 = 32`; **scale 0.001 m/s²**. The plausible window is the *open* interval
  `(−3.0, +2.0)`.
- **The monitor gates on ACHIEVED decel, not commanded.** `sRamc0001732` is a first-order filter
  (`FUN_800a3594`) toward `d000b4fa × 0x40`, i.e. `d000b4fa` is a signed byte at 64 × 0.001 =
  **0.064 m/s²/LSB**. `800ca1e8` writes it from a ring-buffer rate (window sums of `d0006abc`,
  `d0006ad4 ← d0006ad8×5`), traced to source: `d0006ad8 ← d0006f80` (Δ) `← d0006ea0` =
  **`GPTA0_GTTIM0` hardware-timer captures** (`800ab024:79`). So it is the measured longitudinal
  acceleration, derived from motion-sensor pulse timing on an ASIL-redundant path that does **not**
  trust the CAN value.
- **That reconciles the strict `<` with the on-car fault at exactly −3.000.** Byte quantization:
  −3.0 → `round(−3000/64) = −47` → −3008 < −3000 → **fault**; −2.95 → `round(−2950/64) = −46` → −2944 >
  −3000 → **plausible**.
- Consequences: granularity is ~0.064 m/s², not 0.005, so −2.96…−2.99 buy nothing over −2.95; and
  because the input is *achieved* decel, road grade and load matter — downhill the achieved decel
  overshoots the command, so a command below −3.0 can still trip it, uphill it may not. The boundary is
  not predictable from the command alone.
- **Fault routing:** the debounced flags `d0001551`/`d000154b`/`d0001550` are read by nothing except
  this function and the resets `80172658`/`801b498c`, so `800c553c` is **isolated — DTC-only**: it does
  not feed the ACC status or the status-3 latch. The latching fault at −3.0 is a **separate** mechanism
  — the EGAS-L2 torque monitor (§6). No status-3 route reads the decel value.
- **GAP (minor):** which motion sensor feeds the GPTA capture (wheel speed versus engine/drivetrain), and
  the exact command→byte rounding. Both need an on-car sweep or an XCP log of `d000b4fa`. The
  commanded-versus-achieved question itself is resolved: achieved.

## 3. Engine-torque ACC decel — `801e6df0` (separate and weaker)

The engine limits its own ACC engine-*braking* decel to **−0.82 m/s²**: cal struct `0x80079940`, floor
`[+0x42] = −164` (**file `0x79982`**, s16 at 0.005 m/s²), ceiling `[+0x40] = +328` = +1.64 (CONFIRMED,
firmware read). Harder braking is delegated to the ESP over the −3.0 brake channel above. Making
`0x80079982` more negative gives the engine more braking authority of its own.

## 4. Editing the limit

The functional clamp and the L2 monitor are an EGAS L1/L2 pair: **move both or the monitor still faults
at −3.0.**

| target | address | current | direction |
|---|---|---|---|
| flat decel-limit Kennlinie cells | file `0x5b71c`–`0x5b730` (11 × u16 LE) | `0x7237` = −3.000 | **lower** raw = relax the cap (e.g. `0x6FEA` ≈ −3.5, `0x6db1` = −3.984) |
| L2 monitor limit | `0x80043514` (s16, 0.001) | −3000 | raise magnitude to match (e.g. −3500) |
| packer hard floor | `0x6db1` literal in `80137a00` | −3.984 | only needed to go below −3.984 |

`raw = 0x8000 + phys / 850e-6`. For a GRA-coded car the `0x5b71c` group is operative, for an ACC-coded
car the `0x5b728` group; editing the whole contiguous cluster covers both. **Floor achievable without a
code edit = −3.984** (the packer's literal).

Without a reflash, the practical lever is the sending side: clamp commands at the confirmed-safe −2.95.

All cal edits require a cal-block checksum recompute (`core/checksum`) before reflash; validate on-car.
The full lever table across all topics is in `edit_targets.md`.

## 5. FR ↔ binary alignment for this mechanism

| FR label | meaning | type / res | binary anchor |
|---|---|---|---|
| functional decel clamp (`C_AC_SP_NEG_LIM_CRU` family) | the delivered −3.0 saturation | u16, 850e-6 offset-binary | flat Kennlinie file `0x5b71c` = `0x7237` (GRA `0xa005b71c` / Basic-ACC `0xa005b728`); read at `8013c5d4:221-233` |
| `C_AC_SP_LIM_NEG_CRU` | a negative *offset* added to the computed min limit | u16, 850e-6 | cal = **0** here — an offset, not the −3.0 value |
| `AC_DCRU_PLAUS` / `AC_MIN_CRU` | L2 plausibility: fault if setpoint ∉ (−3.0, +2.0) | 0.001 m/s² | `800c553c`; cals `0x80043514`, `0x80043512`, `0x80043510` |
| `LV_ERR_AC_MIN_CRU` / status-3 | latching fault → `TSK_Status_GRA_ACC` = 3 | bool | `d8e0 → d744 → d8b4 → 801eca44` (`acc_flow.md` §6) |
| `C_T_ERR_AC_MIN_CRU_H/_L`, `C_T_ERR_AC_DCRU_PLAUS_H/_L` | fault debounce timers (0.02 s steps) | — | not pinned |

Scripts: `analyze_decel_fault.py` (repo root); rlog CAN extraction/decoding runs in a session scratchpad.

## 6. The latching fault: root cause and how to observe it

The latching ACC fault at −3.0 (`TSK_Status_GRA_ACC_01`/`_02` → 3, held until re-arm or key cycle) is the
**EGAS-L2 engine-torque monitor**, not a deceleration monitor. On-car (rlog `00000178--40`, t=54.61 s): the
status latches within a few cycles of the demand reaching −3.0, `ESP_05.ECD_nicht_verfuegbar = 0`
throughout (the ESP is granting decel), and no CAN input flips — the trigger is engine-internal.

**Route (code-traced):**
```
status 3 (0x10C b28d / 0x10E STATE_DCC)
  <- Route A bit3 = a59c!=0 || b298==3           (8013ef46:731 ; 8013e8aa:8013e926)
  <- a03b = a03c || a040 || d1856                (8009c0b4:837)  [the only engine-internal Route-A term]
  <- a040: permitted torque < requested engine torque, 12-cycle debounce (cal 0x8004566d)
  <- permitted forced to 0 when the EGAS-L2 permit timer runs down
  <- a02e (egas_l2_torque_permit_deauth) sets    (800996a8: a7bb || a02f || a9a5)
```
**It watches torque, not deceleration.** `8009c0b4` reads `acc_engine_torque_request` (`d0007ce0`), which
on the Q5 (`a5a8=0`) is `Ramd0007ccc` passthrough ← `Ramd0007caa` (the ACC engine-torque request from the
CRUC), *not* the decel command. So the −3.0 decel clamp never bounds it; the −3.0 demand and the fault
coincide only because both are driven by the same maximum-longitudinal-authority state. The fault is a
torque-**authorization withdrawal** (a plausibility monitor asserts → `a02e` pulls the permit → any live
engine-torque request then reads permitted(0) < requested → `a040`), not a value-over-limit.

**Emulation** (`ghidra_scripts/EmuL2Torque.java`): armed on `ACC_Status_ACC=3`, `8009c0b4` does not
false-trip under authorized torque; with the permit withdrawn it latches `a040`→`a03b` after exactly the
12-cycle debounce.

**Observing "available (permit) vs commanded" torque.** Both are RAM-only. The Simos 8.5 has **no live-RAM
read** (no UDS `$23`, no CCP/XCP slave — `obd_read_feasibility.md`) and broadcasts neither, so the options
are: (1) **bench + JTAG/OCDS** on the TC1796 — read `d0007ce0` (command), `d0007ccc`/`d0007caa` (source),
the permit timer `d0001840`, debounce `d000ae35`, `d000a02e`+sources `d000a7bb`/`a02f`/`a9a5`, and
`d000a040`/`a03c`/`a03b`; (2) a **custom measurement reflash** broadcasting those on a spare CAN id
(write path is RSA-signed, so hard); (3) **off-car emulation** of the torque path + monitor.

**Open:** which of `a7bb`/`a02f`/`a9a5` asserts during a −3.0 event, and confirmation the permit was
withdrawn while torque was requested — internal, needs a bench/RAM trace.
