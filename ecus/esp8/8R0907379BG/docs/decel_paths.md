# ESP deceleration control & the below-15 km/h braking path — 8R0907379BG

Full static trace of the ESP8's deceleration-request pipeline, from CAN reception to the
brake-pressure executors. Every function/address below is labelled in `symbols.csv` and
reproducible via `ApplySymbols.java`. Where a link is **not** closable by static analysis
(the AUTOSAR COM signal layer uses runtime index addressing) that is stated explicitly —
no empirical inference is presented as a code fact.

## Decompilation coverage
CODE region 0x0–0xa2800 (665,600 B): **88.9 % instructions** (216k insns, 3,176 functions) +
7.6 % defined data = **96.5 % defined**. The residual 3.5 % undefined is ~5 KB of marginal
fragments + ~16 KB of literal-pool/table data, i.e. **~99 % of real code recovered**. Coverage
converged (harvest/disasm passes returned <10 new fns). Scripts: `EspCoverage/EspHarvestFnPtrs/
EspDisasmUndef/EspReadPtrs/EspFindConst.java`.

## 1. The pipeline (all stages CODE-VERIFIED)
```
CAN frame ── can_rx_indication (0x8e3ec, generic: raw bytes -> record state_ram) ──┐
                                                                                    │  (AUTOSAR COM,
                                                          index-driven signal extract│   runtime-indexed
                                                          com_pdu_router (0x9546e ..) │   -> NO static xref)
                                                                                    ▼
   4 raw decel sources in RAM, each built by its own producer:
     type1  decel_src_type1     0x403fac
     type2  decel_src_comfort   0x403a40   <- decel_src_comfort_calc  (0x88a88)  [comfort/ECD]
     type4  decel_src_type4     0x407bb4   <- anb_decel_request_build (0x4bf3c)  [ANB/emergency]
     type5  decel_src_type5     0x403d76
        each gated by status byte 0x405dcd[i]==0x10  AND  enable bit 0x80  AND  value>0
 → decel_req_preprocess (0x7f4ec): 4-tick slew interp  out = raw-((3-(ctr&3))*grad>>2), enable bit0x40
        writes decel_req_array 0x405a90 (type1@+0, comfort@+4, type4@+0x10, type5@+0x1c)
 → decel_req_assemble   (0x86798): emits up to 4 typed 12-byte records, tagging type = 1/2/4/5
        each record: field+0 = slewed value, field+8 = RAW value, +6 = type, +0xb = mode flag
 → decel_req_arbitrate  (0x94a70): MAX-wins (see §2). Winning TYPE byte -> ecd_mode (0x405aba)
 → decel_ctrl_top       (0x9b7b4): clamp result to [min, 0x3ffe]
 → ecd_state_machine    (0x633fc): calls ecd_speed_gate first, then dispatches on ecd_mode (§3)
```

## 2. Arbitration = MAX deceleration wins, with a raw-value preempt (VERIFIED @0x94a70)
- **Primary** max over each record's field+0 (slewed) → `decel_arb_output+0x10`; its type → `ecd_mode`.
- **Secondary** max over each record's field+8 (**raw**, un-slewed) → +0x12; its type → +0x36.
- **Preempt**: when `(decel_frame_counter 0x400804 & 3)==0` and the secondary winning type changed,
  flag +0x3b bit0x20 is armed and the **secondary (raw) request overrides the primary** — lets a
  fresh raw request bypass the slew limiter.
- **`ecd_mode` = the winning request's type byte**, and the state machine dispatches on that same
  value, so **type ≡ mode** (type4→mode4, type2→mode2). This identity is the backbone of the trace.

Priority answer: **there is no fixed source priority — the numerically largest deceleration request
wins**, and its source-type selects the executor. Two requests of equal magnitude keep the incumbent
(strict `<` compare).

## 3. Executors and the 15 km/h floor (VERIFIED @0x633fc / 0x844fc / 0x6de38 / 0x9c788)
`ecd_state_machine` runs `ecd_speed_gate()` first, then:

| type≡mode | executor | pressure shape | reads 15 km/h flag? | below 15 km/h |
|---|---|---|---|---|
| **2** | `ecd_decel_pressure_calc` (0x6de38) | smooth 6-point ramp, peak-tracking | **YES** (only reader) | **suppressed** |
| **4** | `ecd_emergency_pressure` (0x9c788) via `ecd_emergency_dispatch` (0xa15d0) | **flat step** — all 6 setpoints = requested value, fixed timing {0x14,10,3,7} | **NO** | **active (bang-bang)** |
| 1 / 5 | fixed sub-profiles / ramps inside `ecd_state_machine` (500/1000/2000/2500 …) | small fixed setpoints | — | — |

**The 15 km/h floor (`ecd_speed_gate` 0x844fc):** if both axle speeds `0x4022a2` and `0x402482`
are `< 0x78` (=120 = 15.0 km/h at 0.125 km/h/bit; `cmp #0x78` @0x845fc/0x84608) it debounces
(~30 cycles) then **clears** `flag_ecd_speed_avail` (0x403da8 byte[1] bit0x40); above, it sets the
flag and reloads the debounce. **The gate writes ONLY that flag — never `ecd_mode` or the substate.**
The comfort executor (mode 2) is the *only* code that reads the flag, so it is the only thing the
floor disables. **The emergency executor (mode 4) never reads the flag → it brakes below 15 km/h**,
but as a flat step (rough) rather than the comfort ramp. This is the code-level mechanism for
"emergency/ANB braking works below 15 km/h with a rougher loop".

## 4. Source producers (VERIFIED) and the ONE COM-indirect link
- **type2 / comfort** `decel_src_comfort_calc` (0x88a88): computes 0x403a40 from raw inputs
  0x403a80/0x403a86 (the same 0x403a86 the speed gate consumes), gain 0x40545c, clamp ±0x7fff/−0x8000.
  Its raw inputs arrive via `com_decel_double_buffer` (0x64ce4) staging.
- **type4 / ANB-emergency** `anb_decel_request_build` (0x4bf3c): builds 0x407bb4 with a 0xcd0/0xcd
  first-order ramp filter and a large ANB plausibility/fault-bit bank; inputs are COM-extracted
  signals (0x405abe, 0x40553b, 0x405cac, 0x4055b4 …) + calib base 0x40081c.

**What is NOT closable statically:** which CAN frame feeds each producer's COM-signal inputs.
`can_rx_indication` only copies raw frame bytes into the record's `state_ram` (ACC_10 → 0x404588);
signal extraction is done by the index-driven COM layer. Proof it is index-driven: the constant
`0x404588` occurs **exactly once in the whole image** — inside the config table at 0xaa0d4 — and the
ACC_10 payload bytes have **zero** static read-xrefs. So "ACC_10.ANB_Zielbrems → type4" cannot be
asserted from static xref, only inferred from naming (ACC_10 = ANB frame; 0x4bf3c = ANB builder).
The correspondence is strong but is labelled inference, not a code fact.

## 5. CAN reception tables (VERIFIED)
- `0xafae0` (`can_id_array`) — the 0x100–0x116 cluster: ESP_01–05 (TX), TSK_01/02/04/05, ACC_01,
  **ACC_05 (0x10d)**. No 0x117.
- `0xa9fc0` (`can_msg_cfg_table`, 223 × 0x14) — includes **ACC_10 (0x117) = rec#13 @0xaa0c4**,
  routine `can_rx_indication` 0x8e3ec, state `acc10_rx_state` 0x404588. **So the ESP receives BOTH
  ACC_05 and ACC_10**, on two different tables/channels.

## 6. Openpilot implication
Below-15 km/h braking on this ESP runs through the **type4 / mode4 emergency executor**, which is
**not** subject to the 15 km/h comfort gate and applies a **flat pressure step** (hence the observed
roughness). The comfort/ECD executor (mode 2, e.g. TSK cruise) is hard-gated off below 15 km/h.
Smoothing on the openpilot side should therefore: rate-limit the transmitted decel request, keep
frame updates fresh (so the slew/preempt term stays small), and close an outer loop on measured
deceleration (`ESP_05` accel / `ESP_Bremsdruck`) — the ECU's own low-speed loop is bang-bang and
will not smooth a stepped request for you.

---
Symbols: `ecus/esp8/8R0907379BG/symbols.csv` (apply via `core/ghidra/ApplySymbols.java`).
15 km/h floor proof: `docs/ECD_path.md`.  ACC_10 reception: `docs/acc10_read_path.md`.
