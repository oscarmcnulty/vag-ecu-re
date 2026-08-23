# EPB 8K0907801N — reverse-engineering findings

Audi B8/8R Electronic Parking Brake control module (J540, VCDS addr 53), component **EPB_D4**
on the MLB powertrain/comfort CAN. This is the **actuator endpoint**: it receives external
EPB close/open requests and drives the two rear-caliper motors. Goal: map the CAN RX, confirm
which messages set/unset the EPB, and determine whether the clamp can be **partially applied**
(modulated force) for a low-speed ACC stop-and-go hold. See memory `vw-mlb-checksums`,
`mlb-stopgo-donor`, `openpilot-integration-goal`.

## 1. Container / extraction  (reproducible)
`FL_8K0907801N_0005.frf` (111 595 B, recursive-XOR encrypted, **not** AES).
```
cd ~/tools/VW_Flash && python3 -m frf.decryptfrf --file <path>/FL_8K0907801N_0005.frf --outdir <fw>
python3 core/odx/odx_extract.py <fw>/FL_8K0907801N_0005.odx -o <fw>
```
Yields 4 UDS blocks (SOURCE-START-ADDRESS in the ODX is the **block id 1..4, not a physical
address** — the memory map is inferred from the code):

| file        | UDS id | size    | pages     | role                                            |
|-------------|--------|---------|-----------|-------------------------------------------------|
| DB_4_01.bin | 1      | 114688  | 7×16 KB   | main ASW (build/version strings, CAN driver, ISR)|
| DB_6_02.bin | 2      |  98304  | 6×16 KB   | ASW cont. — **CAN RX matrix + signal decode**, fixed low page |
| DB_8_03.bin | 3      |  16384  | 1×16 KB   | coding/CAL — mostly 0x3F fill + "AUDI_B8_0005"   |
| DB_2_04.bin | 4      |   1280  |           | driver / EEPROM defaults                        |

Plaintext (no scramble): strings `X024`, `May 19 2010`, `8K0907801N ;X10;BL01BL02BL03X004`,
`AUDI_B8_0005` are directly readable.

## 2. Architecture — **Freescale/NXP HCS12X (S12X)**, big-endian, 16 KB PPAGE banking
Established empirically (`ghidra_scripts/ArchProbe.java`): under `HCS-12X:BE:24` the code
decodes to coherent S12X — RMW peripheral init (`LDAB/ANDB/ORAB/STAB` on 0x00xx regs), banked
`CALL addr,page` (page bytes 0xE0–0xFF → ~512 KB flash space), real `PSH`/stack-frame
prologues, const-init tables. M16C / V850 / MCS96 all decode to semantic garbage.
The reset/IRQ vector table (S12X local 0xFF80–0xFFFF) is **0x3F-fill** in these blocks → it
lives in the **protected bootloader**, which the app FRF does not reflash.

**Page map (confirmed):** the two app blocks are contiguous banked 16 KB flash pages —
**DB_4 = PPAGE 0xE0–0xE6**, **DB_6 = PPAGE 0xF8–0xFD**. Combined(`cat DB_4 DB_6`) offset =
`(P−0xE0)*0x4000` for DB_4, `0x1c000+(P−0xF8)*0x4000` for DB_6. Fixed-low page (local 0x4000–0x7FFF,
holds the CAN RX matrix) = PPAGE 0xFD @ combined 0x30000; fixed-high 0xFF (reset+IRQ vectors) =
protected bootloader, absent. Windowed ref (local 0x8000–0xBFFF) → combined = page_base + (local−0x8000).
Verified: `CALL 0xaa5c,0xe2`→0x0aa5c, `CALL 0x8846,0xf9`→0x20846 both hit function prologues.

## 3. CAN driver — on-chip **MSCAN** (regs 0x0140–0x017F), in DB_4 ≈ 0x6600–0x6C00
- 0x140 CANCTL0, 0x141 CANCTL1, 0x144 CANRFLG, 0x145 CANRIER, 0x150+ CANIDAR/MR (accept filters),
  **0x160–0x16F CANRXFG** (received ID+data), **0x170–0x17F CANTXFG**.
- **RX ISR @ DB_4 0x69cc**: reads the ID from CANRXFG 0x160, then a table-driven dispatch
  (`0x6a12: LDD #0x1c` = loop over the acceptance table, `CPY 0x4857,IX`), stores the matched
  index → 0x109f and `CALL 0xaa5c` copies the payload into the per-message RAM buffer
  (dest-ptr table at local 0x48e8, length table at 0x48cb).

## 4. CAN RX subscription — **27 messages** (full table: `analysis/can_rx_matrix.csv`)
Acceptance-ID table at local **0x4857** (id stored as `id<<5` in RXIDR0:IDR1 form; masked
`ANDY #0xfff8` before compare). Each msg copied to a contiguous RAM buffer. Relevant subset:

| CAN id | msg              | dlc | RAM buf | relevance                                   |
|--------|------------------|-----|---------|---------------------------------------------|
| 0x10D  | **ACC_05**       | 8   | 0x10D6  | **ACC EPB-close request** (ACC_Betaetigung_EPB) |
| 0x106  | **ESP_05**       | 8   | 0x10CE  | **ESP EPB request** (ESP_Anforderung_EPB) + Autohold |
| 0x100  | ESP_01           | 8   | 0x10AC  | speed / standstill                          |
| 0x101  | ESP_02           | 5   | 0x10B4  |                                             |
| 0x102  | Getriebe_03      | 6   | 0x10B9  | gear / selector                             |
| 0x103  | ESP_03           | 8   | 0x10BF  |                                             |
| 0x105  | Motor_03         | 7   | 0x10C7  | engine                                      |
| 0x3C0  | Klemmen_Status_01| 3   | 0x10F5  | terminal / ignition                         |
(+ 0x081,0x111,0x392,0x39C,0x441,0x520,0x581,0x585,0x590,0x5F0,0x641,0x657,0x660,0x6B2,0x6B4,0x6B7,0x6D9,0x6FF — comfort/gateway/diag; 0x080/0x700/0x752 are len-0 placeholders.)

## 5. EPB set/unset decode  (DB_6 ≈ 0x20C00–0x21090)
Decoded signals land in a CAN-RX **signal-image struct at ~0x2800** (consumers read it via a
base pointer `LDX #0x2806`, so they don't show as absolute refs — an AUTOSAR-style RTE/COM).

**ACC_05 (0x10D) byte 7 → 0x2806** (`0x20c15`):
- bit4 `0x10` = **ACC_Betaetigung_EPB** → 0x2806.0 (+ 0x2800.1)
- **3-bit field** mask `0x0e` → 0x2806.1-3  ← a *graded* ACC field, not a single bit
- bit6 `0x40` → 0x2806.4 ; freshness flags 0x2805/0x2807

**ESP_05 (0x106) byte 7 → 0x283d/0x27fc** (`0x20ffc`):
- **2-bit field** = **ESP_Anforderung_EPB** (0/1/2, 3="nicht verfügbar" → error branch clears
  0x2804.0). Matches the bus-side finding `ESP_Anforderung_EPB=2 = close`.
- + Autohold/Konsistenz booleans → 0x283e, validity → 0x283f.

## 6. Actuator drive & the partial-apply question  (traced)
**Motor drive = on-chip PWM channel 0** (S12X PWM regs 0x300-0x327). Init at DB_4 ~0xc8f0/0xca88
(PWME 0x300, POL 0x301, CLK 0x302, PRCLK 0x303, period PWMPER0 0x314). The generic output helper
@0xce42 writes **PWMDTY0 (0x31c)** from a per-channel config table (local 0x13e2/0x13e3), sets
direction, and toggles PWME ch0 (0x300.0) on/off. So the motor is driven at a **preset/controlled
duty**, and clamp force is regulated the classic EPB way — run the motor to a **target clamp
force** sensed via motor current — not by continuously modulating duty on a force error.

**The CAN interface carries discrete request STATES, not a force magnitude:**
- `ESP_Anforderung_EPB` = 2-bit (0/1/2, 3=n/a)  — open / close / hold. Discrete.
- `ACC_Betaetigung_EPB` = 1 bit; the adjacent 3-bit field (0x2806.1-3) is a status/type, not force.
- ACC_05 / ESP_05 contain **no "desired clamp force" signal**. (The module *does* decode a
  continuous 10-bit ESP_05 quantity — brake pressure/decel, `(raw-100)*3` -> 0x283b @0x20fc7 — but
  that is an ESP feedback value it consumes, not a force command aimed at the EPB actuator.)

**Conclusion — you cannot "partially set" the EPB over stock CAN.** An external requester
(ESP, ACC, or openpilot) can ask only for full **apply / release / hold**; the clamp force is the
module's own internally-calibrated target. For a smooth ACC stop-and-go hold the low-speed
deceleration and initial standstill must come from the **ESP hydraulic hold** (Auto-Hold /
`ESP_Anforderung_EPB` modulated pressure), with the EPB engaging as the **static backup once fully
stopped** — which is exactly production Auto-Vehicle-Hold behaviour.

Caveats / openings:
- The internal apply-force **target is a calibration constant**; whether the AutoHold/ACC apply
  path uses a *lower* target than the park apply is a CAL question not yet fully resolved (needs the
  banked decompile of the force controller — now unblocked by the page map in section 2/ecu.conf).
- The hardware *can* modulate force (PWM duty + current control) and the firmware already decodes a
  continuous ESP pressure value, so a **firmware mod** could implement graded apply — but stock CAN
  cannot request it, and lowering the CAL apply force trades away park-brake holding on grades.

## 7. Banked trace of the actuator layer  (page-map method)
Cross-page calls resolved by searching `CALL 0x4A hi lo page` / same-page `JSR 0x16 hi lo`
encodings against the confirmed page map (no full banked Ghidra program needed). Call chain
found bottom-up:

`PWM-helper 0xce42` (writes PWMDTY0/PWME ch0)  ← `output-driver 0xcbf1` (iterates **3 output
channels**, per-channel config table 0x4c20+ / state 0x13e2, per-channel **fault checks**:
open-load / short / over-current, e.g. `CALL 0x8630,0xe4; CPD #0xeb`)  ← `motor task 0xe50a`
(page 0xE3)  ← **no direct caller** → invoked via the **scheduler pointer-table** (the firmware
is table-dispatched cyclic tasks — cf. the RX ISR's `CALL [0x47f5,IY]`). So the apply/force
decision sits in a scheduled task reached through indirect dispatch, not a static call tree.

**Force/current setpoints — calibration in DB_8.** DB_8 (CAL, UDS block id 3) is mostly 0x3F
fill; the live parameters are one 435-byte block at **0x0105** (+ a trailer at 0x3F80 and a
checksum word 0xB63D at 0x3FFE). After a 7-byte header, a clean BE16 parameter cluster begins at
0x010C: **500, 500, 50, 500, 650, 20, 100, 100 …** — the plausible clamp-force/current targets and
timing thresholds. The presence of **distinct values (500 vs 650)** is consistent with more than
one apply target, but which word is clamp force vs current-limit vs time can't be pinned without
the A2L/map, and DB_8's PPAGE (needed to tie code refs to these bytes) isn't yet mapped.

**Net:** confirms section 6 — the module regulates clamp force to an *internal, calibrated*
target selected by its own scheduled logic; there is no bus-commandable force magnitude. Whether a
softer AutoHold/comfort target is *selected by* `ESP_Anforderung_EPB=1 (hold)` vs `=2 (close)`
lives in that scheduled apply task; reaching it cleanly needs the scheduler task-table mapped
(next), or a proper banked Ghidra overlay load to let the decompiler follow indirect dispatch.

## 8. Next
- Map the **scheduler task-table** (find the pointer array the cyclic dispatcher indexes) to reach
  the apply state machine and see how `ESP_Anforderung_EPB` 1-vs-2 and `ACC_Betaetigung_EPB` map to
  the internal force target.
- Map **DB_8's PPAGE** (same CALL/ref-encoding method) so CAL reads in the force code resolve to
  the 0x010C parameter cluster and each setpoint gets identified.
- Decode the EPB_01 (0x104) **TX packer** to anchor the `EPB_Spannkraft` estimate scaling.


## 9. Reproducible Ghidra pipeline  (raw bin + symbols.csv -> labeled project)
Everything is regenerated from committed metadata only (no decompiled source is committed).
- `./extract.sh` : FRF -> (VW_Flash recursive-XOR) -> .odx -> `core/odx/odx_extract.py` -> DB_*.bin (gitignored).
- `./reproduce.sh` : imports DB_4 @ **global 0x780000** and (via `ghidra_scripts/EpbMap.java`) loads
  DB_6 @ **0x7e0000**, maps IO(0x0-0x3FF,volatile)/RAM(0x400-0x3FFF,volatile)/fixed-low alias
  (local 0x4000-0x7FFF <- 0x7f4000), and **sets the PPAGE context per page** (0xE0-0xE6 / 0xF8-0xFD).
  That last step is essential: HCS12X forms global addresses (0x400000+PPAGE*0x4000+off) for
  windowed accesses, so without per-page PPAGE context every cross-page flow escapes to unmapped
  memory and decompiles come out empty. Then: SeedSweep (linear disasm; no reset vector exists) ->
  auto-analyze -> `core/ghidra/ApplySymbols.java` (creates+names functions, plate comments, reg/RAM
  labels from `analysis/symbols.csv`) -> ExportFunctions -> DecompileNamed.
- **Canonical address = the S12X global** above: DB_4 fn at old "combined offset" O -> 0x780000+O;
  DB_6 -> 0x7e0000+(O-0x1c000); fixed-low tables labelled at their local 0x4xxx alias. `analysis/
  symbols.csv` (schema `address,name,type,comment,source`) holds the confirmed names (13 FUNCTION +
  register/RAM/table LABELs), all source=re-trace.

- **Coverage (byte-level, `core/ghidra/CoverageStat.java` over both flash blocks):** of 212992 flash
  bytes, **96.9% are in decompilable functions, 2.9% marked as data tables** (the fixed-low CAN
  matrix/config band, via `MarkDataRegions.java`), 0.2% orphan-disassembled, and **0.02% (52 bytes)
  unaccounted**. Steps 2c/2d (mark-data + `ClaimOrphanCode`) take in-function from 53% -> ~97%;
  `SeedSweep` is constrained to flash so the uninitialized IO/RAM blocks get no junk functions.
  ~5345 functions (of which ~1150 are >=32 B substantial code; the rest are the model's RTE
  getter/setter accessors). 0 unaccounted runs >=128 B.
- Verified: `can_rx_isr`, `esp05_epb_decode`, `acc05_epb_decode`, the actuator + UDS fns decompile
  with real bodies. Note the decompiler renders the RPAGE-windowed CAN RX buffers (0x10xx) via page
  arithmetic and dead-store-eliminates inter-task signal-image writes unless RAM is marked volatile
  (it now is); the raw disassembly is the ground truth and is clean.


## 10. EPB triggers + status/control-loop  (open vs close vs hold)
### What can trigger the EPB (apply / release)
**CAN-commandable (fully reversed -- the two decoders):**
- **ESP_Anforderung_EPB** -- ESP_05 (0x106) byte7 2-bit field -> `esp_epb_req` (0x283d). 0/1/2
  (3=nicht-verfuegbar). **value 2 = close.** The ESP's channel to command the EPB (Auto-Hold
  handoff, roll-away, ESP-initiated apply). Decoder `esp05_epb_decode` @0x7e4f7f.
- **ACC_Betaetigung_EPB** -- ACC_05 (0x10D) byte7 bit4 -> `acc_epb_req_state.0` (0x2806). ACC
  stop-and-go EPB close request. Decoder `acc05_epb_decode` @0x7e4c15.
- Gated/qualified by Klemmen_Status (0x3C0 terminal), ESP_01 (speed/standstill), Getriebe_03 (gear).

**Module-internal / hardwired (NOT bus-commandable):**
- **Driver EPB switch** (hardwired to J540): pull=apply, push=release -- the primary manual trigger,
  echoed as EPB_Schalterposition in EPB_01.
- **Auto-Hold / drive-off auto-release** (internal logic off the ESP_05 Autohold flags + speed + brake).

=> The ONLY bus-commandable EPB triggers are ESP_Anforderung_EPB (0x106) and ACC_Betaetigung_EPB
(0x10D), and both are BINARY close requests -- no force magnitude, no partial apply (see sec.6).

### EPB status (EPB_01 0x104) and the control loop
`EPB_Status`: **0=open** (released) / **1=closed** (applied+holding) / **2=actuator moving**
(transitioning) / **3=fault**. There is **no separate "hold" state** -- the EPB "holds" by staying
**closed**: the spindle is self-locking, so once clamped the motors switch off and force is held
mechanically with no current. AVH/comfort "hold" at low speed is the ESP's HYDRAULIC hold, not an
EPB status.

Closed-loop actuator path (confirmed): scheduler -> `motor_apply_task` (0x78e50a) ->
`actuator_output_driver` (0x78cbf1, 3 output channels w/ per-channel open-load/short/over-current
monitoring) -> `pwm_output_set` (0x78ce42, PWMDTY0 + PWME ch0). `actuator_state_proc` (0x7988c7)
runs the motion timer (cap 0xc8=200 cyc anti-stall) and status bits. Transitions:
- **close**: drive motors apply-direction, status=2 (moving), until motor current -> target clamp
  force (internal CAL) -> motors off, status=1 (closed).
- **open**: drive release-direction, status=2, until free -> status=0 (open).
- **fault** (status=3): open-load/short/over-current/timeout from the per-channel diagnostics.
The target clamp force is an internal calibration constant, selected by the module's own logic --
an external requester gets only close/open, never a commanded partial force.


## 11. CAN RX -> actuation: the full control-loop data flow  (traced + labelled)
End-to-end path from a received CAN frame to the caliper motors (all functions in symbols.csv):

1. **RX** `can_rx_isr` (0x7869cc): MSCAN0 RX IRQ -> read ID from CANRXFG (0x160) -> 28-entry
   acceptance-table dispatch (0x4857) -> `can_rx_copy_msg` copies the payload to the per-message
   RAM buffer (0x10a0..0x115e).
2. **Signal decode** (scheduled COM tasks): per-message decoders unpack the buffers into the
   **CAN signal image** (~0x2800). EPB-relevant:
   - `acc05_epb_decode` (0x7e4c15): ACC_05 -> `acc_epb_req_state` (0x2806): ACC_Betaetigung_EPB.
   - `esp05_epb_decode` (0x7e4f7f): ESP_05 -> `esp_epb_req` (0x283d, 2=close), Autohold `esp_flags`
     (0x283e), `esp_pressure` (0x283b).
3. **RTE snapshot** `rte_copy_sig_image` (0x7e4022): bulk-copies the signal image into the
   application snapshot the control tasks read (they read the snapshot via base-pointer, NOT the
   live image -- which is why direct xrefs to 0x283d/0x2806 dead-end).
4. **Arbitration / state machine** (scheduler-dispatched, RTE-hidden): reads the snapshot (driver
   switch + esp_epb_req + acc_epb_req + speed + Autohold), decides apply/release/hold + target
   clamp force, updates EPB_Status, and issues the channel commands. Bracketed precisely between
   (3) and (5); its exact entry sits behind the scheduler fn-pointer table (format
   `{addr16 windowed, page8, pad8}`, e.g. the CAN dispatch table at 0x47f5).
5. **Actuator command** `epb_actuator_set_channel` (0x78cbb1): sets per-channel DIRECTION
   (0x13e2[ch] bit1 = apply vs release) + DUTY (0x13e3[ch]); `epb_actuator_ch_enable`
   (0x78cb80 / 0x78cd37) sets ENABLE (0x13e2[ch] bit0); `epb_actuator_ch_disable` (0x78cccb) clears it.
6. **Actuator output** `motor_apply_task` (0x78e50a, scheduled) -> `actuator_output_driver`
   (0x78cbf1): iterate the 3 output channels, per-channel fault check `epb_actuator_ch_fault`
   (0x78cc78, open-load/short/over-current), then `pwm_output_set` (0x78ce42) -> PWMDTY0 (0x31c) +
   PWME ch0 (0x300.0) -> motor H-bridge.
7. **Force regulation** `actuator_state_proc` (0x7988c9): motion timer (cap 0xc8=200 cyc anti-stall);
   motor runs until current (=clamp force) reaches the internal CAL target.
8. **TX** message composers (e.g. FUN_7eec4c-style): call the signal getters and bit-pack them into
   EPB_01 (0x104: EPB_Status/Spannkraft/Schalterposition) + the other TX frames.

### open / close / hold as the status machine sees them
- **close (apply)**: direction=apply, enable=on, run duty -> current rises to target clamp force ->
  motors off, **EPB_Status=1 (closed)**. Held mechanically (self-locking spindle, zero current).
- **open (release)**: direction=release, enable=on -> run until calipers free -> **EPB_Status=0 (open)**.
- **moving**: **EPB_Status=2** during either transition.
- **hold** is NOT a distinct status -- it is the *closed* state maintained. Low-speed comfort "hold"
  for ACC is the ESP hydraulic Auto-Hold; the EPB only latches statically once stopped.
- **fault**: **EPB_Status=3** on open-load/short/over-current/motion-timeout from (6)/(7).


## 12. Conditions for ACC_05 to trigger EPB enablement  (traced to the RTE port boundary)
Traced ACC_05 -> the arbitration input. Snapshot flow: `acc05_epb_decode` (0x7e4c15) unconditionally
unpacks ACC_05 byte7 into the signal image (0x2806) + freshness flags; a task runnable (FUN_788ae7)
copies the image into a snapshot (dest 0x1251 = copy of 0x2806, 0x1252 = copy of 0x2807); the
arbitration SWC reads the snapshot via RTE getters (`FUN_788ead` = ACC_Betaetigung_EPB bit 0x1251.0;
`FUN_788eb9` = the 3-bit field 0x1251.1-3; `FUN_788eb3` = freshness 0x1252.0), which are invoked
through RTE function-pointer ports -> the SWC conditionals sit behind that indirection.

**Layer 1 - ACC_05 must be VALID (firmware-confirmed, generic AUTOSAR COM):**
- Received ALIVE: per-message deadline monitor (`FUN_7e4a9e`/`FUN_7e496d`, state 0x272c/counter 0x2731,
  per-message threshold table 0x5277). On timeout the signal reverts to default (0) -> request dropped.
  A single ACC_05 frame is NOT enough; it must be streamed continuously to stay alive.
- E2E/DLC valid: DLC checked against `can_rx_dlc_table`; checksum+BZ counter must pass or the buffer
  isn't updated. Decode then sets the per-signal freshness flags (0x2807.1, 0x2805.80).

**Layer 2 - signal content the getters expose (firmware-confirmed):**
- `ACC_Betaetigung_EPB` = 1 (the request bit, 0x1251.0).
- the accompanying **3-bit field** (0x1251.1-3) and the **freshness/status byte** (0x1252) must carry the
  qualifying values -- VW pairs the actuation bit with a status/mode (and E2E counter), so a bare bit
  set with a stale/zero status is rejected by the SWC.

**Layer 3 - arbitration SWC gates (behind the RTE port; standard VW EPB, verify on bench):**
- **Coding/adaptation** must enable the ACC (comfort) EPB interface. THE make-or-break, vehicle-
  specific gate: on this Q5 the *engine's* ACC_05->EPB path is coding-gated OFF ([[vw-mlb-checksums]]
  UPDATE 66); the EPB module has its own coding for the comfort/ACC apply that must be enabled.
- **Standstill**: vehicle at v~=0 (ESP_01) -- the EPB is a static clamp, only latched at rest.
- Terminal 15 on (Klemmen_Status 0x3C0), no inhibiting EPB fault, EPB not already mid-transition.

**=> For openpilot:** stream a fully-valid ACC_05 (correct XOR/E2E seed 0x0C + incrementing BZ counter,
continuously so it stays alive) with ACC_Betaetigung_EPB=1 AND the correct accompanying status field,
while the module sees standstill -- AND the EPB must be coded to accept the ACC comfort interface. The
coding gate is the decisive unknown; check the EPB long-coding/adaptation before relying on this path.


## 13. RX-indication dispatch + the RTE runtime-dispatch wall
Resolving the pointer tables closed the RX side of the loop and located the architectural wall:
- `can_rx_isr` -> `can_rx_copy_msg` dispatches each subscribed message through the **RX-indication
  hook table `com_rx_indication_table` (local 0x4922)**: every real message (ACC_05 idx20, ESP_05
  idx21, ...) -> **`com_rx_indication` (0x7e4a9e)**, the placeholders -> `com_rx_special_handler`.
- `com_rx_indication` does the per-message deadline/alive update + E2E/DLC check (via
  `com_deadline_check` 0x7e496d, state 0x272c, thresholds `com_rx_deadline_thresholds` 0x5277).
- The **signal unpack** routines (`acc05_epb_decode`, `esp05_epb_decode`) and the **arbitration SWC**
  (which reads the snapshot via the `rte_get_*` accessors) are invoked through **runtime-computed
  function pointers** -- the code does `(*(code*)((PPAGE<<0xe)|addr))()` where the pointer lives in a
  RAM struct populated at boot from ROM config, NOT a static {addr,page} table (searched every
  format: 0 static pointers to the decoders / getters / task). This is the model-generated AUTOSAR
  RTE dispatch the repo flags as needing **boot emulation** to resolve statically; the direct call
  graph reaches the RX-indication and the actuator command layers but cannot cross this dispatch.
- What *is* statically nailed: the input side (`rte_input_snapshot_task` 0x788ae7 snapshots the ACC
  request 0x2806 -> 0x1251, exposed by `rte_get_acc_betaetigung_epb`/`_field`/`_freshness`) and the
  output side (`epb_actuator_set_channel` -> `actuator_output_driver` -> `pwm_output_set`). The
  arbitration between them is the one runtime-dispatched SWC.

## 14. Crossing the RTE wall WITHOUT emulation: the COM bytecode table
Building the emulator (ghidra_scripts/EmulS12X.java, EmulatorHelper-based) revealed the paged
`segment` CALLOTHER blocker -- but a static find made emulation unnecessary. The COM signal-unpack
dispatch is a **bytecode table** in the config band (~0x7f5340+), interpreted by a COM engine:
each record `c2 03 00 <len> <addr16>` = "call the unpack routine at <addr16>, page 0xf9" (the page
is a constant for all COM callbacks -> that's why the {addr,page,pad} pointer search found nothing).
Parsing it (opcode 0xc2) maps the dispatch statically -- 6 unpack routines:
  acc05_epb_decode(0x7e4c15), esp05_epb_decode(0x7e4f7f), 0x7e544c, 0x7e4dd9, 0x7e4d41, 0x7e541a.
So acc05_epb_decode IS reached: com_rx_indication / a COM main-fn walks this bytecode and calls it.
NEXT: find the 0xc2-bytecode interpreter (the COM engine) to confirm the walk + label the 4 other
unpack routines + their messages; the emulator harness stays as a tool (needs the `segment` userop
implemented for full boot).

## 15. The S12X emulator (ghidra_scripts/EmulS12X.java)
A working HCS12X emulator harness on Ghidra's EmulatorHelper (reuses the validated SLEIGH). Status:
- **Works:** paged instruction fetch via PCE, register state, and the paged-memory `segment`
  CALLOTHER userop (implemented as `res = base ^ inner`) so paged data/stack accesses resolve. It
  executes real firmware functions (validated on the RTE getters). On-chip regs/RAM map to global
  0xfc000-0xfffff (local addr ^ 0xfc000); the harness zero-inits both views + sets CRGFLG LOCK.
- **For full boot** (to populate + dump the runtime RAM dispatch tables) it still needs: peripheral
  read stubs (ATD/CAN/flash status), hardware-wait loop-breaking, and a proper reset/init entry
  (the app cold-start; the reset vector itself is in the absent bootloader). The other CALLOTHER
  userops (backgroundDebugMode, TableLookupAndInterpolate, ...) are currently no-oped.
- **Not needed for the unpack dispatch:** section 14's static COM-bytecode parse already resolves
  it. The emulator remains the tool for the arbitration-SWC dispatch and any other RAM-populated
  pointer we want to trace. Usage: `-postScript EmulS12X.java <entryHex> <maxSteps> [lo:hi]`.

## 16. The arbitration SWC: definitively runtime-only (status)
Exhaustive search settles the last gap's tractability:
- The COM *unpack* dispatch had a static bytecode table (sec.14) -> resolved. The RTE *runnable/port*
  dispatch (the getters `rte_get_acc_*` -> the apply-decision SWC -> `epb_actuator_set_channel`) has
  **NO static config table**: the getter/runnable/actuator-setter window-addresses appear only in
  code, never clustered in the config bands. The pointers are assembled in RAM at boot and called
  via `(*(code*)ptr)()`. So the arbitration SWC can be named ONLY by full-boot emulation.
- Emulator limitation found: Ghidra's HCS12X SLEIGH computes paged CALL targets differently from
  this project's decompilation memory map (e.g. `CALL 0x6e5c,0xfd` -> the SLEIGH's 0x786e5c, not the
  fixed-low 0x7f6e5c the decompile layout uses). So EmulS12X runs straight-line code but cross-page
  calls diverge -> a full-boot run needs a SEPARATE, SLEIGH-paging-matched memory image (single
  16-bit local space + hardware page windows) plus peripheral read stubs + hardware-wait breaking.
- **Net:** everything from CAN RX to the actuator is mapped and labelled; the ACC/ESP request
  DECODE, the message VALIDITY gates, the actuator COMMAND + closed loop, and the STATUS machine are
  all understood. The single unnamed node is the boot-dispatched apply-decision SWC between the
  request getters and `epb_actuator_set_channel`. Closing it = the SLEIGH-matched boot emulator (the
  clear but substantial next step), not a quick script iteration.


## 17. Cross-page calls SOLVED — the emulator now works
The emulator's cross-page divergence is fixed. Root cause (from the HCS12X SLEIGH, HCS_HC12.sinc):
CALL computes its target with a FLAT flash formula (0x780000 ^ addr) and RTC returns to a bare
16-bit local (Push2/Pull2), neither reconstructing the paged global this project's memory map uses;
also the emulator's fetch pointer is the Emulator's execute-address, not the PCE register.
**Fix (ghidra_scripts/EmulS12X.java):** a control-flow-aware shadow stack. Before each step we decode
the opcode; for CALL(0x4A)/JSR(0x16) we compute the target in OUR layout
(`paged(addr,page)`: windowed 0x8000-0xBFFF -> 0x400000|page<<14|off; fixed-low 0x4000-0x7FFF ->
0x7F4000+; fixed-high -> 0x7FC000+), push the correct return global, and after the step override
`emu.getEmulator().setExecuteAddress(target)`; RTC/RTS pops the shadow stack. Data/stack use the
`segment` CALLOTHER (base^inner) with RAM at 0x2000-0x2FFF->0xFE000+, 0x3000-0x3FFF->0xFF000+,
0x1000-0x1FFF->RPAGE window; `mem=addr:val` presets via the same map.
**Validated:** running `rte_input_snapshot_task` (0x788ae7) follows the full chain across pages --
`rte_copy_sig_image` (0x7e4022), the RTE getters, `FUN_7890a6` -> `0x7e40aa/ae` -- with correct
returns and no faults over thousands of steps; and `rte_get_acc_betaetigung_epb` with the snapshot
preset returns B=1. Usage: `EmulS12X.java <entryHex> <maxSteps> [watchLo:watchHi] [mem=a:v] [reg=v]`.
**Remaining for full-boot RAM-dispatch tracing:** indexed/computed calls (0x4B, `CALL [ptr]`) still
need the RAM function pointers populated (run the app init) + peripheral read stubs; the cross-page
control-flow machinery they need is now in place.


## 18. Emulator boot-init run (progress toward the RAM dispatch)
With cross-page control flow solved, EmulS12X.java now runs real init code. Driver init `FUN_78c8ad`
(clock/port/PWM setup + an init-function chain clock_pll_init -> 0x9243/0x8049/0x920b/0xa27b/0x9e49)
executes across pages through ~thousands of steps (into 0x7e236a, a GLDD table-processing loop),
then goes off the rails at an **indexed/computed CALL (opcode 0x4B)** whose pointer resolves to a
RAM/stack address (0x0ffef3) -- i.e. the boot's OWN dispatch, which the shadow stack (0x4A/0x16 only)
doesn't yet predict. Hardening added along the way: userop outputs zeroed (no uninitialized-temp
aborts), RAM init broadened to the segmented windows (0xf0000-0x100000 RPAGE + 0x100000 EPAGE),
robust unmapped-code detection, spin-loop detection, periodic logging.
**To reach the RTE-dispatched arbitration the remaining piece is 0x4B indexed-call decoding**
(decode the S12X indexed postbyte -> read the {addr16,page} pointer from its effective address ->
paged() -> shadow-push, exactly as done for 0x4A), plus running the correct RTE/OS init (not just the
driver init) so the scheduler's RAM function-pointers are populated. The cross-page foundation for all
of that is done; this is the scoped next step.


## 19. Arbitration SWC: definitive reachability + emulator speed limit
Two independent limits settle why the apply-decision SWC stays unnamed:
1. **Fully runtime-dispatched, no static edge.** Its INPUT (reads snapshot 0x1251 via the RTE getters)
   and its OUTPUT (calls epb_actuator_set_channel) are BOTH computed calls through boot-populated RAM
   pointers -- confirmed no static CALL/JSR/pointer to the getters, the setter, or the SWC itself.
   And rte_copy_sig_image has exactly ONE caller (FUN_788ae7), so the snapshot side doesn't enumerate
   other SWCs either. There is no static path in.
2. **Boot emulation is too slow to populate the dispatch.** EmulS12X (cross-page solved) runs real
   init, but the C-runtime/RTE init that would populate the scheduler RAM pointers runs through
   table-copy loops of hundreds of thousands of steps; Ghidra's p-code emulator (~ms/step) can't reach
   completion in practical time. So we can't get the RAM dispatch populated to then run the scheduler.
**Net:** the whole data path (CAN RX -> validity gates -> decode/unpack dispatch [COM bytecode, resolved]
-> signal image -> snapshot -> [SWC] -> actuator command -> closed loop -> status machine) is mapped and
labelled; the single unnamed node is the boot-dispatched apply-decision SWC. Naming it needs a FASTER
emulator (native/Unicorn-class -- Ghidra p-code won't scale to full boot) or a bench trace of the live
ECU. The cross-page emulator remains the right tool for bounded task/function tracing (validated).

## 20. Full CAN RX/TX matrix + RX->control mapping
### TX (analysis/can_tx_matrix.csv)
The EPB is primarily a STATUS transmitter. TX descriptor table at fixed-low local 0x47ad (ids stored
`id<<5 | 0x10`). Main frame **EPB_01 (0x104, 10ms)**: EPB_Status (0=open/1=closed/2=moving/3=fault),
EPB_Spannkraft (clamp force), EPB_Schalterposition (switch), BZ counter + XOR checksum (seed 0x05,
verified in [[vw-mlb-checksums]]). Plus UDS diag responses (0x5EF/0x6FF, VCDS addr 53).

### RX -> control mapping (which received message drives which control path)
| CAN id | msg | -> decoded signal | -> control effect |
|--------|-----|-------------------|-------------------|
| 0x10D | ACC_05 | acc05_epb_decode -> acc_epb_req_state(0x2806): ACC_Betaetigung_EPB.0, 3-bit field | ACC stop&go EPB CLOSE request -> arbitration -> apply (if coded+standstill) |
| 0x106 | ESP_05 | esp05_epb_decode -> esp_epb_req(0x283d) 2-bit, Autohold flags(0x283e), pressure(0x283b) | ESP EPB request (2=close), Auto-Hold handoff, roll-away -> arbitration -> apply/hold |
| 0x100 | ESP_01 | speed / standstill | GATE: EPB is a static clamp; apply only at v~=0 |
| 0x102 | Getriebe_03 | gear / selector | GATE: drive-off auto-release logic |
| 0x105 | Motor_03 | engine running/torque | GATE: drive-off auto-release (accelerator) |
| 0x103 | ESP_03 | wheel/brake state | GATE: dynamic-brake + plausibility |
| 0x101 | ESP_02 | ESP status | GATE: ESP availability |
| 0x3C0 | Klemmen_Status_01 | terminal 15/ignition | GATE: apply/release only with Kl.15 |
| 0x081,0x111,0x392,0x39C,0x441,0x520,0x581,0x585,0x590,0x5F0,0x641,0x657,0x660,0x6B2,0x6B4,0x6B7,0x6D9,0x6FF | comfort/gateway/BCM/diag | various | door/belt/NM/diag -- secondary gates + network mgmt |

### The control loop the RX drives (recap, sec.11):
CAN RX -> COM validity (deadline/E2E) -> decode/unpack (COM bytecode) -> signal image (0x2800) ->
snapshot (0x1251) -> [arbitration SWC: ACC/ESP request + switch + speed/gear/Kl.15 -> apply/release/hold]
-> epb_actuator_set_channel (dir+duty) -> actuator_output_driver (3ch + faults) -> pwm_output_set ->
motor; force regulated to internal CAL target via motor current; EPB_Status back out on EPB_01 (0x104).

## 21. Direct-call scheduler found; arbitration reachability re-confirmed
- **The task scheduler is DIRECT-CALL** at 0x788000/0x788040 (critical-bracketed groups of JSR/CALL to
  the SWC task-wrappers incl. FUN_788ae7). "No static caller" on tasks was missed analysis refs -- they
  ARE called here. Running it in the emulator traces the fast-task chain (637 steps) but does NOT reach
  the actuator: the task-wrappers that hold the apply-decision call epb_actuator_set_channel via a
  COMPUTED pointer, and that pointer is a boot-populated RAM value.
- **No static SWC dispatch table**: the SWC/task window-addrs (epb_actuator_set_channel 0x8bb1,
  the getters, motor_apply_task 0xa50a) are NOT clustered in any ROM table, NOT stored as immediates,
  NOT .data-obvious -- so the RAM pointers can't be populated by parsing ROM (unlike the COM bytecode).
- **Emulator caveats found**: dense regions (clock/init) have static disasm-alignment drift (SeedSweep/
  ClaimOrphanCode), and one target (0x78cef4) is genuinely undecodable, stalling the fast-task trace.
- **Definitive**: naming the apply-decision SWC needs the RAM dispatch populated, which requires either
  a full boot run (Ghidra p-code ~300 steps/sec, impractical for the deep init) or a live-ECU bench
  trace (CAN + BDM). Everything else CAN RX -> actuation is mapped/labelled. This is the hard floor.

## 22. Indexed-dispatch tables found + injected into Ghidra (EpbResolveDispatch.java)
The "runtime dispatch" is mostly STATIC ROM tables after all -- reached via S12X indexed-indirect
CALL (0x4B + [n16,X/Y/SP] postbyte) whose n16 is a fixed-low table base. 10 such call sites; the
fixed-low page holds 224 valid {addr16 BE, page8, pad8} function-pointer entries. Tables identified:
  0x47f5/0x4922 (COM RX dispatch/indication), 0x4a9f/0x4a8b (page-0xe2 signal handlers),
  0x5413/0x584e/0x5a11/... (OS task table -> 0x788000 scheduler, 0x788033, 0x788ad8, ...).
`EpbResolveDispatch.java` (now in reproduce.sh) resolves them all: creates a function at each of the
224 targets (+43 previously-unknown) and adds 308 COMPUTED_CALL references site->target, so the
decompiler follows the dispatch and the call graph fills in. Also handles [n16,PC] code-page tables.
**The ONE holdout**: `epb_actuator_set_channel` (0x78cbb1, the actuator dir+duty setter; ends in RTC
= paged-called) has NO stored pointer anywhere (searched every format) -- it's reached by a RUNTIME-
COMPUTED dispatch (pointer assembled, not stored), so it (and the arbitration SWC that computes it)
can't be resolved statically. That single node needs the boot-run emulator (0x4B now implemented) or
a bench trace; everything else in the dispatch is now resolved and in the decompile.

## 23. ACC_05 availability: NON-LATCHING, self-healing, first-frame grace (openpilot)
Traced the COM RX monitor for the openpilot question "must ACC_05 be present instantly from power-on?"
Answer: **NO. The monitoring is fully non-latching and self-healing, with an explicit first-frame grace.**
`com_rx_indication` (0x7e4a9e, per valid RX) resets, on a VALID frame:
- deadline counter (0x2731 stride) -> 0    (so absence-timeout self-clears)
- DLC error counter (0x272e) -> 0
- checksum error counter (0x272f) -> 0 when the MLB XOR checksum matches (per-msg seed at config+0xe;
  ACC_05 0x10D seed = 0x01^0x0D = 0x0C, chk = seed ^ bytes[1..7], byte0 = chk).
`com_deadline_check` (0x7e496d, periodic) increments the deadline counter +10 (cap 0xfff5); when
counter >= threshold (0x5277 table) it flags the message stale AND arms the **first-frame flag**
(state[7] bit0). While that flag is set, the NEXT received frame is accepted WITHOUT a BZ-counter
continuity check (the AUTOSAR E2E "new data after timeout" path) and the flag clears; from then on the
BZ counter (data[1] low nibble) must increment correctly, and a confirmation counter must build before
the signal is "confirmed valid".
**=> For openpilot:** ACC_05 can start at any time after power-on. When it begins streaming valid
frames (DLC 8 + correct XOR checksum seed 0x0C + incrementing BZ counter), the FIRST frame is accepted
under the first-frame grace (counter value irrelevant), the timeout/error counters reset to 0, and
after a few correctly-sequenced frames ACC_05 becomes confirmed-valid and the ACC->EPB path is
available. No instant-from-power-on requirement; the fault is not latched. (A DTC may still be LOGGED
historic, but the apply path gates on current freshness, not the stored DTC -- see sec.12.)
