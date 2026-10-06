# EPB_01 (0x104) handler + intercept/rewrite feasibility for low-speed braking

Goal: assess using EPB_01 — the ungated, works-to-standstill brake-request path — as the practical
low-speed-braking lever by intercepting/rewriting the frame on the wire, instead of patching the ASW
(which is blocked by flash-SA). Firmware-verified where stated; the executor side remains
object-table-walled (unchanged from `epb_dynamic_braking.md`).

## 1. Bus/handler reality (corrects the "different bus" premise)
Per the ESP's own RX mailbox table (`0xaea38`, verified):
- EPB_01 (0x104) = rec27 @0xaecc0: mailbox reg `0xfff7e690`, **controller `0xfff7ea00`**, handler `0x126bb`, DLC 8.
- ACC_10 (0x117) = rec23 @0xaec60: mailbox `0xfff7e670`, **controller `0xfff7ea00`**, handler `0x12701`.
- The ESP has two CAN controllers: `0xfff7e800` (mailboxes 0xfff7e4xx) carries only {0x061,0x065,0x066,0x071,0x072,0x604,0x661}; **`0xfff7ea00` (mailboxes 0xfff7e6xx) carries the main powertrain/chassis set including EPB_01, ACC_10, ACC_01, TSK, Motor, and the ESP's own TX.**

**So from the ESP's side EPB_01 and the ACC signals are on the SAME physical bus (0xfff7ea00 = powertrain/Antriebs-CAN); they differ in RX *handler*, not bus.** (A panda/harness may still number them as different buses depending on gateway forwarding — that's a harness-topology question, not the ESP's view.) Practically favorable: openpilot's existing powertrain-CAN tap already sees EPB_01.

## 2. The handler (0x126bb → 0x126ba)
A **jump-table island**: dense 4-byte `{movs rX,rY; b <body>}` trampolines (disassembled). One mailbox (`0xfff7e690`) serves 0x105/0x104/0x086 and the handler demuxes by the runtime mailbox-index register. Past the dispatch it does a length-prefixed copy into a per-message **object-table-allocated** buffer, then COM extraction — **not statically traceable** to the EPB-decel reader/executor without the runtime object table (bench RAM dump or full config-init emulation). This is the same wall `epb_dynamic_braking.md`/`com_routing_decoded.md` documented; disassembling the island further does not break it.

## 3. E2E — a rewrite MUST be valid (firmware-verified)
EPB_01 is E2E-protected: `EPB_01_CHK` (byte0, 8-bit) + `EPB_01_BZ` (byte1 low nibble, 4-bit counter).
The ESP validates the **MLB XOR checksum** — `FUN_0005f57c`:
```
seed = (id>>8) ^ (id&0xff)        // from the mailbox arb word; for 0x104 -> 0x05
acc  = seed; for each payload byte: acc ^= byte
frame invalid iff acc != 0        // byte0 included, so a correct frame XORs to 0
```
Counter (BZ) continuity is checked separately in the COM layer (standard VAG: +1 mod 16/frame).
⇒ Any rewritten/injected EPB_01 needs `byte0 = 0x05 ^ byte1 ^ … ^ byte7` and a continuous BZ, or it's flagged invalid (openpilot's VW checksum/counter code already does this class of E2E).

## 4. Signal encoding to request braking
- `EPB_Verzoeg_Anf` (byte2, 0.048 m/s²/bit, offset −7.968): raw = (7.968 − |decel|)/0.048.
  e.g. −2 m/s² → 124 (0x7c); −3 → 103 (0x67); 0 → 166 (0xa6); max −7.968 → 0.
- `EPB_Freig_Verzoeg_Anf` (bit15 = byte1 bit7): enable = 1.
- Keep `EPB_Fehlerstatus`(50-51)=0, `EPB_QBit_*` valid, and `EPB_Schalterposition`/`EPB_Konsistenz_ACC`/`EPB_Status` consistent (the reader likely cross-checks these — unverified, see §5).

## 5. Feasibility verdict — viable but with real obstacles (none hand-waved)
PRO: no ASW patch, no flash-SA, no checksum-repair — sidesteps the entire firmware-write problem.
Obstacles:
1. **Dual sender → must MITM, not inject.** The real EPB ECU (EPB_D4) continuously transmits EPB_01. Adding frames collides the BZ counter → E2E fault. The clean method is a **CAN bridge/firewall**: split the powertrain bus so the EPB ECU is on one segment and the ESP on the other, and rewrite EPB_01 in transit. That's a hardware interposer (like comma's camera-harness pattern but on the powertrain bus), not a passive Y-tap. On a multi-drop bus you cannot otherwise remove the EPB ECU's frames.
2. **Plausibility gates unverified (object-table wall).** The EPB-decel reader may require EPB_Fehlerstatus=0, valid quality bits, and consistency between EPB_Verzoeg_Anf and the switch/ACC state. A decel with inconsistent accompanying fields may be ignored or faulted. Only a bench/on-car test (or breaking the object-table wall) settles which fields are mandatory.
3. **Off-design path.** This is the EPB "Notbremsfunktion" (emergency-stop-on-lever-hold) route. Driving it for routine ACC creep/stop braking is off-design: likely coarse, may log DTCs, and the EPB ECU's own state machine still believes it is not requesting braking (possible consistency/arbitration conflict).
4. **Safety.** Spoofing a brake request on the powertrain safety bus commands real hydraulic braking; validate only on a bench/closed course.

## 6. Cheapest way to de-risk (before any hardware)
- On-car (read-only first): log EPB_01 while briefly holding the EPB lever at low speed (off public road) and record the exact byte pattern the EPB ECU sends when it DOES command decel — that reveals the real, ESP-accepted combination of EPB_Verzoeg_Anf + enable + status/quality/consistency fields (and the BZ/CHK), i.e. a known-good template to replay/modify. Watching ESP_05 (`ESP_Verz_EPB_aktiv` bit58, `ESP_Status_Bremsdruck`) + wheel decel confirms acceptance.
- Then bench the bridge-rewrite with that template before trusting it on-car.

Firmware refs: mailbox table 0xaea38 (rec27); handler island 0x126ba; E2E verifier `FUN_0005f57c`;
DBC EPB_01 in opendbc `vw_mlb.dbc`. Executor: base-ESC path (`epb_dynamic_braking.md`).
