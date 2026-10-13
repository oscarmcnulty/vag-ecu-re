# ESP8 ABS (8R0907379BG_0030) — RE findings

Target: Audi B8 Q5 ABS, **Bosch ESP8 quattro**, SW 8R0907379BG / HW 8R0907379AM, H09 0030.
Goal (openpilot): read/flash path; CAN TX/RX for functional msgs incl **ESP_05**; and where
**ECD_nicht_verfuegbar** comes from — is a 15 km/h floor hardcoded, or writable elsewhere?

## Container & load  (VERIFIED)
- `8R0907379BG_0030.sgo` = "SGML Object File"; **entire image XOR 0xFF**. header 0x0–0x200
  (partno str XOR'd, SA2 @0x1bb). firmware = `bytes(b^0xFF)[0x200:]` → `firmware/8R0907379BG_0030.bin`.
- **ARM + Thumb, big-endian BE32.** flash base **0x0**, RAM **0x00400000**.
  - CODE region **0x0–0xa2000** (mixed ARM & Thumb). DATA/cal **0xa2000–0x110000**.
  - RULE: only trust functions in 0x0–0xa2000. Ghidra auto-analysis mis-disassembles the
    data region as bogus Thumb → false "functions" (e.g. FUN_000abb9e, FUN_000aad34) whose
    "UDS SID" / dispatcher signatures are coincidental data bytes. Ignore anything ≥0xa2000.

## MCU / hardware platform  (identified 2026-10-05 — firmware fingerprint + TI public docs)
Die is bare/decapped/**UNMARKED**, so this is inference (HIGH confidence): **TI TMS470-family
ARM7TDMI** core (ARMv4T, big-endian 32), a Bosch-custom ESC derivative. Corroborated two independent
ways — firmware fingerprint and TI datasheet/reference-guide cross-check.
- **Core = ARM7TDMI / ARMv4T** (NOT ARM9/v5TE): pervasive BX interwork veneers (`arm_thumb_call_veneer`
  @0xa2428 — an ARM7 lacking BLX), zero CP15/cache/MMU code. → **Ghidra language refined to
  `ARM:BE:32:v4t`** (was `v5t`); v4t removes false v5-only BLX/CLZ decodes. Re-import to realize it
  (existing committed decompiles were generated under v5t and are largely valid; code-region ARM/Thumb
  decode is unaffected except the spurious BLX/CLZ).
- **RTOS/build string** @file 0xa4d5b: `"ERCOSEK V4.1.17k TMS_470 (c)ETAS Jul 12 2006"` (ETAS OSEK, TI
  TMS470 target port) — the decisive platform fingerprint.
- **Reset vector @0x0 = self-loop** (`B 0x0`): the ASW is entered *by SBOOT*, not via the reset
  vector. SBOOT is reached from ASW via monitor SVCs (`SVC #0x13–0x16/#0xFF10`, `asw_start_sboot`
  0x8f440).
- **Peripheral map = TI TMS470 "peripheral frames" @0xFFF7xxxx** (confirmed assignments; TI
  TMS470R1B1M datasheet memory map + SPNU197e):
  | base | module | our label |
  |---|---|---|
  | 0xFFF7E800 | **HECC1 control regs** (CANME@0x00/CANMD@0x04/CANTRS@0x08/CANTA@0x10/CANRMP@0x18/CANRML@0x1C) | `hecc_module_a` (was mislabeled `flexcan_module_a`) |
  | 0xFFF7E400 | **HECC1 mailbox RAM** (32×16-byte mailboxes) | ctrl-sel 1 in `rx_mailbox_resolver` |
  | 0xFFF7EA00 | **HECC2 control regs** | `hecc_module_b` (was `flexcan_module_b`) — the vehicle/diag bus |
  | 0xFFF7E600 | **HECC2 mailbox RAM** | ctrl-sel 2; diag mailbox lives here |
  | 0xFFF7D400 | **SPI2** (stock B1M frame) — firmware uses as ESC valve-bank/wheel-channel | `esc_valve_mmio` |
  | 0xFFF7D500 | **I2C5** (stock B1M frame) — firmware uses as ESC valve-bank/wheel-channel | `periph_i2c5_valve` |
  | 0xFFF7D600 | **RESERVED** (stock B1M frame) — firmware uses as ESC valve-bank/wheel-channel | `periph_rsvd_d600_valve` |
  | 0xFFF7EC00 | **GIO** (stock B1M frame) — firmware uses for ESC valve-enable/driver GPIO | `periph_gio` |
  | 0xFFF7F000 (0xF0A0) | **MibADC** (stock B1M frame) — firmware pump/motor sub-reg @0xF0A0 | `periph_mibadc` |
  | 0xFFF7F400 | **SCI1** (stock B1M frame) — firmware writes config bytes (+0x2f/0x33/0x37) | `periph_sci1` |
  | 0xFFF7F800 | **SPI1** | `periph_spi1` |
  | 0xFFF7FC00 | **HET** (high-end timer) | `periph_het` |
  | 0xFFFFF700 | **MSM** (memory security module) | `periph_msm` |
  The CAN cell is **TI HECC** (the old `flexcan_*` symbol names were wrong — HECC uses memory-mapped
  16-byte mailboxes + the CANTA/CANRMP/CANRML control regs our ISR polls; it is NOT Freescale FlexCAN
  and NOT D_CAN). Clock: external **15.000 MHz crystal** (Kinseki, on teardown photo) → internal PLL.
- **CORRECTION 2026-10-11 (verified against the SM470R1B1M-HT datasheet SPNS155I, Table 8-7):** the HECC1/
  HECC2 control + mailbox-RAM frames above match the datasheet **exactly** (4/4). But the ESC actuator
  frames were previously mislabeled as dedicated "valve/pump" peripherals — in the stock B1M map they are
  **SPI2 (0xD400), I2C5 (0xD500), RESERVED (0xD600), GIO (0xEC00), MibADC (0xF000), SCI1 (0xF400)**. The
  firmware drives valve/pump hardware **through** these frames, i.e. they are repurposed by the Bosch-custom
  mask (or wired to external driver ICs), not stock-function peripherals. See the custom-mask note below.
- **CUSTOM-MASK / PART# caveat (2026-10-11):** this is a Bosch-custom derivative on the TMS470R1x BE
  platform, **not a bone-stock catalog B1M**. Evidence: (1) the ESC actuators sit in stock SPI2/I2C5/GIO/
  SCI1/MibADC/reserved frames (above); (2) the firmware flat-addresses flash content **past the 1 MB B1M
  limit** — SEG2 executable code to file 0x10a000, the signed CAL block to 0x133be9, and main-code pointers
  reaching 0x1312d0 (~1.22 MB). No standard TMS470R1x exceeds 1 MB, so either external memory is mapped on
  the expansion bus (CS[5]/CS[6]) or the die carries extended flash. Consequence for the die teardown: the
  **catalog SM470R1B1M-HT bare-die Table 4-1 (152 pads, 5.30×5.38 mm) is NOT a pad-for-pad template** for
  this silicon. The die is also one of several in a multi-die chip-on-board hybrid (the MCU is the die with
  the on-die flash/RAM arrays; the smaller companion dies are valve/pump drivers + watchdog). Do not gate
  the MCU ID on a pad-overlay match — the exact HECC address match + ERCOSEK string already settle the family.
- **For fault injection:** no cache/MMU/branch-prediction (ARM7TDMI 3-stage pipeline) ⇒ deterministic
  timing, glitch-friendly. Flash is TI **F035** with the TI **MSM** (Memory Security Module) readout
  protection — the SBOOT-side gate to target. See `docs/SECURITY_ACCESS.md` avenues 3 & 5.
- **Peripheral/MMIO labels (symbols_merged.csv + symbols.csv, 2026-10-11):** all datasheet frame bases
  the firmware uses are now labelled with datasheet+usage comments — the HECC frames + mailbox RAM, the
  repurposed ESC frames (SPI2/I2C5/RESERVED/GIO/SCI1/MibADC), SPI1, HET, MSM, EBM, and the SYS-module
  bases (RTI/CIM/PSA/DWD/DEC/DMA/MMC/IEM/DMA-cmd-buffer/SYS). Applied by `ApplySymbols.java` at reproduce
  step 06.
- **Register-level decompile aid (`ghidra_scripts/EspPeripherals.java`, reproduce step 06c):** creates a
  volatile `PERIPH` block (0xFFF00000+0x100000) so the MMIO labels resolve; defines a `HECC` control-register
  struct (CANME/CANMD/CANTRS/CANTA/CANRMP/CANRML/… per SPNU197e) + a `HECC_MBOX[32]` mailbox-RAM struct and
  types the HECC base/RAM literal-pool pointers with them (CAN ISRs now read `hecc1->CANTA`, `mbox[n].MID`);
  types the other peripheral-base pool constants as named pointers; and labels the ARM vectors 0x0..0x1c.
- Citations: TI SPNU197e (TMS470R1x CAN/HECC Reference Guide), TMS470R1B1M datasheet (ti.com).

## Ghidra project state  (ecus/esp8/ghidra_proj, ARM:BE:32:v4t — refined from v5t 2026-10-05)
- Cleanup done via `ghidra_scripts/`: EspFix (RAM block @0x400000 + cleared data-region junk,
  removed 992 bogus fns), EspSweep (+165 ARM fns from STMFD prologues), EspThumbSweep
  (+447 Thumb fns from B5xx PUSH prologues). **~3396 functions**, clean decompiles in code region.
- Scripts: EspSurvey, EspFix, EspSweep, EspThumbSweep, EspDecomp (decompile addrs),
  EspDisasm (raw disasm), EspHunt (SID/xref search), EspFindDiag.
- CAVEAT: a full `-process` (with analysis) re-mangles the data region. Re-run EspFix after
  any full re-analysis, or (better next step) split memory: exec block 0x0–0xa2000, non-exec
  0xa2000+ so the analyzer never disassembles data.

## CAN TX/RX infrastructure  (VERIFIED)
- **Message-ID array @0xafae0** — flat u32 list of every CAN id the ESP handles (…0x104,
  0x105, **0x106**, 0x107,…); index = message handle.
- **Message→descriptor table @0xb33d0** — u32 records `{u16 id|flags, u16 ptr}`; the ptr
  field indexes a descriptor cluster @~0x8694 that holds **RAM signal pointers 0x00405Exx**
  (per-signal storage in RAM). flags nibble 0x00/0x20/0x60 ≈ direction/type.
- **`FUN_00005bfc` = CAN TX scheduler**: calls the transmit primitive once per message
  descriptor (DAT_00006434/6464/6618/…). **`FUN_000a2428` = transmit primitive** (msgobj,…).
- **ESP_05 = CAN id 0x106**, 8 bytes, ESP→(gateway)→engine.
  From vw_mlb.dbc: **ECD_nicht_verfuegbar = bit 33 = byte4 bit1** (0=verfügbar, 1=nicht);
  ECD_Fehler=bit32; ECD_Bremslicht=bit59. Receivers = the engine ECUs → matches "15 km/h
  floor relayed from ESP". So ECD_nicht_verfuegbar ORIGINATES here in the ESP firmware.

## ECD / speed  (STRONG LEAD — not yet proven)
- **`FUN_0000a904` = wheel-speed → vehicle-reference-speed processor.** Reads 4 wheel speeds
  (arrays via DAT_0000a8b4/a8b8/a8bc/a8c0), validity bit `&0x800000`, computes median/avg →
  `speed = struct[0x3b]` (clamped to 0x7ff and a floor DAT_0000a8cc).
- Sets a status byte `struct+0x25 = 1` when `*DAT_0000b9b4 < 0x32` (50). Multiple 0x32(=50)
  thresholds appear. Hypothesis (UNVERIFIED): 0x32 in a 0.3-km/h-style unit = 15.0 km/h and
  struct+0x25 feeds ECD availability. **Must verify: (1) the speed UNIT (scale of struct[0x3b]
  / DAT_0000b9b4), (2) that struct+0x25 → ESP_05 byte4 bit1.** Do NOT state 15 km/h until both
  are proven from the image.

## Read / flash path (goal a)
**Superseded — see `SECURITY_ACCESS.md`.** This module is TP2.0+KWP2000, not UDS (the "0x27
security / SA2 key already extracted" note below was wrong — it was chasing UDS and a since-rejected
SA2 key). The current, bench-confirmed status of the diagnostic read/flash/SecurityAccess path lives
in `SECURITY_ACCESS.md`.

## Open items / next steps
1. Split Ghidra memory (exec ≤0xa2000) so re-analysis stops fabricating data-region functions.
2. Prove/disprove the ECD 15 km/h floor: unit of struct[0x3b]/DAT_0000b9b4; trace struct+0x25 →
   the ESP_05 (0x106) packer bit33. Find the 0x106 packer (via its descriptor / RAM buffer).
3. Read/flash path: see `SECURITY_ACCESS.md`.

---
# UPDATE 2 — deeper CAN-TX + ECD trace

## Speed UNIT (VERIFIED via DBC cross-check)
- vw_mlb.dbc `ESP_v_ref` scale = **0.125 km/h/bit**; ESP internal ref speed (`FUN_0000a904`
  struct[0x3b] @RAM 0x403f38) clamps to ±0x7ff (=±255.875 km/h) → confirms **0.125 km/h unit**.
- Therefore **15 km/h = 120 = 0x78** in the ESP's speed unit (wheel-speed signals use 0.1 → 15 km/h = 150 = 0x96).
- `FUN_0000a904`'s `< 0x32` (=50) threshold = **6.25 km/h** → this is a standstill/creep flag
  (cf. ESP_Stillstandsflag), **NOT** the 15 km/h ECD floor. (Verified — do not conflate.)

## CAN TX model (VERIFIED)
- `FUN_00005bfc` (scheduler) walks message-descriptor groups (DAT_00006434→0xb33cc etc.) and
  calls `FUN_000a2428(descriptor+4,…)` per message.
- `FUN_000a2428` = trampoline: `(*fnptr)()` with `fnptr & 1` ARM/Thumb check → each message has
  its own **pack handler** (fn pointer from the descriptor).
- Descriptor group @0xb33cc holds `{u16 id|flags, u16 ptr}` records incl **`0106 86ab`** (ESP_05).
  The ptr (0x86ab) indexes a **signal-pointer array @flash 0x8690** → **ESP_05 signal storage in
  RAM 0x405e81–0x405e98** (one byte per signal). Writers/tables cluster at flash 0x57c4/0x8484/0x8690.
- Signal-oriented (AUTOSAR-COM-like) framework: signals computed by application code and written
  to their RAM byte, then packed by bit-position at TX. So `ECD_nicht_verfuegbar` = one byte in
  0x405e8x, set by an application handler — NOT a hand-packed ESP_05 function.

## ECD_nicht_verfuegbar origin — STILL OPEN (honest)
- Confirmed it ORIGINATES in this ESP (ESP_05 0x106 byte4 bit1, engine ECUs are receivers).
- NOT yet pinned: the exact application handler that writes the ECD RAM byte, hence NOT yet proven
  whether the 15 km/h (0x78) gate is (a) hardcoded in code, (b) a writable calibration in
  0xa2000–0x110000, or (c) driven by ECD-system readiness (brake temp/fault) rather than speed.
  Blind constant search is inconclusive (74× 0x0078 in cal). NEEDS: identify the ECD signal's
  exact RAM byte (decode the 0x8690 array's bit-position mapping for byte4 bit1), then find its
  writer via the COM signal-id (Com_SendSignal-style) rather than address xref.

## Ghidra project (current)
- Memory split: **CODE 0x0–0xa2000 (exec), DATA 0xa2000–0x134010 (no-exec), RAM 0x400000–0x480000**.
  This stops the analyzer fabricating data-region "functions". ~2371 clean functions.
- Full re-analysis after split OOM-killed once (4 heavy passes back-to-back) — run it alone with a
  bigger JVM heap (`-max-cpu`/analyzeHeadless default heap is small). Then re-run EspSweep+EspThumbSweep.

## Concrete next steps (priority)
1. Decode the 0x8690 signal-pointer array + descriptor bit-map to get the EXACT RAM byte for ESP_05
   byte4 bit1 (ECD_nicht_verfuegbar). Then find its writer → answer the 15 km/h hardcoded-vs-cal question.
2. UDS dispatcher (read/flash): find the ISO-TP RX handler that switches on the SID; trace 0x27
   (SA2 gate), 0x23/0x2E/0x34. (SID-CMP search unreliable — data false positives; use the RX buffer path.)
3. Re-run full analysis with larger heap for max coverage before deep tracing.

---
# UPDATE 3 — Path D: adaptation/calibration channel analysis (2026-10-12)

## Adaptation channel protocol (0xB8/0xB9/0xBA/0xBB) — firmware analysis

**Objective**: determine if VAG adaptation channels provide an arbitrary memory read path.

### Handler chain (from KWP dispatch)
1. **`kwp_adaptation_handler` @0x1d7a8** — main dispatcher for SIDs 0xB8-0xBB (plus 0xC1, 0xFB).
   16-entry × 8-byte channel table at **0xB8D98** (DATA region, pointer from literal pool @0x1d92c).
   Request format: `B8 <hi> <lo>` — two data bytes construct a 16-bit channel ID as `lo + hi * 256`.
   On match: stores table[i].byte6 as "type identifier" to RAM 0x4079CA; loads table[i].bytes[0:4]
   into R4 as parameter; BLs to the ARM/Thumb interwork veneer at 0xa2428, which dispatches to the
   type-specific sub-handler.

2. **`kwp_coding_channel_handler` @0x1bf30** — 6-state protocol machine.
   13-entry × 2-byte channel table at **0xB91E4** (pointer from DAT_0001c3c4).
   States: 0=idle, 1=channel lookup, 2-3=data exchange (0xBA=write, 0xB9=next), 4=param config,
   5=finalize. Reads from a 4-byte-record table at **PTR_DAT_0001c318** (indexed by channel).

3. **`kwp_coding_data_dispatch` @0x1c128** — record-based data reader.
   Base pointer = **PTR_DAT_0001c5e8 → 0xB9048** (fixed flash address). On 0xB8 (open): sets read
   pointer to this base. On 0xB9 (advance): pointer += 4, reads next 4-byte record. Max 68 records
   (0x44). Records contain timing/flags/mode packed in 4 bytes (timing = byte0 × 200ms).

4. **FUN_0001c438** — variant of the data dispatch. Base pointer = **PTR_DAT_0001c734 → 0xB8ED4**.
   Identical to 0x1c128 but with a different base table and sentinel-based wrapping (0xFFFFFFFF wraps
   to start).

5. **`kwp_adaptation_access_check` @0x1c6b0** — access-level gate for 0xB8/0xBA.
   Reads `sec_access_state` and `diag_access_level_read()`. For 0xB8: calls FUN_0005f362 (sets a
   single flag byte). For 0xBA with level 4: sets +0x37 = 3; level 6-7: sets +0xc = 0xC3.

6. **FUN_0009c204** — calibration measurement channel handler.
   Gated on calibration SA (bit 25 = 0x02000000) AND session 0x83/0x86 (flag check: `(flags|flags>>3)&1`).
   Stores 16-bit channel ID from request to PTR_DAT+2. Sets control flags (|= 0x10). Does NOT
   directly read from a memory address — the channel ID is stored, not dereferenced.

### Channel table contents (0xB8D98, 16 entries × 8 bytes)
| # | ch_id | state | perm | notes |
|---|-------|-------|------|-------|
| 0 | 0x2B40 | 0x2A | 0x42 | extended |
| 1 | **0x002C** | 0x00 | 0xD1 | **= channel 44 (workshop code)** — state=0 → read blocked after open |
| 2 | 0x0109 | 0x5A | 0xD2 | extended |
| 3 | 0x52D2 | 0x61 | 0x0A | extended |
| 4 | 0x0D22 | 0x80 | 0x40 | extended |
| 5 | 0x5A09 | 0xDA | 0xD2 | extended |
| 6 | 0xD2D2 | 0x55 | 0x09 | extended |
| 7 | 0x0A09 | 0x92 | 0xD2 | extended |
| 8 | 0x0278 | 0x0A | 0x08 | extended |
| 9 | 0x420A | 0x15 | 0xD2 | extended |
| 10 | 0x8040 | 0x75 | 0x09 | extended |
| 11 | 0xD5D2 | 0x06 | 0x78 | extended |
| 12 | 0x3EE0 | 0x02 | 0x46 | extended |
| 13 | 0x0C09 | 0x95 | 0xD2 | extended |
| 14 | 0xADD2 | 0x35 | 0x09 | extended |
| 15 | 0x4D09 | 0x6D | 0xD2 | extended |

Note: the table is in the DATA region (0xa2000-0xbb045). The byte values happen to decode as valid
Thumb instructions (e.g., 0xD1xx = BNE, 0xD2xx = BCS), which initially caused confusion, but the
literal pool reference and runtime access pattern are confirmed by Thumb disassembly of the handler.
Channel 0x002C (44) matches the standard VAG "workshop code" adaptation channel, validating the table.

### Special channel: 0x0FFF (security reset)
When `buf[0x22f] == 4` (protocol state) AND SID == 0xB8 AND channel == 0x0FFF:
→ calls `security_unlock_set(0)` — resets/locks the security access state.
NOT an SA unlock path. It CLEARS security, not grants it.

### VERDICT: no arbitrary memory read via adaptation channels
**All data handlers read from FIXED flash tables.** None use the channel ID as a memory address or
offset. The data flow for each path:

- **kwp_coding_data_dispatch**: fixed base 0xB9048, sequential 4-byte reads up to 68 records
- **FUN_0001c438**: fixed base 0xB8ED4, sequential 4-byte reads with 0xFFFFFFFF sentinel wrap
- **kwp_coding_channel_handler**: indexed from PTR_DAT_0001c318, channel-index selects a record
- **FUN_0009c204**: stores channel ID to RAM but never dereferences it as a pointer

No handler computes `data = *(base + channel_id * stride)` with user-controlled channel_id.
The adaptation protocol exposes calibration parameters (timing values, flag bits, mode codes), NOT
arbitrary memory contents.

### Bench confirmation (2026-10-12, session 0x83 + calibration SA unlocked)
`bench/adapt_probe.py` run with correct 3-byte format (`B8 <hi> <lo>`) and all firmware table IDs:
- **SID 0xB8/0xB9/0xBA**: NRC 0x11 (serviceNotSupported) in all formats — not implemented at all
- **VAG-proprietary SIDs 0x46-0x50**: all NRC 0x11 despite CLASS table entries — dead code
- **SID 0x21 extended formats** (address payload): NRC 0x31 (requestOutOfRange) — no address-based reads
- **SID 0x2C DynamicallyDefineLocalIdentifier**: NRC 0x11 — not implemented
- **SID 0x22 extended DIDs**: only 4 positive (0x0405-0x0408), single status bytes, no memory content
- **SID 0x31 RoutineControl**: 0 positive across 0x00-0xFF (0xC1 returned conditionsNotCorrect)

Firmware analysis + bench probe agree: adaptation channels are dead on this part number.

### Summary of all diagnostic memory access paths explored
| Path | Handler | Result |
|------|---------|--------|
| **SID 0x23 ReadMemByAddr** | 0x987f4 (Table A) | No bounds check, BUT unreachable — SBOOT takes over in 0x85 |
| **SID 0x3D WriteMemByAddr** | shared with 0x23 | Same — unreachable via SBOOT |
| **SID 0x35 Upload** | SBOOT-only | NRC 0x90 always |
| **SID 0x34 Download** | SBOOT-only | 2KB SRAM window (0x400000-0x400800), no exec trigger |
| **SID 0x21 MeasBlocks** | Table A | 48 fixed blocks — no arbitrary addressing |
| **SID 0x22 ReadDID** | Table A | Standard ranges + 4 extended DIDs (status bytes only) |
| **SID 0x2C DynDefDID** | — | NRC 0x11 — not implemented |
| **SID 0x31 RoutineCtrl** | Table A | 0 accessible routines (0xC1 gated by conditionsNotCorrect) |
| **Adaptation 0xB8-0xBB** | 0x1d7a8 | NRC 0x11 — not implemented on this part number |
| **VAG SIDs 0x46-0x50** | CLASS table | NRC 0x11 — dead code, no handler wired |

**No diagnostic-protocol memory read primitive exists on this ECU.**

### Remaining viable paths for memory readback
1. **Path A — Flash-modify-reboot** (medium risk): write a custom routine into flash via SBOOT
   download that implements ReadMemByAddr, then reboot into modified ASW. Risk: brick if
   flash write corrupts the image (need known-good backup first).
2. **Path B — JTAG** (best option): TMS470R1B1M has TDI/TDO/TMS/TCK pads on the bare die.
   Die pad locations documented in `docs/jtag_pad_id.md`. Full memory read/write with no
   firmware dependency. Requires micro-probing on the decapped die.
3. **Path C — Fault injection**: voltage glitch or clock glitch to skip security checks.
   High complexity, low predictability on this MCU generation.
