# ESP8 8R0907379BG — KWP2000 session & service map (all 4 diagnostic sessions)

Per-session diagnostic capability matrix. Companion to `KWP_SERVICES.md` (per-handler RE detail,
SVC interface, attack surface) and `SECURITY_ACCESS.md` (SA algorithms, flash sequence, bench
tools). Protocol is **TP2.0 + KWP2000** — see `SECURITY_ACCESS.md` §1 for transport/wiring.

Addresses are firmware VMAs (load base 0; file offset == VMA for the main image).

---

## 1. Session architecture

Four diagnostic sessions, entered via SID `0x10` (StartDiagnosticSession) with the session id as
the subfunction byte. Each session ORs a unique bit into a **session flags byte** at RAM
`0x405316` (`transport_channel_buf + 0x22e`). The session state machine lives in
`kwp_security_access_sm` (`0x8b850`) — despite its name, it handles session transitions for all
four sessions via internal opcodes, not just SecurityAccess.

### Session flag bits

| Session | Wire req | Internal opcode | Flag bit ORed | Entry conditions |
|---------|----------|-----------------|---------------|------------------|
| **0x83** | `10 83` | `−0x7d` (0x83) | `0x01` (bit 0) | **Unrestricted** — no SA required, no prior session, no precondition gate. Clears +0x22e, calls `FUN_000925b8(0,1)` (timer/flag set), ORs 0x01. |
| **0x85** | `10 85` | `−0x7b` (0x85) | `0x04` (bit 2) | Requires operational CAN traffic (see `SECURITY_ACCESS.md` §"operational gate"). Clears +0x22e, ORs 0x04, writes `0xaa005500` to `sec_unlock_marker`, calls `security_unlock_set(1)`, clears `sa_lock_flag`. **Hands off to SBOOT** (`sboot_session_handoff_site` 0x869a0 via `SVC #0x001e`). |
| **0x86** | `10 86` | `−0x7a` (0x86) | `0x08` (bit 3) | Requires coding SA level 3 (`sec_access_state` bit `0x20000000` = key `seed+0x2909`). If bit not set → **silent reject** (no NRC, function returns without setting any flag). On success: clears that SA bit (one-shot consumption), ORs 0x08. |
| **0x89** | `10 89` | `−0x77` (0x89) | `0x10` (bit 4) | **Unrestricted** — default/application session. ORs 0x10 directly. |

### Session state machine (`+0x22f`)

The byte at `transport_channel_buf + 0x22f` (RAM `0x405317`) tracks the KWP session state:

| Value | Meaning |
|-------|---------|
| `0x00` | Idle — waiting for a session request |
| `0x02` | Response sent — a positive response was dispatched |
| `0x03` | Lockout — SA lockout active (flash SA attempts exhausted) |
| `0x04` | Grant — session transition in progress; the flag-OR and handler calls execute in this state |

### Session entry in `kwp_security_access_sm` (0x8b850)

When `+0x22f == 4` (grant state), the function dispatches on the internal opcode at `+0x10a`:

- **0x83 path:** Clears `+0x22e` to 0. If `*DAT_0008b9c8 != 0` (a DTC-reporting flag), calls
  `diag_dtc_event_report(0x10, 0, 0)` — session 0x83 entry can trigger a DTC event (event id
  0x10). Then calls `FUN_000925b8(0, 1)` — a timer/flag function that checks a free-running
  counter (`FUN_00001628`) against a stored value, and if `param_2 == 1` (which it is here), sets a
  control flag `*PTR_DAT_00092608 = 1` unconditionally. This appears to be an "enable measurement"
  or "enable calibration access" gate. Finally ORs bit 0x01 into the session flags.

- **0x85 path:** Clears `+0x22e` to 0. ORs bit 0x04. Writes the magic marker `0xaa005500` to
  `sec_unlock_marker` (0x40bffc). Calls `security_unlock_set(1)` to set the security-unlock bit.
  Clears `sa_lock_flag` (0x408500) to 0. Returns early (does not fall through to the common flag-OR
  code — the flag-OR is inline). This path is the **SBOOT handoff** — after this, the SBOOT's own
  KWP dispatcher takes over.

- **0x86 path:** Tests `sec_access_state` (0x4079e4) bit 29 (`0x20000000`). If 0 → returns
  immediately (silent reject, no flag set, no response). If 1 → clears that bit (one-shot SA
  consumption), ORs bit 0x08. The consumed bit is the one set by coding SA key `seed+0x2909` — so
  session 0x86 requires a fresh level-3 SA unlock each time.

- **0x89 path:** ORs bit 0x10 directly. No conditions.

When `+0x22f == 2` (response-sent state):
- **0x83, 0x89:** Copies a positive-response template via `resp_frame_copy`, sets `+0x22f = 2`.
  For 0x86, if the SA bit is not set, writes NRC 0x33 (`securityAccessDenied`) at `+0x7`.
- **0x85:** Additional condition checks — tests 6 halfwords (precondition flags related to
  operational state/CAN communication), tests `sa_lockout_counter` (0x405e12) and
  `sa_lock_flag` (0x408500). If lockout counter > 0 and lock flag != 0 → decrements counter,
  sets `+0x22f = 3` (lockout state). If conditions pass → sets `sa_lock_flag = 0xff`, copies
  positive response.

---

## 2. Service dispatch — which table serves which session

| Session | Service dispatch table | Reason |
|---------|----------------------|--------|
| **0x89** (app) | **Table A** (`kwp_service_table_a` @ `0xb4be4`, 17 SIDs) | Default/application table. Confirmed by handler `kwp_start_diag_session_10_app` (0x93858) being the table A SID 0x10 entry. |
| **0x85** (prog) | **Table B** (`kwp_service_table_b` @ `0xb4d80`, 13 SIDs) | Programming table. After SBOOT handoff, a **separate SBOOT-resident table** (not in this image) takes over — see `SECURITY_ACCESS.md` §"SBOOT bootloader service map". |
| **0x83** | **Table A** (inferred) | Session 0x83 does NOT trigger the SBOOT handoff (no `security_unlock_set`, no marker write). No code path selects table B without the 0x85 transition. Session 0x83 uses table A with its flag bit 0x01 enabling additional capabilities via per-handler flag checks. |
| **0x86** | **Table A** (inferred) | Same reasoning — no SBOOT handoff, no table B selection. Session 0x86 uses table A with flag bit 0x08 (plus the consumed SA bit) enabling additional capabilities. |

**Key finding:** Sessions 0x83 and 0x86 do NOT have their own service tables. They use the same
17-SID table A as session 0x89, but the **session flag bits** they set unlock handler-level
permission gates that the default session 0x89 (flag bit 0x10) does not satisfy.

---

## 3. Service availability matrix

### Table A — application sessions (0x83, 0x86, 0x89)

All three sessions dispatch through table A. The "Availability" column shows which sessions can
actually USE the service, based on the CLASS permission requirements and session flag checks.

| SID | KWP service | Handler | Kind | CLASS | Available in sessions | SA required? |
|-----|-------------|---------|------|-------|-----------------------|-------------|
| `10` | StartDiagnosticSession | `kwp_start_diag_session_10_app` 0x93858 | NATIVE | — | 0x83, 0x86, 0x89 | No |
| `12` | ReadFreezeFrame | 0x86534 | NATIVE | — | 0x83, 0x86, 0x89 | No |
| `14` | ClearDiagnosticInformation | 0x9cee8 | NATIVE | — | 0x83, 0x86, 0x89 | No |
| `18` | ReadDTCByStatus | 0x749e4 | NATIVE | — | 0x83, 0x86, 0x89 | No |
| `21` | ReadDataByLocalId | 0x1ad4c | NATIVE | 0x13 (0x20) | 0x83, 0x86, 0x89 | CLASS-gated |
| `22` | ReadDataByCommonId | 0x6fb30 | NATIVE | 0x13 (0x22) | 0x83, 0x86, 0x89 | CLASS-gated |
| `27` | **SecurityAccess** | `kwp_sa27_precondition` 0x8cce8 → `kwp_sa27_level3_handler` 0x84cd4 | NATIVE | 0x13 (0x27) | 0x83, 0x86, 0x89 | Self-gating (IS the SA) |
| `2e` | WriteDataByCommonId | 0x709f8 | NATIVE | 0x13 (0x2e) | 0x83, 0x86, 0x89 | CLASS-gated |
| `31` | RoutineControl | 0x257bc | NATIVE | 0x01 (sub≤0xcf) / 0x26 (sub≥0xd0) | 0x83, 0x86, 0x89 | CLASS-gated |
| `32` | StopRoutine | 0x24768 | NATIVE | 0x10/0x11/0x28 (sub ranges) | 0x83, 0x86, 0x89 | CLASS-gated |
| `33` | RequestRoutineResults | 0xa57f8 | DATA/cal | 0x0e | 0x83, 0x86, 0x89 | CLASS-gated |
| `34` | RequestDownload | 0xa4218 | DATA/cal | 0x21 (sub≤0x10) / 0x20 (sub>0x10) | 0x83, 0x86, 0x89 | CLASS-gated |
| `35` | RequestUpload | 0xa53b0 | DATA/cal | 0x24 | 0x83, 0x86, 0x89 | Flash-SA gated |
| `36` | TransferData | 0x8fc1c | NATIVE | 0x24 | 0x83, 0x86, 0x89 | Flash-SA gated |
| `37` | RequestTransferExit | 0xa56e8 | DATA/cal | 0x24 | 0x83, 0x86, 0x89 | Flash-SA gated |
| `3b` | WriteDataByLocalId (coding) | 0xa8e64 | DATA/cal | 0x24 | 0x83, 0x86, 0x89 | Flash-SA gated |
| `82` | StopCommunication | 0xa9524 | DATA/cal | — | 0x83, 0x86, 0x89 | No |

### Table B — programming session (0x85)

| SID | KWP service | Handler | Kind | CLASS | SA required? |
|-----|-------------|---------|------|-------|-------------|
| `10` | StartDiagnosticSession | `kwp_start_session_10` 0x92950 | NATIVE | — | No |
| `1a` | ReadEcuIdentification | 0x6d756 | NATIVE | 0x18 (0x1a sub≤0x7f) / 0x17 (sub≥0x80) | CLASS-gated |
| `23` | **ReadMemoryByAddress** | `kwp_read_mem_23_handler` 0x987a4 | NATIVE | 0x13 | Flash-SA gated |
| `30` | InputOutputControlByLocalId | 0x80010 | NATIVE | 0x13 (sub 1) / 0x28 (sub≥2) | CLASS-gated |
| `31` | RoutineControl | `kwp_actuator_test_31_prog` 0x98f84 | NATIVE | 0x01 (sub≤0xcf) / 0x26 (sub≥0xd0) | CLASS-gated |
| `34` | RequestDownload | `kwp_prog_dl_lockout_gate` 0x9a900 | NATIVE | 0x21 (sub≤0x10) / 0x20 (sub>0x10) | Flash-SA gated |
| `36` | TransferData | `kwp_transfer_state_reset` 0x9a844 | NATIVE | 0x24 | Flash-SA gated |
| `37` | RequestTransferExit | 0x9a900 (shared with SID 0x34) | NATIVE | 0x24 | Flash-SA gated |
| `3d` | **WriteMemoryByAddress** | 0x987a4 (shared with SID 0x23) | NATIVE | 0x24 | Flash-SA gated |
| `3e` | TesterPresent | 0xaa83c | DATA/cal | 0x24 | Session-timer handled |
| `81` | StartCommunication | 0xa8d30 | DATA/cal | — | No |
| `82` | StopCommunication | 0xa8f34 | DATA/cal | — | No |
| `83` | AccessTimingParameters | 0xa0f98 | NATIVE | — | No |

### SBOOT bootloader services (after `10 85` + flash SA unlock)

The SBOOT has its own dispatcher (not in this image). Confirmed via ODIS capture and bench probing:

| SID | Service | Status |
|-----|---------|--------|
| `10` | DiagnosticSession | `50 85 00` — programming session confirmed |
| `22` | ReadDataByIdentifier | Works with 2-byte DIDs (F17C, F187, F189, F191, F197, F1A3, F1AA, F1DF) |
| `27` | SecurityAccess | Level 1 only — **SGO SA2 bytecode** (solved, see `SECURITY_ACCESS.md`) |
| `31` | RoutineControl | Routine 0xC4 = erase, 0xC5 = checksum verify |
| `33` | WriteMemoryByAddress | `subFnNotSupported` (needs specific params) |
| `34` | RequestDownload | Works after erase; `34 00 <addr3> 00 <len3>` format |
| `36` | TransferData | Works during active download |
| `37` | RequestTransferExit | Works after transfer complete |
| `23` | ReadMemoryByAddress | **NOT available** — NRC 0x90 |
| `35` | RequestUpload | **NOT available** — NRC 0x90 |

---

## 4. Session 0x83 — the calibration/measurement session

### What session 0x83 IS

Session 0x83 is a **calibration/measurement access session** — an engineering/development session
that enables measurement channel access and calibration data manipulation that the default
application session 0x89 does not allow. It requires no SecurityAccess to enter — `10 83`
succeeds unconditionally (same as `10 89`).

### What session 0x83 ENABLES that 0x89 does not

The session flag byte at `0x405316` is checked by at least 6 code sites (literal-pool references
at `0x1c430`, `0x1c83c`, `0x1d0c0`, `0x8a7bc`, `0x9c294`, `0x9d864`). The references cluster in
two functional areas:

#### A. Calibration/measurement channel access (0x9c204)

Function at **0x9c204** is the key session-0x83-gated handler. It specifically requires session
0x83 **OR** 0x86 — NOT 0x89. The check uses:

```
(flags | (flags >> 3)) & 1
```

This evaluates to 1 if **bit 0** (session 0x83, flag 0x01) OR **bit 3** (session 0x86, flag 0x08)
is set. Session 0x89's bit 4 (flag 0x10) does NOT satisfy this check.

The function:
- Gates on `sec_access_state` bit 25 (`0x02000000`) — this is SA key `seed+0x75fb` (the third
  alternate SA key, not the primary `+0x2909`). So full access requires **session 0x83 (or 0x86)
  AND SA level 3 with key `seed+0x75fb`**.
- Handles DID-like calibration/measurement channel parameters: reads `+0x10b`/`+0x10c` as a 16-bit
  channel ID, `+0x110` as a parameter count (capped at 0x14 = 20), `+0x108` must equal 0x08.
- On success: writes the channel ID into the control struct, sets control flag bits (`|= 0x10`),
  sets `+0x22f = 2` (response sent).
- On permission failure: copies an NRC response template.

#### B. Coding/adaptation channel handlers (0x1bf30–0x1d0c0 cluster)

Three references to `0x405316` in the coding/adaptation handler cluster:
- `0x1c430` — in `FUN_0001c438`, a coding channel handler that dispatches ops 0xb8/0xb9/0xba.
  Tests the session flags to determine which coding operations are allowed.
- `0x1c83c` — in `kwp_adaptation_access_check` / nearby code. Tests session flags for
  adaptation-level gating.
- `0x1d0c0` — in the coding data dispatch area. Further session-level checks for write operations.

These handlers implement the **adaptation/coding channel protocol** (KWP ops 0xb8 open channel,
0xb9 read next record, 0xba write record). The session flag checks likely gate write access to
coding channels — session 0x83 may unlock write access to channels that are read-only in session
0x89.

#### C. Diagnostic response state reset (0x8a7bc)

`diag_response_state_reset` (0x8a628) references the session flags area. It reads `0x405314` (2
bytes before the flags byte) — likely part of the same transport channel struct. The function
resets diagnostic response state and is called by 9 diagnostic handlers after sending a response.
The session flag check here determines post-response behavior (timing, state transitions).

#### D. RoutineResults / internal opcode 0xFB (0x9d864)

Function at **0x9d7e4** handles internal opcode `0xFB` (routineResults). It also gates on the
session flags (`*DAT_0009d864 >> 9`), checking whether specific session flag bits allow access
to routine result data. The `>> 8 & 1` check tests bit 8 of the flags word — which in the
context of the 16-bit read at the flags address corresponds to a different flag than the session
bits (possibly a "routine active" or "response pending" indicator).

### Session 0x83 entry side-effect: `FUN_000925b8(0, 1)`

On session 0x83 entry, the state machine calls `FUN_000925b8(0, 1)`:

```c
// param_1=0, param_2=1
// Reads free-running timer via FUN_00001628
// Compares against a stored value at PTR_DAT_00092614
// If they differ (not a duplicate entry): sets *PTR_DAT_00092608 = 1
```

This sets a control flag to 1 — likely an "enable calibration/measurement mode" gate that
downstream measurement channel handlers check before allowing data access. The flag is NOT set
by session 0x89 entry (`kwp_start_diag_session_10_app` does not call this function).

### Session 0x83 summary

| Aspect | Detail |
|--------|--------|
| Entry | `10 83` → `50 83` — unrestricted, no SA required |
| Flag bit | 0x01 at `0x405316` |
| Service table | Table A (same 17 SIDs as 0x89) |
| Unique capabilities | Measurement/calibration channel access (fn 0x9c204), additional coding/adaptation write gates |
| SA key for full access | `seed + 0x75fb` (SA level 3, alternate key 3, sets `sec_access_state` bit 25) |
| Relationship to 0x86 | Shares the `(flags \| flags>>3) & 1` gate — both satisfy it. Session 0x86 additionally requires primary SA (`+0x2909`) to enter. |
| Bench status | **NOT YET TESTED** — `esp_unlock.py` includes `10 83` in its probe loop but no bench results are documented |

---

## 5. Session 0x86 — the coding session

Session 0x86 is the coding/adaptation write session, gated behind coding SA level 3 (key
`seed+0x2909`). It shares capabilities with session 0x83 (both satisfy the `(flags | flags>>3) &
1` check) but requires SA to enter.

| Aspect | Detail |
|--------|--------|
| Entry | Requires `sec_access_state` bit 29 (`0x20000000`) — set by coding SA key `seed+0x2909`. **One-shot:** the bit is cleared on entry. |
| Flag bit | 0x08 at `0x405316` |
| Service table | Table A (same 17 SIDs as 0x89) |
| Unique over 0x89 | Same measurement/calibration gates as 0x83 plus whatever bit-3-specific handlers exist |
| Confirmed on bench | `10 86` → `50 86` after SA unlock (confirmed in `SECURITY_ACCESS.md`). Opens `21` measurement blocks. |

---

## 6. Permission / CLASS system

### Full CLASS table (`kwp_sid_permission_table` @ 0xae8f8)

78 records, 4 bytes each: `{u8 SID, u8 subLo, u8 subHi, u8 CLASS}`. Covers SIDs 0x19–0x50.
A KWP request `SID sub …` is matched to the record where `subLo ≤ sub ≤ subHi`, yielding a
**CLASS** that the dispatcher checks against the current session + SA state.

The permission table applies to **internal opcodes** (the remapped SID values used within the
dispatcher), not the raw wire SIDs directly. SIDs without a table entry (0x10, 0x12, 0x14, 0x18,
0x81, 0x82) are either unrestricted or have session-level gating only.

| SID range | Sub range | CLASS | Services in this CLASS |
|-----------|-----------|-------|----------------------|
| 0x19 | 0x01–0x50 | **0x13** | |
| 0x19 | 0x51–0xff | 0x0a | |
| 0x1a | 0x01–0x7f | 0x18 | ReadEcuIdentification (low range) |
| 0x1a | 0x80–0xff | 0x17 | ReadEcuIdentification (high range) |
| 0x1b | any | 0x0b | |
| 0x1c | any | 0x1f | |
| 0x1d | any | 0x0a | |
| 0x1e | any | **0x13** | |
| 0x1f | any | **0x13** | |
| 0x20 | any | **0x13** | |
| 0x21 | any | **0x13** | ReadDataByLocalId |
| 0x22 | 0x01–0x60 | **0x13** | ReadDataByCommonId |
| 0x22 | 0x61–0xff | 0x16 | ReadDataByCommonId (high range) |
| 0x23 | any | **0x13** | **ReadMemoryByAddress** |
| 0x24 | any | **0x13** | |
| 0x25 | any | 0x07 | |
| 0x26 | any | 0x0e | |
| 0x27 | any | **0x13** | **SecurityAccess** (self-referential) |
| 0x28 | any | 0x18 | |
| 0x29–0x2b | any | 0x07 | |
| 0x2c | 0x01–0x40 | 0x14 | |
| 0x2c | 0x41–0xff | 0x07 | |
| 0x2d | any | 0x0f | |
| 0x2e | any | **0x13** | WriteDataByCommonId |
| 0x2f | any | 0x07 | |
| 0x30 | sub 0x01 | **0x13** | InputOutputControl (sub 1) |
| 0x30 | sub≥0x02 | 0x28 | InputOutputControl (sub 2+) |
| 0x31 | 0x01–0xcf | **0x01** | RoutineControl (standard routines) |
| 0x31 | 0xd0–0xff | **0x26** | RoutineControl (high routines — erase, etc.) |
| 0x32 | 0x01–0x02 | 0x11 | StopRoutine |
| 0x32 | 0x03–0x14 | 0x10 | StopRoutine |
| 0x32 | 0x15 | 0x11 | StopRoutine |
| 0x32 | 0x16–0x20 | 0x10 | StopRoutine |
| 0x32 | 0x21–0xff | 0x28 | StopRoutine (high range) |
| 0x33 | any | 0x0e | RequestRoutineResults |
| 0x34 | 0x01–0x10 | **0x21** | RequestDownload (low addr range) |
| 0x34 | 0x11–0xff | **0x20** | RequestDownload (high addr range) |
| 0x35 | any | **0x24** | RequestUpload |
| 0x36 | any | **0x24** | TransferData |
| 0x37 | any | **0x24** | RequestTransferExit |
| 0x38–0x40 | any | **0x24** | (reserved transfer/flash SIDs) |
| 0x41 | any | **0x13** | |
| 0x42–0x45 | any | **0x24** | |
| 0x46 | 0x01–0x0f | **0x00** | (public) |
| 0x46 | 0x10–0x3f | 0x0a | |
| 0x46 | 0x40–0xff | **0x26** | |
| 0x47 | 0x01–0x3e | 0x0a | |
| 0x47 | 0x3f–0x40 | 0x25 | |
| 0x47 | 0x41–0xff | **0x24** | |
| 0x48–0x49 | any | 0x0c | |
| 0x4a | 0x01–0x4f | 0x0c | |
| 0x4a | 0x50–0xff | 0x27 | |
| 0x4b–0x4c | any | 0x0c | |
| 0x4d | 0x01–0x3f | 0x0d | |
| 0x4d | 0x40–0x4f | 0x0c | |
| 0x4d | 0x50–0xff | 0x27 | |
| 0x4e | any | 0x07 | |
| 0x50 | any | 0x23 | |

### CLASS tiers (inferred from behavior + structure)

The CLASS value indexes a **requirements table** (not yet located — lives in SEG2 or the
undecompiled dispatcher). Based on bench behavior and code analysis:

| CLASS | Inferred requirement | Evidence |
|-------|---------------------|----------|
| **0x00** | Unrestricted / public | SID 0x46 sub 0x01–0x0f |
| **0x01** | Minimal session gate | RoutineControl standard range — available without SA |
| **0x07** | Low / public-ish | Many "read" subfunctions |
| **0x0a–0x0c** | Medium / read-level | ECU identification, DTC-related |
| **0x0e–0x0f** | Routine results / mid-tier | RequestRoutineResults, SID 0x2d |
| **0x10/0x11** | Routine stop classes | StopRoutine sub ranges |
| **0x13** | **SA-class** | SecurityAccess, ReadMemory, WriteData, IOControl sub1. Bench-confirmed: SID 0x23 returns NRC 0x90 (`securityAccessDenied`) without SA. This is the shared "requires some level of SA" gate. |
| **0x14** | Medium-write | SID 0x2c (sub≤0x40) |
| **0x16–0x18** | Read-with-restrictions | ECU ident high range, SID 0x28 |
| **0x20/0x21** | Download tiers | RequestDownload — two sub-ranges, flash-SA gated |
| **0x23** | Transfer-extended | SID 0x50 |
| **0x24** | **Flash/transfer class** | Upload, transfer, transfer-exit, write-memory, coding-write, timing. The "programming + flash-SA" gate — bench-confirmed: these services return NRC 0x90 without flash-SA unlock. |
| **0x25** | Special mid-tier | SID 0x47 sub 0x3f–0x40 |
| **0x26** | High routine class | RoutineControl sub≥0xd0 (erase routines), SID 0x46 high range |
| **0x27** | High DTC/measurement | SID 0x4a/0x4d high ranges |
| **0x28** | IO control + routine | IOControl sub≥2, StopRoutine high range |

### CLASS enforcement — WHERE it lives (open gap)

The CLASS→(session, SA-bit) enforcement function is **not yet located**. The permission table at
`0xae8f8` is consumed by the KWP dispatcher, which uses the CLASS value to gate handler execution.
The enforcement logic almost certainly resides in the **SEG2 code cluster** (0xbb045+) and/or the
**jump-table island** (0x12000–0x14000), neither of which is fully decompiled. The descriptor
pointers in each service table record (all pointing into 0xbd3c8–0xbda74) likely include the
permission check as part of the service dispatch stub.

---

## 7. Differences between the 4 sessions — summary

| Capability | 0x89 (app) | 0x83 (cal) | 0x86 (coding) | 0x85 (prog) |
|-----------|------------|------------|---------------|-------------|
| **Entry requirement** | None | None | Coding SA (`+0x2909`) | Operational CAN |
| **Service table** | Table A (17 SIDs) | Table A (17 SIDs) | Table A (17 SIDs) | Table B (13 SIDs) → SBOOT |
| **DTC read/clear** | Yes | Yes | Yes | No (not in table B) |
| **ReadDataByLocalId (21)** | Yes (CLASS 0x13) | Yes (CLASS 0x13) | Yes (CLASS 0x13) | No |
| **ReadDataByCommonId (22)** | Yes (CLASS 0x13) | Yes (CLASS 0x13) | Yes (CLASS 0x13) | No |
| **SecurityAccess (27)** | Yes (level 3) | Yes (level 3) | Yes (level 3) | No (SBOOT handles 27) |
| **Measurement channels** | **No** (flag check fails) | **Yes** (flag bit 0x01) | **Yes** (flag bit 0x08) | No |
| **Calibration write** | **No** | Likely **Yes** (with SA `+0x75fb`) | Likely **Yes** | No |
| **Coding channels** | Limited | Extended access | Extended access | No |
| **ReadMemoryByAddress (23)** | Not in table A | Not in table A | Not in table A | Yes (flash-SA gated) |
| **WriteMemoryByAddress (3d)** | Not in table A | Not in table A | Not in table A | Yes (flash-SA gated) |
| **RequestDownload (34)** | DATA/cal only | DATA/cal only | DATA/cal only | Yes (flash-SA gated) |
| **RoutineControl (31)** | Yes (CLASS 0x01/0x26) | Yes (CLASS 0x01/0x26) | Yes (CLASS 0x01/0x26) | Yes — volatile actuator test |
| **IOControl (30)** | Not in table A | Not in table A | Not in table A | Yes (CLASS 0x13/0x28) |
| **ECU identification (1a)** | Not in table A | Not in table A | Not in table A | Yes (CLASS 0x17/0x18) |
| **Erase/flash/transfer** | Flash-SA gated | Flash-SA gated | Flash-SA gated | Flash-SA gated |
| **TesterPresent (3e)** | Not in table A | Not in table A | Not in table A | DATA/cal (session timer) |

### What each session is FOR

- **0x89 (application):** Default session. DTC reading/clearing, standard measurement blocks
  (via `21`), coding SA, session transitions. No memory access, no calibration channels.

- **0x83 (calibration):** Engineering/development session. Enables measurement/calibration channel
  access (fn 0x9c204) and extended coding channel operations — the capabilities an ECU calibration
  tool (ETAS INCA, Vector CANape) would use for online parameter tuning. Unrestricted entry makes
  it accessible without any prior SA unlock, but full calibration write access additionally
  requires SA key `seed+0x75fb`.

- **0x86 (coding):** Post-SA coding session. Requires the primary coding SA key (`seed+0x2909`).
  Enables the same measurement/calibration gates as 0x83 (both satisfy the `(flags|flags>>3)&1`
  check). Used by diagnostic tools after SA unlock for parameter adaptation and coding writes.
  The SA bit is consumed on entry — re-entering 0x86 requires a fresh SA unlock.

- **0x85 (programming):** Flash programming session. Requires operational CAN. Hands off to SBOOT
  for flash-level operations (erase, download, transfer). The SBOOT dispatcher presents a
  different service set (no `23`/`35`, adds `22`/`31`/`33`). The flash-level SA (SGO SA2) is
  handled entirely by SBOOT.

---

## 8. Bench test plan for session 0x83

Session 0x83 has NOT been tested on the bench. Recommended test sequence:

```
# 1. Enter session 0x83 (should be unconditional)
10 83  -> expect 50 83

# 2. Probe measurement block access (should work in 0x83, fails in 0x89)
21 01  -> compare response vs same request in session 0x89
21 02
21 03
21 0f
21 10

# 3. Test calibration channel access (fn 0x9c204 path)
#    Requires SA key seed+0x75fb first:
27 03  -> seed
27 04 <seed+0x75fb>  -> expect 67 04 (unlocks sec_access_state bit 25)
#    Then try a measurement channel read (exact DID/channel format TBD from fn 0x9c204)

# 4. Test session transition: 0x83 -> 0x86
#    In session 0x83, do SA key seed+0x2909, then 10 86
27 03  -> seed
27 04 <seed+0x2909>  -> 67 04
10 86  -> expect 50 86

# 5. Verify 0x83-specific capabilities vs 0x89 baseline
#    Run identical requests in both sessions and diff the responses
```

---

## 9. Adaptation channel protocol analysis (2026-10-12)

### Handler chain (SIDs 0xB8-0xBB)

Main dispatch: `kwp_adaptation_handler` @0x1d7a8. 16-entry × 8-byte channel table at flash 0xB8D98.
Request: `B8 <hi> <lo>` → channel_id = lo + hi × 256 (16-bit). Special: channel 0x0FFF when
`+0x22f == 4` → `security_unlock_set(0)` (SA reset, not unlock).

Sub-handlers after table match:
- `kwp_coding_channel_handler` @0x1bf30 — 6-state protocol, 13-entry table @0xB91E4
- `kwp_coding_data_dispatch` @0x1c128 — sequential 4-byte records from fixed base 0xB9048 (max 68)
- `FUN_0001c438` — variant, fixed base 0xB8ED4 with 0xFFFFFFFF sentinel wrap
- `kwp_adaptation_access_check` @0x1c6b0 — access-level gate (reads `diag_access_level_read()`)
- `FUN_0009c204` — calibration channel handler, gated on cal SA + session 0x83/0x86

**All handlers read from fixed flash tables. No user-controllable memory addressing.**

### Identified channel IDs (from firmware table @0xB8D98)

Known: 0x002C (44 = workshop code), 0x0109, 0x0278, 0x0A09, 0x0C09, 0x0D22, 0x2B40, 0x3EE0,
0x420A, 0x4D09, 0x52D2, 0x5A09, 0x8040, 0xADD2, 0xD2D2, 0xD5D2. Bench probe (`adapt_probe.py`)
will verify which respond positively and what data they contain.

## 10. Open gaps

1. **CLASS→(session,SA-bit) enforcement table** — the exact mapping from CLASS values to required
   session flags + SA bits. Lives in SEG2 (0xbb045+), not yet decompiled. Without this, the
   "Available in sessions" column in §3 is inferred from flag checks and bench behavior, not
   proven for every CLASS.

2. **Session 0x83 bench verification** — calibration SA (seed+0x75fb) proven, but the measurement
   channel behavior and calibration write capabilities via adaptation channels are unconfirmed.
   Bench probe `adapt_probe.py` prepared to test.

3. **The `FUN_000925b8` control flag** — what downstream handlers check the flag set by session
   0x83 entry. Likely gates the measurement channel dispatcher but the consumers are not traced.

4. **Coding channel session-flag checks** — the three references in the 0x1bf30–0x1d0c0 cluster
   need closer analysis to determine exactly which coding/adaptation operations are gated by
   which session flag bits.

5. **Internal opcode mapping** — how wire SIDs map to the internal opcodes used by the dispatcher
   and permission table. The 127-entry jump table at 0x12dd4 handles opcodes 0x00–0x7E; session
   IDs (0x83/0x85/0x86/0x89, all > 0x7E) are handled by `kwp_security_access_sm` before/outside
   the jump table.
