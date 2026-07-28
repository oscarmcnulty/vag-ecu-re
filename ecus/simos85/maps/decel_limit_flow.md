# ACC deceleration limit (−3.0 m/s²) — engine-ECU RE

The engine ECU caps ACC deceleration at **−3.0 m/s²**: when the ACC decel demand reaches −3.0, the
engine clamps its outgoing `TSK_Verzoeg_Anf` (TSK_02 / CAN 0x10C) at exactly −3.000 **and** latches
an ACC fault — `ACC_Status_ACC → 6` and `TSK_04` (0x10E) `TSK_Status_GRA_ACC_02 = 3`
("Fehler, GRA/ACC nicht möglich"), which holds until a key cycle. Engine-side, not ESP
(`ESP_Konsistenz_TSK = 0`, `ECD_Fehler = 0` throughout). Two distinct mechanisms are involved: a
functional **saturation clamp** and a separate **L2 plausibility monitor** (the fault).

## On-car ground truth (comma rlogs)
Verified across five drive routes on the subject vehicle:
- **Fault occurs at a −3.000 sent command** — `ACC_Sollbeschleunigung` raw 844 (0.005 m/s²/bit),
  `TSK_Verzoeg_Anf` raw 41 (0.024, off −3.984); openpilot's clamp means it never sends below −3.0.
- **~100 ms debounce** — the demand holds at −3.0 for ~5 cycles before the latch fires.
- **Fixed ceiling, NOT speed-interpolated** — the five faults span **51–116 km/h and all trip at −3.0**
  (`00000143` faulted at −3.0 at 116 km/h; a speed curve would have capped near −1.25 there).
- **Causal chain** (route 00000178, t≈2456 s): `TSK_Verzoeg_Anf` reaches −3.000 → same cycle
  `TSK_Status_GRA_ACC_02` 1→3 → next cycle `ACC_Status→6`, command zeroed. No driver brake /
  ESP inconsistency / CAN error at the trip; driver `MO_BLS` only appears ~400 ms later.
- **Practical floor: `−2.95` is the confirmed-safe value.** The monitor granularity is COARSE
  (~0.064 m/s², see §2) — NOT 0.005 — so `−2.96…−2.99` are NOT reliably safer than `−2.95` (they can
  land on the same or the faulting byte-step). Do not hug the wall; if you want more authority than
  −2.95, raise the cal (§ levers), don't shave the software clamp.

## 1. Functional saturation clamp — `8013c5d4` (`acc_brake_request_formation`)
`C_AC_SP_LIM_NEG` decel-limit curve:
```c
// 8013c5d4:209-224
input = Ramd0007ce8;                                          // filtered vehicle-speed class
if (DAT_d000a757 == 0) { vals=0xa005b71c; axis=0xa005a4c4; }  // functional variant
else                   { vals=0xa005b728; axis=0xa005a4f4; }  // alternate variant
limit = lookup_kennlinie_800a2cd0(vals, axis, input);         // -> −3.0 (raw 0x7237), cells flat
Ramd0007c8e = min_value_selector(Ramd0007cc6, limit, ...);    // saturate the brake request (:223)
// a second saturation at :418 (min_u16_800a4bbc against the same limit) -> Ramd0007c9a
```
- **Curve @ file `0x5b71c` (values) / `0x5a4c4` (axis)**; alternate `0x5b728`/`0x5a4f4`. Cluster of
  flat −3.0 cells `0x5b71c–0x5b730` (see `acc_flow.md`).
- **Encoding: offset-binary u16 LE**, phys = (X − 32768) × 0.00085; all cells = `0x7237` = −3.000;
  packer floor `0x6db1` = −3.984 (= `TSK_Verzoeg_Anf` min).
- This is a **saturation clamp** (why `TSK_Verzoeg_Anf` hard-caps at exactly −3.0). Lowering the cells
  (`0x7237` → lower raw) **relaxes** the cap. It does NOT itself fault.

## 2. L2 plausibility monitor (the fault) — `FUN_800c553c`  [AC_DCRU_PLAUS]
```c
// 800c553c:55-72  (setpoint sRamc0001732 is a rate-limited/filtered ACC decel setpoint)
iVar13 = abs_and_mask_800a5640(..., sRamc0001732);
if ( (cRam80043510*0x40 <= iVar13)            // rate limit exceeded
   || (sRamc0001732 < sRam80043514)           // setpoint < −3000  (STRICT '<')
   || (sRam80043512 < sRamc0001732) )         // setpoint > +2000  (> +2.0, STRICT)
     goto FAIL;                               // d000154b := 0x8004368d (reload debounce)
else d000154b = decrement(d000154b);          // plausible -> count down
d0001551 = (d000154b != 0);                   // debounced plausibility-fault flag
```
- Cals: **`0x80043514 = −3000` (−3.0)**, `0x80043512 = +2000` (+2.0), rate `0x80043510` — **scale 0.001
  m/s²/bit** (distinct from the clamp's offset-binary curve). Fault window is the OPEN interval
  `(−3.0, +2.0)`: plausible only if `−3.0 < setpoint < +2.0`.
- Per `fr_alignment.md` ③ (UPDATE 52) this is the latching status-3 path (FR `AC_MIN_CRU`/`AC_DCRU_PLAUS`);
  the debounced flag `d0001551` feeds the ACC status.
- **Editable −3.0 here: `0x80043514`** (raise magnitude for more authority) — recompute cal checksum.

### Reconciled: strict `<` on a BYTE-QUANTIZED, filtered, derived setpoint
`FUN_800c553c`'s −3.0 side is strict `<` (exactly −3000 would NOT trip it) — yet on-car the fault
fires at a −3.000 command. Resolved by the derivation of `sRamc0001732`:
- `sRamc0001732` = first-order filter (`FUN_800a3594`) toward target **`d000b4fa × 0x40`**, i.e.
  `d000b4fa` (signed byte) at **64 × 0.001 = 0.064 m/s²/LSB**.
- `d000b4fa` is written by `800ca1e8` from a **ring-buffer rate** (window sums of `d0006abc`,
  `d0006ad4 ← d0006ad8×5`). Traced to the source: `d0006ad8 ← d0006f80` (Δ) `← d0006ea0` = **`GPTA0_GTTIM0`
  hardware timer captures** (`800ab024:79`). So `d000b4fa` is the **MEASURED / ACHIEVED longitudinal
  acceleration**, derived independently from motion-sensor pulse timing (an ASIL-redundant path that does
  NOT trust the functional CAN value) — it is NOT a copy of the commanded `ACC_Sollbeschleunigung`.
- Byte quantization then explains both observations: `−3.0` → `round(−3000/64)=−47` → `−3008 < −3000`
  → **fault**; `−2.95` → `round(−2950/64)=−46` → `−2944 > −3000` → **plausible/safe**.

**Consequences:**
1. **Granularity is ~0.064 m/s², not 0.005.** `−2.96…−2.99` map onto byte −46/−47 like −3.0/−2.95 do, so
   they are NOT reliably safer than −2.95; the strict-vs-inclusive question is moot at fine resolution.
2. **The monitor gates on ACHIEVED decel, not commanded** — so road grade / load / brake response matter:
   downhill the achieved decel overshoots the command (a command *below* −3.0 can still trip it); uphill
   it may not. The boundary is not predictable from the command alone. `−2.95` is headroom for
   achieved-vs-commanded divergence + derivative noise, not just quantization. Do not hug the wall.

Remaining detail (minor): which motion sensor feeds the GPTA capture (wheel-speed vs engine/drivetrain),
and the exact command→byte rounding. Both need an on-car sweep or XCP-log of `d000b4fa` to pin — but the
commanded-vs-achieved question itself is RESOLVED (achieved, via GPTA timer capture).

## openpilot levers
1. **Software clamp (no reflash):** use the confirmed-safe `−2.95`. Because the monitor quantizes at
   ~0.064 m/s² (§2), shaving to −2.96…−2.99 buys little and may still fault — don't hug the wall.
2. **Cal edit (reflash):** relax the clamp cells at `0x5b71c` (offset-binary; e.g. `0x6FEA` ≈ −3.5) AND
   raise the monitor limit `0x80043514` (−3000 → e.g. −3500) — both, or the monitor still trips at −3.0.
   Recompute the cal-block checksum (`core/checksum`) before reflash; validate on-car.

Scripts: `analyze_decel_fault.py` (repo root); rlog CAN extract/decode in the session scratchpad.
