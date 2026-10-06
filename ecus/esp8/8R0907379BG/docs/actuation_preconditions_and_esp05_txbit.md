# ACC_01 / ACC_10 / EPB_01 — exact decel preconditions + the ESP_05 ECD_nicht_verfuegbar TX-bit source

Follow-up to `verify_speed_gate_vs_ecd_tx.md`. Re-verified against the fresh `reproduce.sh`
corpus + independent capstone (register-tracking `decode/verify_speed_gate_xref.py`), with opendbc
`vw_mlb.dbc` (commaai/opendbc master) as external ground truth. Two parallel sub-traces fed this;
every load-bearing claim below was re-checked by hand against the raw image (and two sub-trace
claims were **corrected** — see §5).

## 1. The three messages reach three different executors

| msg | CAN | carries | internal path | executor | speed-gated? |
|---|---|---|---|---|---|
| **ACC_01** (comfort) | 0x109→comfort req | `ACC_Sollbeschleunigung` | type2 → `ecd_mode=2` | `ecd_decel_pressure_calc` (0x6de38) smooth ramp | **YES — 15 km/h** |
| **ACC_10** (ANB/AEB) | 0x117 | `ANB_Zielbrems_*` + `ANB_*_Freigabe` | type4 → `ecd_mode=4` | `ecd_emergency_pressure` (0x9c788) flat step | no (but see §3) |
| **EPB_01** | 0x104 | `EPB_Verzoeg_Anf` + `EPB_Freig_Verzoeg_Anf` | **separate base-ESC path, NOT ECD** | base ABS/ESC pressure (behind MMIO) | no `0x78` on any EPB path |

(ACC_01↔comfort is the functional mapping: the comfort/type2 request is the only 15 km/h-gated
one. The exact CAN-id→comfort-source COM edge is index-driven; type2=comfort is proven by its
producer `decel_src_comfort_calc` 0x88a88.)

## 2. ACC_01 (comfort / mode-2) — full gate chain (code-verified)
All must hold to produce pressure:
1. Request present: `decel_src_comfort` (0x403a40) ← `decel_src_comfort_calc` (0x88a88).
2. **Assemble** (`decel_req_assemble` 0x86798:31): comfort `status==0x10` AND `enable & 0x80` AND `value>0` → type=2.
3. **Arbitrate** (`decel_req_arbitrate` 0x94a70): MAX-decel wins; winner type → `ecd_mode` (0x405aba). Comfort must out-magnitude any concurrent type1/type4.
4. **State machine** (`ecd_state_machine` 0x633fc): `ecd_mode!=0`; runs `ecd_speed_gate()`; dispatches `ecd_decel_pressure_calc` only when `ecd_mode==2 && substate==2`.
5. **ECD armed** (`ecd_speed_gate` 0x844fc guards): `esp_ctrl_status`(0x403a04) bit12 set; request not negligible (gate clears availability if comfort decel `<5`); no fault (`ecd_gate_flags & 0x12`).
6. **Speed ≥ 15 km/h**: `flag_ecd_speed_avail`(0x403da9) bit6, from the two `cmp Rn,#0x78` (0.125 km/h/bit) + ~30-cycle debounce. Below 15, `ecd_decel_pressure_calc` **zeros** setpoints +8/+0xa/+0xc/+0x14. ← the floor.
7. Pressure = `ecd_pressure_curve` (0xaeb60) lookup on the requested decel.

## 3. ACC_10 (ANB / mode-4) — full gate chain + the real precondition
Executor is ungated (works to 0 km/h), but the **arm** is a brake-ASSIST gate: it needs the car to
be **already physically decelerating**. Chain (type-4 producer `anb_decel_request_build` 0x4bf3c:154):
```
arm iff:  status(0x407bf0) bit14 AND  (0x460 < *0x4066e0)  AND  bit6(freigabe)
          AND  *0x4055b4 > 0xc (quality)  AND  *0x4055e4 < 0x37 (freshness)
          AND  *0x405cac == 0x10 (master-enable)  AND  dwell-integrator(0x407bc4+0x28) >= 0x6ddd00
          AND  no fault latch (0x405abe∈{0,4}, 0x405473 bit7 clear, 0x407c29 bit7 clear)
then: type4 → preprocess(0x7f4ec, enable 0x40) → assemble(0x86798, status 0x405dcf==0x10 & enable 0x80 & val>0)
      → arbitrate (must be MAX) → ecd_mode=4 → ecd_emergency_pressure (flat, all 6 setpoints = request)
```
- **Arm magnitude `0x4066e0`** is written by wheel-dynamics `FUN_00090520` (weighted sum of 4
  per-wheel decels) **and** by `anb_decel_from_wheels` (0x7c1d4, `str` @0x7c3b0). 0x7c1d4 combines
  the external ACC_10 request `0x4054c4` **clamped to ±0x1ff (±511)** with wheel dynamics.
- **Decisive:** arm threshold is `0x461` (1121) but the external term is capped at **+511** — so a
  CAN command **cannot arm ANB on its own** from steady speed/standstill; real measured
  deceleration (dominant, wheel-derived) must supply the rest, and the dwell integrator (0x6ddd00)
  requires it to **persist**. ANB also releases the instant measured decel drops < 0x461, so it
  can't hold at standstill. (Scale ≈0.001 m/s²/bit ⇒ 0x461 ≈ 1.12 m/s²; medium-high confidence.)
- **freigabe** (`ANB_*_Freigabe` → `0x40553b` bit3 → status bit6) is a hard gate in steady state,
  with a ~1450-cycle (`0x5aa`) debounce grace window after it drops (why init-state emulation
  looked freigabe-independent). `AWV1_ECD_Anlauf`'s internal consumer is COM-indirect/unproven.
- Not speed-gated: `ecd_emergency_pressure` (0x9c788) reads no speed flag (whole-function + pool
  verified).

## 4. EPB_01 — reception byte-proven; execution behind the runtime wall
- **RX (byte-proven):** mailbox-config `0xaea38` (stride 0x18; the valid decode is `+0x10 = CAN_id<<18`,
  validated against 11 anchors). EPB_01 = **record 27 @0xaecc0**: HW reg `0xfff7e690`, handler
  `0x126bb` (Thumb), controller `0xfff7ea00`, DLC 8, arb `0x44100000`→`0x104`. Also in id-array
  `0xafae0` idx8.
- **Distinct RX pipeline (new proof):** the static per-message COM config `0xa9fc0` (196 msgs,
  handler `can_rx_indication` 0x8e3ec → fixed state_ram) that feeds ECD arbitration **does not
  contain the 0x100–0x116 cluster at all** — ACC_10 (0x117) is in it (state_ram 0x404588); EPB
  (0x104) is not. EPB is a runtime/bulk-RX message (mailbox trampoline 0x126bb → object-table
  buffer). So EPB structurally **cannot** join the type1/2/4/5 ECD arbitration.
- **Execution:** behind the boot-installed object-table/MMIO wall (`*0x4069b4=0x40a1a8`). The base
  ESC valve stage (`esc_valve_apply_wheel` 0x8fcb8 etc., MMIO 0xfff7d400/d500/d600, pump
  0xfff7f0a0) is the actuator, but EPB's request-injection point is upstream in the base-ESC
  pressure arbiter — not statically pinnable from the ASW image. No `cmp #0x78` on any EPB path
  (consistent with the owner's report that lever-hold brakes to a stop).
- Status feedback: ESP_05 `ESP_Verz_EPB_aktiv`(58)/`ESP_Verzoeg_EPB_verf`(60)/`ESP_Anforderung_EPB`(62),
  packed by the same generic composer (§6 wall).

## 5. ESP_05 `ECD_nicht_verfuegbar` — TX-bit source (settled, with residual)
- The CAN bit is assembled by the **generic COM composer** (`com_signal_compose` 0x6b00 ←
  `esp05_status_src` 0x405f68 ← config-indexed copy `0xa6c8`; packed via TX scheduler 0x86aa). This
  is not byte-literal traceable: sig-byte addresses (0x405e8x/9x) appear **nowhere as literals** in
  the config region, and a cold `com_signal_compose` emulation (RAM image applied, status struct
  seeded 0x00 vs 0xFF) produced **zero** sig-byte change — the ESP_05 branch needs full COM-scheduler
  state. **No TX/pack function reads `flag_ecd_speed_avail` or `flag_speed_status`.**
- **Source condition settled behaviorally:** on-car the bit flips at a clean **15.0–15.2 km/h with
  no 25 km/h hysteresis**. The only 15 km/h (`0x78`) thresholds in the image are `ecd_speed_gate`
  (clean + debounce, no hysteresis) and `veh_ref_speed_calc` (15/25 hysteresis). The clean fingerprint
  **uniquely matches `ecd_speed_gate`** — the same gate/constant as the comfort actuation floor.
- **Residual / mod caveat:** because no TX-path code literally reads the gate flag, a *separate*
  `0x78` compare in a (possibly Thumb) status routine can't be excluded. If the CAN status bit has
  its own compare, patching `ecd_speed_gate`'s two immediates fixes *actuation* but leaves the CAN
  "not available" bit asserting < 15 — and the ACC master may withhold the request. Verify on-car
  after patching; full byte-exact proof needs COM-scheduler emulation bring-up.

## 6. Corrections to prior repo state
- **CONFIRMED correct (do not change):** `anb_decel_from_wheels` (0x7c1d4) **does** write the arm
  magnitude `0x4066e0` (`str` @0x7c3b0) — so `ECD_path.md`'s "wheel-dominant, externally modulated"
  model stands. (A sub-trace proposed retracting this; that proposal is **wrong** — verified by
  disassembly: 0x7c1d4 writes both 0x4065e4 @0x7c2ec and 0x4066e0 @0x7c3b0.)
- **CORRECTED:** the CAN-mailbox-config decode scheme and the "EPB_01 → handle 0x25b @0xaea98/b0/c8".
  The valid record field is `+0x10 = id<<18`; under the old `{+0xd id,+0xf handle}` scheme every known
  anchor decodes to garbage, and 0xaea98/b0/c8 are actually diag IDs 0x6c0/0x6d0/0x6c7. EPB's real
  mailbox is **rec27 @0xaecc0 / 0xfff7e690 / handler 0x126bb**; **the 0x25b handle is an artifact and
  is retracted.** `symbols.csv` updated accordingly.

Reproduce: `decode/verify_speed_gate_xref.py`; disasm 0x4bf3c/0x7c1d4/0x844fc/0x633fc/0x86798/0x94a70;
mailbox decode `+0x10=id<<18` at 0xaea38; DBC in opendbc master `vw_mlb.dbc`.
