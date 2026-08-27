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

## Ghidra project state  (ecus/esp8/ghidra_proj, ARM:BE:32:v5t)
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

## Read / flash path (goal a)  (PARTIAL)
- ESP supports full UDS incl **0x22/0x23 read**, **0x2E/0x3D write**, **0x34/0x36/0x37 flash**,
  **0x27 security** (SA2 key already extracted — see memory abs-sa2-key). On-car the ABS did NOT
  answer at 0x713 over OBD (see abs-sa2-key); RE is on the ASW image only.
- The real UDS dispatcher FUNCTION is not yet pinned: SID-CMP searches hit data-region false
  positives; 0xb1e14 "service table" was a 0x00..0x54 ramp (red herring). NEXT: find the
  code-region function that reads the ISO-TP RX buffer SID and does the service table lookup;
  trace 0x27 (SA2 seed/key gate), then 0x23/0x2E/0x34 handlers.

## Open items / next steps
1. Split Ghidra memory (exec ≤0xa2000) so re-analysis stops fabricating data-region functions.
2. Prove/disprove the ECD 15 km/h floor: unit of struct[0x3b]/DAT_0000b9b4; trace struct+0x25 →
   the ESP_05 (0x106) packer bit33. Find the 0x106 packer (via its descriptor / RAM buffer).
3. Pin the UDS dispatcher + 0x23/0x2E/0x34 handlers for concrete read/flash evidence.

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
