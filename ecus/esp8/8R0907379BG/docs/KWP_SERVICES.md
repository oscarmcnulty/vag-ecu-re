# ESP8 8R0907379BG — KWP2000 service dispatch & handler map (authoritative)

Complete map of the module's diagnostic services: the two KWP2000 service-dispatch tables, the
permission/CLASS table, which handlers are real native code vs. data-driven, and the per-service
reverse-engineering status. Companion to `SECURITY_ACCESS.md` (the source of truth for the
SecurityAccess/flash-security *gates*); this doc is the source of truth for the *service surface*.
Read `CLAUDE.md` first for repo conventions. Protocol is **TP2.0 + KWP2000** (not UDS) — see
`SECURITY_ACCESS.md` for transport/session entry.

All addresses are firmware VMAs (load base 0; for the main image file offset == VMA). Extracted
directly from `firmware/8R0907379BG_0030.bin`; regenerate with the parser notes at the end.

## Dispatch architecture

Two 12-byte-record tables, SID-keyed, selected by session:

- `kwp_service_table_a` @ **0xb4be4**, 17 records — **application session** (`10 89`).
- `kwp_service_table_b` @ **0xb4d80**, 13 records — **programming session** (`10 85`).

Record layout (big-endian): `{u8 SID, u8 flags, u16 x, u32 handlerPtr, u32 descriptorPtr}`.
- `handlerPtr` — Thumb/ARM via bit0. **Dual-natured (key finding, see below).**
- `descriptorPtr` — always into the **SEG2 code cluster** 0xbd3c8..0xbda74 (VMA ≥ SEG2_START
  0xbb045). This is per-service code (a validation/length/dispatch stub), present on *every* record.
- `flags`/`x` — per-service dispatch attributes; `x` is 0x3900/0x3d00 on most table-A records,
  0x0000 on all of table-B, and **uniquely 0x0100 on table-A SID 0x33** (the one obvious
  data-table marker, but not a general discriminator — see next).

### handlerPtr is dual-natured: NATIVE code vs. DATA/cal pointer  (corrected 2026-10-05)

`handlerPtr` is **not always a code entry**. The reliable rule, confirmed three independent ways
(raw-byte inspection of every target, the memory-map split, and the absence of any prologue):

- **`handlerPtr < CODE_HI (0xa2000)` ⇒ NATIVE handler.** Direct Thumb/ARM code entry; the
  dispatcher calls it. These are the core diagnostic + security services.
- **`handlerPtr ≥ 0xa2000` ⇒ DATA/calibration pointer, NOT code.** The field points into the
  calibration/data band (0xa2000..0xbb045). (The very start of that band, ~0xa2000..0xa2ab0, is in
  fact real ARM/Thumb interwork-veneer code — e.g. `arm_thumb_call_veneer` 0xa2428 — but **no**
  service handlerPtr points there; all 9 DATA/cal handlers target ≥0xa4218, squarely in calibration.) The service is dispatched by a **generic data-driven
  engine** that consumes the record's `descriptorPtr` (SEG2 code) + `flags`/`x`, treating
  `handlerPtr` as a pointer to the service's cal descriptor / data-definition table. Examples
  confirmed by raw bytes: SID 0x33 (table A) handler 0xa57f8 is a `{ptr,ptr,len/scale}` record
  array into the 0xad800+ pool; SID 0x3e (table B) handler 0xaa83d lands inside a 223×20-byte
  measurement-channel descriptor table @0xa9fcc.

**This supersedes** the prior assumption (baked into `EspServiceTables.java` step 05b2) that every
record's handlerPtr is a code pointer. For the 9 DATA/cal records, the 05b2 step fabricated a bogus
Thumb function by mis-decoding calibration bytes — those committed decompiles
(`000a57f8.c`, `000a4218.c`, `000a8e64.c`, `000aa83c.c`, `000a8d30.c`, `000a8f34.c`, …) are
**garbage and must be ignored** (consistent with `RE_findings.md`: "Ignore anything ≥0xa2000").
The real logic for these services lives in their SEG2 `descriptorPtr` stub, which is **not currently
decompiled** (the descriptor addresses fall in gaps between decompiled SEG2 functions) — the main
open coverage gap, see "Next steps".

### The central dispatcher is not yet located statically

Neither table base (0xb4be4 / 0xb4d80) nor any NATIVE handler pointer appears as a literal-pool word
anywhere in the code region — so the dispatcher computes the table address (base+offset, or a
RAM-installed pointer) rather than loading it directly, and almost certainly lives in the
0x12000–0x14000 BX jump-table island (reached from `diag_rxindication` 0x127ec) and/or SEG2,
neither of which disassembles cleanly in isolation. Consequence: the NATIVE handlers are invoked
with context in **registers** (the handler reads `r4/r5/r6/r7/r12` set up by the dispatcher), which
is why several of them decompile with `unaff_rN`/`in_r12` spaghetti — see "Decompile-quality".

## Service map — TABLE A (application session `10 89`)

| SID | svc (KWP) | handler | kind | perm CLASS (sub range) | status |
|----|----|----|----|----|----|
| 10 | StartDiagnosticSession | 0x093864 (→fn 0x93858) | NATIVE | — | **RE'd** `kwp_start_diag_session_10_app` |
| 12 | readFreezeFrame? | 0x086534 | NATIVE | — | reg-ctx blocked |
| 14 | clearDiagnosticInformation | 0x09cee8 | NATIVE | — | reg-ctx blocked (10-byte memcpy + flag) |
| 18 | readDTCByStatus | 0x0749e4 | NATIVE | — | reg-ctx blocked (calls DTC helpers) |
| 21 | readDataByLocalId | 0x01ad4c | NATIVE | — | mis-bounded (decodes as thunk+baddata) |
| 22 | readDataByCommonId | 0x06fb30 | NATIVE | — | reg-ctx blocked |
| 27 | **SecurityAccess** | 0x08cce8 (→ `kwp_sa27_precondition`, real crypto `kwp_sa27_level3_handler` 0x84cd4) | NATIVE | 0x1-0xff: **C0x13** | **RE'd** — see SECURITY_ACCESS.md |
| 2e | writeDataByCommonId | 0x0709f8 | NATIVE | 0x1-0xff: C0x13 | reg-ctx blocked |
| 31 | routineControl | 0x0257bc | NATIVE | 0x1-0xcf: C0x01; 0xd0-0xff: C0x26 | reg-ctx blocked (routine/test struct) |
| 33 | requestRoutineResults | 0x0a57f8 | **DATA/cal** | 0x1-0xff: C0x0e | data table (x=0x0100 marker); see note |
| 32 | stopRoutine | 0x024768 | NATIVE | (6 sub ranges, C0x10/0x11/0x28) | reg-ctx blocked |
| 34 | requestDownload | 0x0a4218 | **DATA/cal** | 0x1-0x10: C0x21; 0x11-0xff: C0x20 | data (app-session download is data-driven) |
| 35 | requestUpload | 0x0a53b0 | **DATA/cal** | 0x1-0xff: C0x24 | data; **no decompile** (uncovered) |
| 36 | transferData | 0x08fc1c | NATIVE | 0x1-0xff: C0x24 | reg-ctx blocked |
| 37 | requestTransferExit | 0x0a56e8 | **DATA/cal** | 0x1-0xff: C0x24 | data; **no decompile** (uncovered) |
| 3b | writeDataByLocalId (coding) | 0x0a8e64 | **DATA/cal** | 0x1-0xff: C0x24 | data (cal map descriptor) |
| 82 | stopCommunication | 0x0a9524 | **DATA/cal** | — | data (cal curve + descriptor) |

## Service map — TABLE B (programming session `10 85`)

| SID | svc (KWP) | handler | kind | perm CLASS (sub range) | status |
|----|----|----|----|----|----|
| 10 | StartDiagnosticSession | 0x0929b0 (→fn 0x92950) | NATIVE | — | **RE'd** `kwp_start_session_10` (address range-check 0x400000..0x400800) |
| 1a | readEcuIdentification | 0x06d756 | NATIVE | — | mis-bounded (alt-entry, reg-ctx garbage) |
| 23 | **readMemoryByAddress** | 0x0987f4 (→fn 0x987a4) | NATIVE | — | **RE'd** `kwp_read_mem_23_handler` — SA-gated (see SECURITY_ACCESS.md) |
| 30 | inputOutputControlByLocalId | 0x080046 (→fn 0x80010) | NATIVE | 0x1: C0x13; 0x2-0xff: C0x28 | reg-ctx blocked (actuation/valve math) |
| 31 | routineControl | 0x099020 (→fn 0x98f84) | NATIVE | 0x1-0xcf: C0x01; 0xd0-0xff: C0x26 | **RE'd** `kwp_actuator_test_31_prog` (volatile actuator test, no NVM) |
| 34 | requestDownload | 0x09a964 (in fn 0x9a900) | NATIVE | 0x1-0x10: C0x21; 0x11-0xff: C0x20 | **partial** — flash-SA lockout gate (`kwp_prog_dl_lockout_gate`), entry model open |
| 36 | transferData | 0x09a8c8 (in fn 0x9a844) | NATIVE | 0x1-0xff: C0x24 | partial — transfer-state reset/manager |
| 37 | requestTransferExit | 0x09a944 (in fn 0x9a900) | NATIVE | 0x1-0xff: C0x24 | partial — shares fn 0x9a900 with SID 0x34 |
| 3d | **writeMemoryByAddress** | 0x0987f4 (→fn 0x987a4) | NATIVE | 0x1-0xff: C0x24 | **shares the SID 0x23 handler** (combined read/write-memory) |
| 3e | testerPresent | 0x0aa83c | **DATA/cal** | 0x1-0xff: C0x24 | data (inside meas-channel table 0xa9fcc); likely no-op, session-timer handled |
| 81 | startCommunication | 0x0a8d30 | **DATA/cal** | — | data |
| 82 | stopCommunication | 0x0a8f34 | **DATA/cal** | — | data |
| 83 | accessTimingParameters | 0x0a0f98 | NATIVE | — | reg-ctx blocked (small; copies +8, sets flags) |

> KWP service names are the conventional ISO-14230 assignments as a reading aid; where a handler was
> actually reversed, the "status" column reflects verified behavior, which takes precedence.

## Permission / CLASS table  (`kwp_sid_permission_table` @ 0xae938)

40 records, 4 bytes each `{u8 SID, u8 subLo, u8 subHi, u8 CLASS}`, covering SID 0x24..0x42 (the
services whose access is gated; SIDs below 0x24 and the session/comms SIDs are not in it). A request
`SID sub ...` is matched to the record whose `subLo ≤ sub ≤ subHi`, yielding a **CLASS** that the
dispatcher checks against the current session + SecurityAccess state before invoking the handler.

Observed CLASS values and the services that carry them (CLASS→meaning is partially inferred — the
enforcement function that reads 0xae938 is handler-side, around 0xa57f8+ at 0xa7e1c/0xa8260, and is
in the data-driven path; exact CLASS→(session,SA-bit) decode is **not yet fully traced**):

| CLASS | carried by (SID:sub) | inferred requirement |
|----|----|----|
| 0x07 | 0x25,0x26-range,0x29-0x2f misc | low / public-ish |
| 0x0e | 0x26, 0x33 | — |
| 0x0f | 0x2d | — |
| 0x10/0x11 | 0x32 sub-ranges | routine stop classes |
| 0x13 | **0x27, 0x2e, 0x30(sub1), 0x41** | SecurityAccess-class (0x27 is itself here) |
| 0x14 | 0x2c(sub≤0x40) | — |
| 0x18 | 0x28 | — |
| 0x20/0x21 | 0x34 sub-ranges | download, two tiers (sub≤0x10 vs >0x10) |
| 0x24 | **0x35,0x36,0x37,0x38-0x40,0x42** + many prog-session SIDs | transfer/flash class (the "programming+flash-SA" gate) |
| 0x26 | 0x31(sub≥0xd0) | high routine class |
| 0x28 | 0x2c(sub≥0x41), 0x30(sub≥2), 0x32(sub≥0x21) | — |

Key point for the flash path: **SID 0x23/0x35/0x36/0x37/0x3d all sit in CLASS 0x24 / 0x20-0x21**,
the same tier that bench-testing shows is gated behind the **flash-level SecurityAccess** (SBOOT),
not the coding (level-3) SA — consistent with `SECURITY_ACCESS.md`'s finding that the coding unlock
does not open the memory-read/transfer services.

## Security gates — where they live (cross-ref SECURITY_ACCESS.md)

The gate chain, by function (all NATIVE, all reversed):

1. **Session gate** — `kwp_start_diag_session_10_app` (0x93858, table A SID 0x10) and
   `kwp_start_session_10` (0x92950, table B SID 0x10) select which table is active; the app one
   clears ~session state and sets session-id 0x10; neither touches security cells (confirmed — a
   session change does **not** reset lockout/SA state).
2. **Coding SecurityAccess (level 3)** — `kwp_sa27_precondition` (0x8cce4, the SID-0x27 table-A
   entry; a sensor-plausibility gate, not crypto) → real crypto `kwp_sa27_level3_handler` (0x84cd4):
   `key = seed + delta` (6 valid deltas), sets bits in `sec_access_state` (0x4079e4). **SOLVED.**
3. **Flash/FBL SecurityAccess (level 1)** — `kwp_security_access_sm` (0x8b850) only *records* a grant
   (`security_unlock_set` 0x6e9ec) after a valid key; the seed-gen + key-verify are **SBOOT-side**,
   not in this image. Gated behind the persistent **flash-SA lockout counter** `sa_lockout_counter`
   (0x405e12) + `sa_lock_flag` (0x408500). **OPEN.**
4. **Flash-SA lockout decrement** — function **0x9a900** (container of the prog-session SID 0x34/0x37
   table entries) references and **decrements** `sa_lockout_counter` at 0x9a98c
   (`ldrh; subs #1; strh`), gated by `sa_lock_flag` top bit + `FUN_0009b556`; on the fail path calls
   `FUN_0004f730(0xc)`. **It contains no increment path** — see the correction note in
   SECURITY_ACCESS.md (the earlier "counts the lockout back up over time" description of 0x9a900 is
   not supported by its disassembly).
5. **Access-level read** — `diag_access_level_read` (0x5f372) returns `diag_access_level`
   (0x4059ec[6]), consulted by adaptation/coding handlers.

## Decompile-quality issues found (and fixes)

Three distinct causes degrade the committed decompiles of the diagnostic layer:

1. **Spurious functions from DATA/cal handlerPtrs (≥0xa2000).** `EspServiceTables.java` created
   functions at 9 calibration addresses and they got decompiled into garbage. **Fix:** guard the
   `createFunction` so a record whose `handlerPtr ≥ CODE_HI (0xa2000)` is *not* turned into a
   function (lay a data label / skip instead) — implemented 2026-10-05 in `EspServiceTables.java`.
   This removes `000a57f8.c`, `000a4218.c`, `000a8e64.c`, `000aa83c.c`, `000a8d30.c`, `000a8f34.c`
   (+ the uncovered 0xa53b0/0xa56e8/0xa9524) as code on the next `reproduce.sh`.
2. **Register-context dispatch.** NATIVE handlers are called with their context in registers
   (r4/r5/r6/r7/r12), but Ghidra has no caller to infer it from, so handlers like 0x86534 (SID 12),
   0x24768 (SID 32), 0x257bc (SID 31), 0x6fb30 (SID 22), 0x709f8 (SID 2e), 0x8fc1c (SID 36),
   0x9cee8 (SID 14), 0x749e4 (SID 18) decompile with `unaff_rN`/`in_r12` and are not reliably
   readable. **Fix path (not yet done):** recover the dispatcher's calling convention (which register
   holds request ptr / response ptr / length / context struct) and set a matching custom prototype +
   storage on each handler, so the decompiler folds the register args — this would clean up ~10
   handlers at once. Blocked on locating the dispatcher (see above).
3. **Mis-bounded alt-entries.** Table pointers that are +N alt-entries into a function whose real
   prologue is >0x60 bytes earlier defeat `EspServiceTables.prologueStart`'s back-scan, so a function
   gets created mid-stream and decodes as `thunk_*`/`halt_baddata` — e.g. SID 0x21 (0x1ad4c), SID
   0x1a (0x6d756). **Fix path:** widen/smarten the prologue back-scan, or seed these entries from the
   manifest at their true prologue.

## ASW → SBOOT handoff: the monitor SVC interface

The ASW never directly computes SecurityAccess keys, writes flash, or manages the flash-SA
lockout recovery. All privileged operations trap to SBOOT via ARM **`SVC` (software interrupt)**
instructions — the standard ARM7TDMI supervisor-call mechanism. SBOOT is architecturally
resident (loaded before the ASW; `asw_start_sboot` at 0x8f440 shows the ASW is *launched by*
SBOOT via SVCs `#0x15`/`#0x16`). The ASW marshals parameters into registers and a context
struct (typically pointed to by `r12`), executes `SVC #imm`, and SBOOT's monitor handler
(vector at 0x8 in the ARM exception table, in the SBOOT flash region) dispatches on `imm`.

### SVC encoding — two families

107 total SVC sites in the ASW code region (0x0..0xa2000), using 54 distinct immediates:

1. **Direct (small) SVCs** — immediate < 0x100. These are core monitor lifecycle operations:
   - `SVC #0x13` — **MONITOR_ENTER** (15 sites). Transitions CPU to a privileged mode for the
     next coded operation. Often appears in pairs with a coded SVC.
   - `SVC #0x14` — appears only in `asw_start_sboot` (0x8f440), 3 sites. Possibly a
     "query SBOOT state" or mode-check.
   - `SVC #0x15` — **MONITOR_START** (7 sites). Begins a privileged execution block.
   - `SVC #0x16` — **MONITOR_END** (7 sites). Ends a privileged block / returns to user mode.
   - `SVC #0x17` — 1 site (0x74b74), only in the HECC/NVM manager. Unknown purpose.

2. **Coded SVCs** — immediate ≥ 0x100, all follow the pattern **`code<<8 | 0x10`** (low byte
   always 0x10). The `code` selects the monitor function. 49 distinct codes observed, from
   `code=0x0001` to `code=0x07ff`. These implement flash read/write/erase, NVM management,
   security state queries, and hardware configuration — everything the ASW cannot do in
   unprivileged mode.

### Major SVC-using functions (15 clusters)

| Function | addr | SVCs | Role |
|----|----|----|----|----|
| **Monitor gateway hub** | 0x69c20 | 22 | OS mode init + CPU-mode register save/restore. Bookended by `#0x15`…`#0x16`. Sets up SPSR for each exception mode (IRQ `0xd0`, FIQ `0xd7`, ABT `0xdb`, UND `0xdf`, SVC `0xd3`, SYS `0xd0`). Codes: `0x03`, `0x0505`, `0x0f` (×2), `0xfd`, `0x7f`, `0x3d`, `0x14f`, `0x157`, `0x1ff`, `0x1c7`. |
| **HECC/NVM manager** | 0x74b24 | 24 | CAN controller + NVM block management. Heavy use of `code=0x0780` (×3), `0x07c1` (×2), `0x0020` (×5 — likely NVM page-write), `0x07e1`, `0x06e7`, `0x06c0`, `0x07d3`, `0x0100`, `0x0001`, `0x01fd`, `0x01c1`, `0x0307`. The `0x07xx` codes cluster = HECC peripheral config. |
| **SA crypto helper** | 0x85154 | 4 | Codes `0x03de` (×2), `0x03fe`, `0x05fb` — likely SBOOT crypto / random-number calls (SA seed generation). Near the SA handler cluster. |
| **Session handoff** | 0x869a0 | 3 | Code `0x001e` + `#0x15`/`#0x16` bookends — transitions control to SBOOT for session descent (`10 85` → programming). |
| **Flash driver** | 0x89350 | 12 | Flash write/erase burst with key-schedule pattern (0x11111111…0xaaaaaaaa written to `r12+4..+0x20`). Codes: `0x03fc` (×2), `0x04fc`, `0x07ae`, `0x07d1`, `0x00ec`, `0x03ec`, `0x046c`, `0x0600` (×2), `0x01f8`, `0x063f`. |
| **SBOOT state query** | 0x8e648 | 3 | Codes `0x00ff`, `0x0081` + one `#0x13`. Reads SBOOT-managed state. |
| **`asw_start_sboot`** | 0x8f428 | 14 | ASW entry point, launched by SBOOT. Three `#0x14`+`#0x15`+`#0x16` blocks (mode bring-up for IRQ/FIQ/SVC stacks) + `0x00ff` + `0x007f`. |
| **Flash state machine** | 0x95334 | 2 | Code `0x01ff` — flash-operation completion check. |
| **NVM sector ops** | 0x96d48 | 4 | Code `0x0010` (×3) + `0x0006` — NVM sector read/status. |
| **HECC mailbox config** | 0x97a20 | 4 | Codes `0x07ff`, `0x07f0`, `0x07fe`, `0x07c0` — HECC CAN mailbox register writes (these are in the `0xfff7e800` MMIO range that the monitor gates). |
| **Diag buffer setup** | 0x98160 | 2 | Two `#0x13` calls — diagnostic transport buffer init. |
| **Flash SA/transfer gate** | 0x99094 | 7 | Codes `0x00ff` (×3), `0x0001`, `0x0003` (×2), `0x003f` — flash-SA state machine and transfer authorization. |
| **Flash validate** | 0x99bcc | 2 | Codes `0x00ff` + `0x06ff` — signature/checksum validation. |
| **Flash erase** | 0x9b258 | 3 | Codes `0x00d0`, `0x05b9`, `0x0007` — flash sector erase. |
| **Misc** | 0x9e364 | 1 | Code `0x07ff` — isolated HECC config. |

### What this means for the security analysis

The SVC interface confirms that:
- **Flash-SA key verification lives entirely in SBOOT.** The ASW's `kwp_security_access_sm`
  (0x8b850) only records the *result* of a SBOOT-side verify; it never sees the seed, key, or
  algorithm. The `0x03de`/`0x03fe`/`0x05fb` codes at 0x85154 are the ASW asking SBOOT for
  crypto services (seed generation), not computing them locally.
- **Flash writes go through a multi-SVC burst** (0x89350). The key-schedule pattern
  (`0x11111111`…`0xaaaaaaaa` in `r12+4..+0x20`) is likely an unlock sequence that SBOOT
  validates before enabling the flash controller's write-enable — similar to TI's FSM
  (Flash State Machine) key sequence on TMS470.
- **The `10 85` programming-session descent** is a physical handoff: the session-handoff function
  (0x869a0) calls `SVC #0x001e` bracketed by `#0x15`/`#0x16`, which transfers control to SBOOT's
  own KWP dispatcher. After this point, a **different** service table (SBOOT-resident, not in this
  image) handles `27 01`/`27 02` and the flash transfer services. The ASW's `kwp_service_table_b`
  only handles the *pre-descent* programming session.
- **NVM/EEPROM management** (the persistent flash-SA lockout counter, calibration storage) is
  entirely SBOOT-gated via the `0x0020` / `0x0010` family of SVC codes. The ASW cannot directly
  increment or reset the lockout counter — it can only *read* it via monitor queries and
  *decrement* it on its side (0x9a98c), with the persistent store managed by SBOOT.
- **HECC (CAN controller) configuration** uses dedicated SVC codes (`0x07xx` family). The CAN
  mailbox registers at `0xfff7e800`+ are likely in a monitor-protected MPU region; the ASW
  configures them only through SBOOT mediation.

### Implication for avenue 2 (code-execution via diagnostic vuln)

A code-exec primitive in the ASW (e.g., via a transport-buffer overflow) would execute at the
ASW's privilege level, which **cannot directly read SBOOT flash or write to flash**. However,
it *can* invoke any SVC — including the flash-read and NVM-read codes. A small payload could:
1. Use `SVC code=0x0010` (NVM sector read) to dump the SBOOT flash region.
2. Use the flash-driver SVCs (0x89350's pattern) to write arbitrary data to flash sectors.
3. Use `SVC code=0x00ff` to query/manipulate flash-SA state.

This means code-exec in ASW context is **sufficient** to dump SBOOT and bypass flash-SA, even
though the ASW itself doesn't have direct flash/NVM access. The transport buffer at
`0x4050e8` (multi-frame data landing at `+0x10b`) is the primary target for a bounds-checking
vulnerability — see the section below.

## Diagnostic handlers with user-controlled read/write

These are the handlers where the diagnostic client controls memory addresses, data content, or
execution targets — i.e., the attack surface for avenue 2 (code-execution or memory-dump via
diagnostic protocol).

### SID 0x23 / 0x3d — readMemoryByAddress / writeMemoryByAddress (shared handler 0x987a4)

- **Table B only** (programming session `10 85`). Both share the exact same handler entry 0x987f4
  (→fn 0x987a4).
- **Permission CLASS 0x24** (SID 0x3d) / **0x13** (SID 0x23) — flash-SA gated. Without the
  flash-SA grant, both return NRC 0x90 (security/session required), confirmed on bench.
- **If SA were granted:** the handler sets up a read/write operation from/to the address and
  length in the request. The length is clamped to 0xff (1 byte field, `0x40801a >> 4`, cap 0xff).
  The address comes from the request body — the handler itself does not appear to do
  additional bounds checking beyond what the dispatcher/CLASS enforcement provides, meaning it
  would be an **arbitrary memory read/write primitive** (within the length cap) once SA is
  cleared. This is the primary post-SA target for memory dumping.
- **Probing value:** HIGH (if SA is ever solved). Direct memory read = dump SBOOT. Direct memory
  write = patch code / inject payload.

### SID 0x10 (prog) — StartDiagnosticSession / download-target setup (0x92950)

- **Table B** (programming session). The prog-session `10` handler does more than session init:
  it sets up a **download target address** from the request body.
- **Bounds check present:** validates address in range `0x400000..0x400800`, 4-byte aligned. The
  base (0x400000 = `PTR_DAT_000929e4`) and limit (+0x800) are hardcoded. Requests outside this
  window → NRC 0x42.
- **The 0x400000..0x400800 range** is RAM (TMS470 internal SRAM starts at 0x400000). The handler
  writes the validated address to `0x4084bc` and `0x40905c`, which are then consumed by the
  `transferData` (SID 0x36, handler 0x9a844) and `requestDownload` (SID 0x34) flows.
- **Bounds check also verifies `addr + length ≤ 0x400800`** (the `puVar5 + *(int*)(puVar1+2) <= puVar3`
  check at line 39 of the decompile). Address + transfer size must fit within the 2KB window.
- **Probing value:** MEDIUM. The bounds check is tight (2KB window in RAM), but the check at
  decompile line 39 (`puVar5 + *(int*)(puVar1+2) <= puVar3`) reads the length as a **signed int**.
  If a large user-supplied length is treated as negative in the comparison, `addr + negative`
  wraps below 0x400800 and passes — but the downstream transfer might use it as unsigned,
  allowing writes beyond the 2KB window. The length comes from request bytes at +0x10e/+0x10f/+0x110
  (3 user-controlled bytes forming 3 of the 4 bytes of the int, offset 4 of the struct potentially
  uninitialized). This service is NOT SA-gated (no CLASS entry for SID 0x10) — it runs without
  any SecurityAccess, making it reachable without solving the flash SA. However, the download
  target is in SRAM (0x400000+), ~3.4 KB away from `diag_access_level` and ~13 KB from
  `sa_lockout_counter` — reaching security cells would require a very large overflow.

### SID 0x34 / 0x37 — requestDownload / requestTransferExit (0x9a900)

- **Table B** (programming session). Both land mid-function in `kwp_prog_dl_lockout_gate`.
- **Permission CLASS 0x20/0x21** (SID 0x34), **0x24** (SID 0x37) — flash-SA gated.
- The handler gates on the flash-SA lockout counter and then dispatches to `FUN_00097e3e`
  (the actual download setup) or `FUN_00097d90` (transfer-exit cleanup). The download target
  address was pre-validated by the SID 0x10 handler above.
- **Probing value:** LOW without SA. The CLASS gate blocks this before the handler runs.

### SID 0x36 — transferData (0x9a844)

- **Table B**, **CLASS 0x24** — flash-SA gated.
- The handler resets the transfer state machine: clears ~20 fields in the transfer context struct.
  It does NOT directly accept user data — the actual data transfer path is downstream (likely
  in the SEG2-dispatched data-driven engine or a called sub).
- **Probing value:** LOW. State-reset function, not a data-sink.

### SID 0x31 (prog) — routineControl / actuator test (0x98f84)

- **Table B**, **CLASS 0x01** (sub 0x01..0xcf) / **0x26** (sub 0xd0..0xff).
- The handler dispatches on sub 0/1/2/3 to test-timing parameter writes. It is volatile
  (no NVM writes) and does not directly accept user memory addresses. However, the sub-0
  path writes to a fixed struct, and subs 1/2/3 set timing parameters that could affect
  physical actuators.
- **Probing value:** LOW for code-exec. Relevant for ECU-internal state manipulation only.

### Transport buffer (0x4050e8) — the best avenue-2 target

The TP2.0 transport layer reassembles multi-frame KWP requests into `transport_channel_buf`
at 0x4050e8. The per-frame data lands at offset `+0x10b`. The key question is whether the
**total reassembled length** is bounds-checked against the buffer's allocated size. If the
buffer is, say, 0x240 bytes (the `+0x22f` state field suggests at least that), and the
transport layer trusts the KWP length byte, a request claiming >0x240 bytes of payload could
overflow into adjacent RAM. The fields after the buffer include session state, security state
cells, and function pointers (the dispatcher's context) — a classic stack-smash target.

**Status (2026-10-05):** the transport reassembly function is **NOT in the main code region**.
All 44 literal-pool references to `transport_channel_buf` (0x4050e8) in the main code
(0x0..0xa2000) are *consumers* of already-reassembled data — they read from the buffer to
handle channel setup, KWP dispatch, and responses. None performs the actual frame-to-buffer
copy. The TP2.0 config descriptors at 0xa43f4 (in the cal region) point to **SEG2** code
(above 0xbb045). The reassembly engine — which copies CAN payload bytes into `+0x10b`
onwards, manages the sequence counter, and sets the `+0x22f` completion state — almost
certainly lives in SEG2 alongside the data-driven KWP handlers. **Bounds-check status:
UNKNOWN** until SEG2 is decompiled. Buffer size estimate: struct is ≥0x230 bytes, payload
area (+0x10b..+0x22e) is ~292 bytes; a TP2.0 multi-frame transfer >292 bytes could overflow
IF the reassembly engine doesn't check total length against buffer capacity. This makes SEG2
decompilation the **single highest-priority next step** for both the service-handler and
code-exec analyses.

## Next steps

1. **Decompile SEG2** (0xbb045+, VMA = file_offset+3) — now the **single highest-priority** step.
   SEG2 contains THREE critical things that are currently uncovered:
   (a) The **TP2.0 transport reassembly engine** (the function that copies CAN frame payloads into
   `transport_channel_buf` +0x10b; config descriptors at 0xa43f4 point here). Need to determine
   whether it bounds-checks total reassembled length against buffer capacity (~292 byte payload
   area) — a length bug = code-exec without SA (avenue 2).
   (b) The **KWP descriptor stubs** (0xbd3c8..0xbda74) — the real handlers for the 9 DATA/cal
   services (app-session download/upload/transfer 0x34/0x35/0x37, coding-write 0x3b, etc.).
   (c) Likely the **central KWP dispatcher** and CLASS→(session,SA-bit) enforcement that reads
   0xae938 — needed to recover the register calling convention and unblock ~10 reg-ctx handlers.
   `EspSeg2.java` already partially handles SEG2; extend it to cover the full descriptor+transport
   code range and add entries to the manifest for `DecompileAll`.
2. **Locate the central dispatcher** (jump-table island 0x12000–0x14000 and/or SEG2) to recover the
   register calling convention and unblock the reg-ctx handlers (decompile-quality cause #2).
3. Finish the reg-ctx NATIVE handlers once #2 lands (SIDs 12/14/18/22/2e/31/32/36 app, 30/83 prog).
4. **Map the SVC code space** — correlate the 49 coded SVC immediates to TI TMS470 flash-state-machine
   operations and HECC register writes using SPNU197e (HECC) and SPNU243 (flash/MSM) docs.

## Reproduce the raw tables

```python
import struct
fw = open("firmware/8R0907379BG_0030.bin","rb").read()
u8=lambda o:fw[o]; u16=lambda o:struct.unpack(">H",fw[o:o+2])[0]; u32=lambda o:struct.unpack(">I",fw[o:o+4])[0]
def svc(base,n):   # 12-byte records {SID,flags,u16 x,u32 handler,u32 descr}
    for i in range(n):
        o=base+12*i; print(hex(u8(o)), hex(u8(o+1)), hex(u16(o+2)), hex(u32(o+4)), hex(u32(o+8)))
svc(0xb4be4,17)    # table A (app)
svc(0xb4d80,13)    # table B (prog)
# perm table: 4-byte {SID,subLo,subHi,CLASS} @0xae938, 40 records
```
