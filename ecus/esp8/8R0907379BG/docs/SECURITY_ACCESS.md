# ESP8 8R0907379BG — diagnostics, SecurityAccess & flash-security status (current)

This is the **single current source of truth** for diagnostics/SecurityAccess/flash-security on
this module. It replaces `HANDOFF_uds_dump.md`, `uds_read_primitive.md`, `HANDOFF_seedkey_trace.md`,
`BENCH_SESSION2_PROMPT.md` and `BENCH_HANDOFF.md` (all retired — git history has them if needed).
Those docs were written while probing **UDS**, which is the wrong protocol for this module; most of
their specific conclusions ("0x23 doesn't exist", "SecurityAccess level 01 only", "SA2 key already
extracted") are superseded below. Read `CLAUDE.md` first for repo conventions.

## Protocol: VAG TP2.0 + KWP2000, NOT UDS

Every UDS/ISO-TP probe (0x6b4, 0x713, full 0x600-0x7ff sweep) is silent on this module because it
simply isn't UDS. The real diagnostics are **TP2.0 transport + KWP2000**, confirmed working:
- Channel setup: `03 C0 00 10 00 03 01` → CAN id `0x200`; ECU replies on `0x203`: `00 d0 00 03 a3 04 01`.
- Channel direction: we **TX→0x4a3**, we **RX←0x300**.
- Params: send `A0 0F 8A FF 32 FF` the instant the first `0xD0` arrives → ECU `A1 0f 8a ff 4a ff`.
- `10 89` (StartDiagnosticSession) → `50 89` POSITIVE.
- Tool: `bench/tp20_kwp.py` (`TP20KWP` class — multi-frame TX, `responsePending` handling).

Bench wiring: SM2-Pro/T38a, module B (vehicle Antriebs/ESP-CAN, the diag bus) = pins **26 CAN-H /
14 CAN-L**, 500 kbps. Module A (private sensor/chassis bus) = pins 37/24 — a bench on 37/24 cannot
reach diagnostics. Ignition switch ON powers term-15.

## The operational gate — SOLVED (bisected 2026-10-04)

A quiet bench bus gives `conditionsNotCorrect` on `10 85` (ProgrammingSession) and `14 FF FF`. This
is **not** a wiring/addressing/protocol problem — it's an operational-context check: the module
needs to see *some* CAN traffic.

**Minimal fix (bench-bisected from 225 ids down to 1):** transmit **any single accepted-id frame**
(RX filter @`0xafae0`) periodically — e.g. id `0x200` at ~20-50 Hz, counter+CRC-8/J1850 body — and
`10 85` returns `50 85`. This is a low bar ("CAN communication active"), not full ComM-operational.
Tool: `bench/emu_unlock.py` (`Stim` class takes `--ids <hex>`; defaults to the full 225-id set at a
busload-safe rate if omitted).

**Full ComM-operational** (module broadcasts its own ESP_01/02/05/08 etc.) is a *higher*, separate
bar, NOT needed just to reach `10 85`: the module needs the NM container — IpduM container CAN-id
**0x36E** (MEDIUM confidence; absent from the generic RX filter, so may be module-A-side), contained
sub-PDU header `0x0600`, 4-byte NM word with a valid node-id at **byte index 2** (table `0xbd83c`:
`{0x5f,0x98,0x99,0x9a,0x4a,0xd4}`), control byte (index 3) `& 0xD6 == 0`. Chain:
`transport_rx_process 0x689e4` → `nm_msg_process 0x40950` → NM word `0x408f10` →
`comm_nm_main 0x6a71c` sets `comm_enable 0x40944c=1` → `can_tx_scheduler 0x5bfc` operational. Tool:
`bench/nm_operational.py` (untested on bench; builds the frame with the corrected byte layout).

**Session state gotcha:** a successful `10 85` descent leaves the module in "state B" — `10 89`/
`10 85` then answer `subFnNotSupported` until the next **power-cycle** (back to "state A"). Several
bench scripts need a fresh power-cycle per run for this reason.

## KWP service dispatch — two tables, verified live on bench

> **Full service map + handler RE status now in `docs/KWP_SERVICES.md`** (authoritative for the
> service surface). Key additions there (2026-10-05): the `handlerPtr` field is dual-natured —
> `< 0xa2000` = native code handler, `≥ 0xa2000` = pointer to a cal descriptor dispatched by a
> generic data-driven engine via the record's SEG2 `descriptorPtr` (so 9 of the 30 "handlers" the
> old pipeline carved were mis-decoded calibration data); full permission/CLASS table decode; and
> the per-SID reversed/blocked status.

`kwp_service_table_a` (`0xb4be4`, 17 records) — **application session** (`10 89`). SIDs: 10, 12, 14,
18, 21, 22, 27 (→ precondition stub, see below), 2e, 31, 32, 33, 34, 35, 36, 37, 3b, 82. No `0x23`.

`kwp_service_table_b` (`0xb4d80`, 13 records) — **programming session** (`10 85`). SIDs: 10, 1a,
**23** (ReadMemoryByAddress), 30, 31, 34, 36, 37, 3d, 3e, 81, 82, 83. No `0x27`.

Record format (both tables, recovered by `EspServiceTables.java`, wired into `reproduce.sh` step
05b2): 12 bytes `{u8 SID, u8 flags, u16 x, u32 handlerPtr (Thumb/ARM via bit0), u32 descriptorPtr}`.

Permission table `kwp_sid_permission_table` (`0xae938`, 4-byte records `{SID, subLo, subHi, CLASS}`):
`SID 0x23 → CLASS 0x13`, the **same class as SID 0x27** (SecurityAccess). Confirmed **bench-live**:
in the programming-session context, `23 <addr> <len>` returns `7F 23 90` (security/session required)
— the read primitive exists and is recognized, but is SA-gated. (The old `uds_read_primitive.md`
conclusion "0x23 doesn't exist" was reached while hunting it as a UDS service; it's real, just KWP.)

## SecurityAccess — TWO SEPARATE systems on this module

### 1. Coding/adaptation SA — LEVEL 3 — **SOLVED, working**

In the application session (`10 89`), level 1 (`27 01/02`) is `subFnNotSupported` — **level 3**
(`27 03`/`27 04`) is the real one, handled by **`FUN_00084cd4`** (Thumb), which IS in the ASW image
(RE'd + emulator-verified):

```
key = (seed + 0x2909) & 0xFFFFFFFF      # seed and key are 32-bit BIG-ENDIAN on the wire
```

Seed is per-session random (RAM `0x4079b0`, source `FUN_0000113e` free-running timer), constant
within a session across repeated `27 03`. The handler actually accepts **6 valid keys** (seed +
different constant), each setting a different bit of `sec_access_state` (`0x4079e4`):

| delta | grants bit | notes |
|---|---|---|
| `+0x2909` | `0x20000000` | primary; also the session-`0x86` gate bit |
| `+0x564f` | `0x00000200` | |
| `+0x75fb` | `0x02000000` | |
| `+0x9ce8` | `0x01000000` | |
| `+0xefc2` | `0x00000400` | |
| `+0xfe10` | `0x04000000` | |

Wrong key → `7F 27 35 invalidKey`; the level-3 handler (`FUN_00084cd4`) resets `sa_level3_state`
(`0x408f26`) to 0. (RE correction 2026-10-05: the handler does NOT itself touch `sa_lockout_counter`
`0x405e12` — that volatile 3-try counter is decrement-only, written (decremented) by
`kwp_security_access_sm` `0x8b850` on the programming/`0x85` path and ALSO by `0x9a900`
(`kwp_prog_dl_lockout_gate`, the prog-session SID 0x34/0x37 download/transfer-exit function) at
`0x9a98c` — guarded by `sa_lock_flag` `0x408500` + `FUN_0009b556`; it still **resets on
power-cycle** via .data/.bss init. **RE correction 2026-10-05:** neither `0x8b850` nor `0x9a900`
contains any *increment* of `0x405e12` — the earlier "counted back up over time by the delay timer
`FUN_0009a900`" description is NOT supported by that function's disassembly (it only decrements). The
bench-observed time-delay *recovery* of the flash-SA lockout is therefore not accounted for by any
ASW code path we can see and is most likely SBOOT/NVM-side (open). Earlier text here also conflated
the level-3 state reset with the `0x405e12` countdown.) Confirmed live: `27 03`→seed,
`27 04 <seed+0x2909>`→ `67 04` **UNLOCKED**. This opens session `10 86` (confirmed `50 86`) and `21 ReadDataByLocalId`
measurement blocks (ids `01,02,03,0f,10`) — but **not** `23`/`35`/`2C` (tested; see below).

Tool: `bench/esp_unlock.py`.

### 2. Flash/FBL SA — level 1 — **SBOOT-side, open problem**

Reached only post-`10 85` descent + TP2.0 reconnect (the channel drops when the module hands off
toward the boot loader). In that context `27 01` gives a real changing seed (high byte always
`0xFD/FE/FF` — a timer-idiom seed-gen signature). `27 02` is **state-gated**: sent with any
intervening frame it's `subFnNotSupported`; sent **immediately** after `27 01` with no frame in
between, it does a real compare (`invalidKey` on wrong keys — proven, see below).

**Proven NOT in the ASW image** (RE, cross-checked two ways): the post-descent context answers a
*different* `27` subfunction-support set than either KWP table (table A has no `0x27` entry beyond
the precondition stub at level distinct from this; table B has no `0x27` at all) — a single image
can't present an inverted support set for the same transport buffer, so a **separate dispatcher**
(SBOOT) is answering. Confirmed independently: `asw_start_sboot` (`0x8f440`) shows the ASW is
launched *by* SBOOT via monitor SVCs (`#0x13-0x16`, `#0xff10`), and SBOOT is architecturally
resident/separate (standard for this MCU family).

**Candidates tested and REJECTED** (clean `invalidKey`, so the compare mechanism is real and
working — these are genuinely wrong keys, not a harness bug):
- SGO SA2 (see below), all 4 seed/key byte-order combinations (BE/BE, BE/LE, LE/BE, LE/LE)
- `rot5` login family (`key = 5×{MSB-rotate; if carry, XOR 0x5FBD5DBD}`), big-endian
- Additive `seed + 0x2909` and `seed + 0x564f` (the coding-SA deltas, in case shared)

**Untested / remaining candidates:** the other 4 coding-SA deltas (`+0x75fb/+0x9ce8/+0xefc2/+0xfe10`),
`shift5`/single-XOR login variants, `ecu_azx`'s `seed+0x11170`. **CAUTION: the flash-SA lockout
(`7F 27 36 exceedNumberOfAttempts`) is NVM-PERSISTENT, not volatile like the coding one** — it
tripped after ~2 wrong keys and did not clear on power-cycle (clears on a time delay instead, which
appeared to lengthen with repeated attempts). **STATUS (2026-10-05): a further candidate sweep
tripped it again, and this time a power-cycle did not restore access to the FBL context at all
(3 reconnect attempts failed outright) — the lockout may now be escalated/longer-duration than
before. Before testing any further candidate, confirm with `bench/fbl_check.py` (seed-request
only, never burns an attempt) that the lockout has actually cleared.**
**(2026-10-05 follow-up, `fbl_check.py`, minimal 1-msg stimulus):** `10 89`→`50 89` but `10 85`→
`7F 10 22 conditionsNotCorrect` — the module now refuses the ProgrammingSession *descent itself*, so
`27 01` never reaches the FBL context (`7F 27 12 subFnNotSupported`, i.e. still in the app session).
The escalated flash-SA lockout appears to also block the `10 85` handoff to SBOOT, not just the key
compare. Net: FBL is unreachable right now; leave the module powered down for an extended cool-off
(hours) and re-probe with `fbl_check.py` before any further flash-SA work.
Test candidates sparingly,
one at a time, with waits between — do not loop automated retries against it. Tool: `bench/fbl_sa2.py`
(single back-to-back
attempt), `bench/fbl_keytest.py` (candidate list, one per invocation via `--start`/`--n 1`),
`bench/fbl_check.py` (lockout-state probe — seed-only, never burns an attempt).

**Where the SGO's SA2 fits — RESOLVED (2026-10-05, cross-community research):** the OEM flash
container (`8R0907379BG_0030.sgo`) embeds a 24-byte SA2 bytecode program at offset `0x1bb`
(identical across all 4 sibling SGOs — genuine, not a template): `ADD 0x974c58ab; BCC+7;
EOR 0xfedcba98; BRA+5; EOR 0x98765432; FOR 11 {RSR}; FINISH`. Our VM implementation
(`bench/sa2_unlock.py`, `Sa2SeedKey`) is **validated against 3 independent public test vectors**
(bri3d/sa2_seed_key format, incl. one using the `0x5FBD5DBD` constant) — it is correct. All 4
byte-order variants were rejected by the live flash-SA compare.

**The SGO's SA2 bytecode is NOT expected to work for our flash-SA — this is now understood, not an
open question.** Cross-referencing community knowledge (nefmoto, bri3d/sa2_seed_key, icanhack.nl,
BtB paper) yields a clear architectural picture:

- **For engine/powertrain ECUs (MED17, Simos, ME7, etc.):** SA2 bytecode from the SGO/ODX **IS**
  the flash-level SecurityAccess algorithm. ODIS reads the SA2 script and computes the key to
  unlock a ProgrammingSession. d3irb (bri3d, author of `sa2_seed_key`) confirms: "it is the
  universal seed/key authentication mechanism for flashing pretty much all VAG control units since
  the early 2000s" (nefmoto topic 18663). HelperD (nefmoto topic 20977) confirmed the SA2 bytes
  are even embedded verbatim in the MED17 firmware binary. The icanhack.nl ECU Flashing knowledge
  base documents this as the standard: "The script travels inside the flash file… anyone who has
  the flashdaten has the algorithm."

- **For Bosch ABS/ESP modules: the SBOOT uses a SEPARATE, proprietary algorithm NOT in the SGO.**
  nefmoto's "Bosch ABS Boot Mode" thread (topic 14951, 2018–2025, 31k+ reads) confirms the
  community has **never cracked flash-level SA on any Bosch ABS module via diagnostics**.
  jochen_145: "Even for OEM, ABS/ESP are completely BLACK-BOX." treadshuffle (Apr 2023): "The
  specifics of the algo are in an external library called 'SecAcc.dll' which isn't included with
  the RaceABS installation nor with Modas… its distribution is severely limited to only those who
  are authorized." The SA2 in the SGO may exist for ODIS tooling compatibility (so ODIS doesn't
  error on missing SA2 data), but the actual SBOOT flash-SA is independent.
  **(2026-10-05 update, ODIS-E investigation — avenue 9 below):** `SecAcc.dll` does NOT ship with
  ODIS-E either. ODIS-E v17.0.1 has TWO distinct server-side security systems: (a) **SFD (Schutz
  Fahrzeug Diagnose)** — a 2019/2020+ coding/adaptation protection system for MQB/MQB Evo modules
  (Gateway, Central Electronics, etc.) that uses time-limited tokens from VW's online backend, and
  (b) a **flash-security D3 server mechanism** (`flash\d3server\` package) for flash-level SA key
  computation. Neither exposes a local algorithm. The VWMCD database for AU37X (Q5) has NO KWP2000
  brake BasisVariant at all — only UDS. The `libGWSK32.dll` in VWMCD is gateway-only. All ODIS
  class files are encrypted with VW's custom `VaudesSmardlang` ClassLoader.
  **(2026-10-05 update, community research — avenue 10 below):** SFD is confirmed by Ross-Tech
  (wiki.ross-tech.com) and vagprogramming.com as **coding/adaptation protection only** — it
  replaces the old 5-digit login code for coding access, not flash-level SecurityAccess. SFD
  applies to modules like Gateway (19), Central Electronics (09), Instrument Cluster (17), etc.
  The `SecurityAccessSFD*` classes in ODIS handle this coding gate. The `flash\d3server\` package
  is the separate flash-SA server mechanism. For pre-SFD engine ECUs, ODIS used SA2 bytecode in
  ODX/FRF containers for flash SA — but Bosch ABS/ESP modules do NOT use SA2 (confirmed earlier).
  The Bosch ABS flash-SA algorithm is proprietary SBOOT-side, with key computation server-side
  via the D3 infrastructure. No community source has ever published a Bosch ABS flash-SA algo.

- **Even on modern Simos18 (where SA2 works for CBOOT-level flash), the SBOOT has its own
  completely separate authentication** — RSA-encrypted Mersenne Twister challenge, documented by
  bri3d in `github.com/bri3d/Simos18_SBOOT`. SA2 is what the Customer Bootloader (CBOOT) uses
  during normal UDS programming sessions; the Supplier Bootloader (SBOOT) has its own
  manufacturer-level seed/key. bri3d also notes: "Bosch use a similar PWM 'break-in' mechanism
  and overall architecture, but a **totally different command protocol which looks more like KWP**"
  — which matches our ESP8 exactly (KWP2000, not UDS).

- **Implication for our ESP8:** our `10 85` descent hands off to SBOOT (proven: different SID
  support set, separate dispatcher). The flash-SA `27 01/02` in this SBOOT context is a Bosch
  proprietary algorithm, almost certainly NOT SA2-based, NOT any simple additive scheme, and NOT
  publicly documented. The SGO's SA2 rejection is expected behavior. Remaining additive-delta
  candidates (avenue 1) are deprioritized — the SBOOT algo is likely structurally different from
  any of the known SA families (additive, rot5, shift5, LFSR). **Best remaining avenues are
  hardware/exploit paths: JTAG dump (avenue 3), fault injection (avenue 5), or diagnostic
  code-execution (avenue 2).**

  New lead from bri3d's SBOOT docs: Bosch SBOOTs may have a **PWM "break-in" mechanism** similar
  to Continental's — two square-wave signals on specific pins at boot that force the ECU into the
  SBOOT command shell. On TMS470, the GPTA timing comparator is the likely peripheral. If such a
  break-in exists on our ESP8, it would provide direct SBOOT-shell access without needing to
  solve the flash-SA at all (the SBOOT shell would have its own, separate authentication, but
  it's a different attack surface). Worth investigating the bench cable's `CNF1/BOOT1/BOOT2`
  leads as candidate break-in pins.

### Does the coding (level-3) unlock open the memory-read/flash-write services?

**Tested, NO.** With the coding SA unlocked: `23`/`35`/`2C` in the app session all refuse (`35`→
`7F 35 80`; `2C`→`7F 2C 11 serviceNotSupported`; `23` not in table A at all). `34`/`35` in the
programming session also `7F .. 80` (wrong-session-ish) even with the coding grant active — the
transfer/read services are gated by the **flash SA**, not the coding one. `kwp_security_access_sm`
(`0x8b850`) — which records a session-0x85 grant via `security_unlock_set` — only runs that grant
**after a valid flash-SA key**, not on plain session entry (checked and ruled out; see git history
of `esp8-progsession-bypass` memory note for the disproof).

## Flash validation — RSA-1024, confirmed (signature_analysis.md, unchanged, still current)

Both signed regions (`SIG1`=ASW `[0,0xbd424)`, `SIG2`=CAL `[0xd20c1,0x133be9)`) carry 128-byte
RSA-1024 signatures (`Bosch.CSDE.BEG_VAG.01.004` scheme). **Cannot be forged/recomputed** — the
private key isn't in this image (only in the bootloader, which we don't have). A patched image is
only flashable if verification can be bypassed. Four routes, all needing SBOOT/CBOOT: (1) check
whether CBOOT verifies RSA only at flash time while the runtime jump checks only a CRC — if so, a
patched ASW with a corrected runtime CRC might boot despite an invalid signature; (2) patch the
CBOOT verify branch; (3) an SBOOT exploit to write flash bypassing enforcement; (4) voltage-glitch
the verify branch at flash time. See `signature_analysis.md` for the full descriptor format.

## Bottom line / where this is blocked

Both the **memory dump** and **patched-firmware flash** paths are gated behind the **flash-level
SecurityAccess**, whose seed-gen + key-verify live in **SBOOT** — a separate flash region not
present in our dump (the SGO container only ships ASW+CAL). This is not a wall we're declaring
closed — see below for what's still open — but every pure-software/bench-diagnostic avenue from
*this* image converges on needing SBOOT:
- Diagnostic read (`23`) is SA-gated behind the flash SA, not the coding SA.
- The coding-SA unlock (which we have) doesn't reach the transfer services.
- The flash-SA algorithm isn't in the ASW to reverse statically or emulate.

**Open avenues** (not yet exhausted):
1. **Finish the flash-SA candidate sweep** (remaining additive deltas + login variants) — slow due
   to the persistent lockout, one candidate at a time with waits.
2. **Code-execution via a diagnostic vulnerability** — the published technique (Garcia et al.,
   "Beneath the Bonnet: a Breakdown of Diagnostic Security") for VAG/Ford/Fiat ECUs: once
   authenticated at the *download* level, `RequestDownload` a small secondary bootloader into RAM,
   `TransferData` it, then `RoutineControl` (routine id varies by OEM, e.g. `0x301`/`0x304`) to jump
   to it — gives arbitrary code execution that can read/transmit all flash including SBOOT. Also
   worth checking the TP2.0/KWP2000 reassembly buffer (`transport_channel_buf 0x4050e8`, multi-frame
   data landing at `+0x10b`) for a length/bounds bug that could give code-exec with **no SA at all**.
   That paper also notes some VAG units reset their SA lockout timer on `ECUReset`/session-toggle —
   NOT used here by deliberate choice (see repo history around 2026-10-04 for why).
   **(2026-10-05 update):** the SVC interface analysis (see `KWP_SERVICES.md` "ASW → SBOOT handoff")
   confirms that ASW-level code-exec IS sufficient to dump SBOOT: the ASW invokes monitor SVCs for
   all flash/NVM operations, and a payload running at ASW privilege can call those same SVCs — e.g.
   `SVC code=0x0010` (NVM sector read) to dump SBOOT flash, or the flash-driver pattern at 0x89350
   to write arbitrary sectors. No need to break out of the ASW's privilege level; the SVC interface
   itself is the escalation path. Key targets for avenue 2: (a) the TP2.0 reassembly buffer overflow
   (transport reassembly function, upstream of `transport_rx_process` 0x689e4 — analysis in progress),
   (b) the SID 0x10 prog handler (0x92950) signed-int bounds check on the download-target length
   (no SA required, but the write window is only 2KB in SRAM 0x400000..0x400800).
3. **Hardware SBOOT dump via JTAG — MCU identified (2026-10-05, web research).** The MCU is almost
   certainly a **TI TMS470R1x** (big-endian **ARM7TDMI = ARMv4T**+Thumb core; Ghidra language refined
   `v5t`→`v4t` 2026-10-05 to match — see `RE_findings.md` "MCU / hardware platform"):
   our own independently-discovered CAN controller addresses `0xfff7e800`/`0xfff7ea00`
   (now relabeled `hecc_module_a`/`b` — the cell is **TI HECC**, not FlexCAN, confirmed by TI SPNU197e)
   are an **exact match** to TI's documented HECC1/HECC2 control-frame base addresses (with mailbox RAM
   at `0xfff7e400`/`e600`). `TMS470R1B1M` (1MB flash, dual HECC 32-mailbox, 144-pin LQFP, ARM7TDMI, 1.8V) is the
   closest part-number match found so far. Explains the "unmarked bare die" in the teardown photos —
   TMS470 is supplied to Tier-1s as bare wafer die for chip-on-board hybrid assembly; it was never
   packaged, so there were never markings to lose. Commercial tools exist for exactly this chip
   family (CarProTool's "TMS470 Programmer", JTAG via test points on the PCB, supports several
   TMS470R1Vxxx/R1Axxx part numbers) — confirming this is a known, reachable target in the field,
   not a dead end.

   **Security mechanism (TI "Memory Security Module" / MSM, reference guide SPNU243):**
   - A 128-bit password per protected zone (up to 2 zones), stored in flash/ROM at a part-specific
     fixed address (in the device-specific datasheet, not yet pinned to our exact part). Unlock
     ("password match flow", PMF) = read the 4 password words, write them back to the `MSMKEY0-3`
     registers.
   - **If the password is all-1s (erased-flash default), the device auto-unsecures** — simply reading
     it brings the device out of secure mode, no actual secret needed.
   - Even while secured, **JTAG can still halt the CPU, and load+run code in any *unprotected* RAM
     or flash bank** — the MSM only blocks direct JTAG *reads* of the protected zone's content, not
     CPU execution generally. Per TI's own security-scenario table: code *executing from inside* the
     secured region (which is exactly what SBOOT does on every normal boot) has full read access to
     its own secured memory — only a *direct JTAG peek* of that memory is blocked. So even a
     correctly-secured chip is plausibly still crackable by loading a small RAM stub via JTAG that
     redirects execution into the secured region (or hooks it) and exfiltrates bytes via a
     JTAG-visible RAM buffer or CAN — the same idea as the diagnostic code-exec technique below, just
     entered through JTAG/CPU-halt instead of a diagnostic-protocol bug. **Security Mode 2** (a
     *separate*, harsher setting — a 64-bit "JSM" key that permanently disables JTAG access to the
     CPU entirely, no RAM-stub workaround possible) is the one real dead end; whether Bosch enabled
     Mode 1 only (likely, for factory test/rework) or Mode 2 is unknown until a probe is attempted.
   - **HAZARD, read before any JTAG attempt or any flash write near the password's bank:** per TI,
     if the 128-bit password reads as **all-0s**, the device becomes **permanently and irrecoverably
     locked** on the next reset (TI's own words: "the device will be permanently locked and can no
     longer be debugged or reprogrammed"). This is in fact TI's *documented, intentional* method for
     an OEM to permanently seal a production part before shipping — so there is a real chance Bosch
     did exactly this, in which case JTAG recovery of the secured zone is not possible via password
     and the RAM-stub/code-redirect approach above would be the only remaining avenue. This also
     means: **never write to the flash bank containing the MSM password with anything other than all-1s
     or a deliberate legitimate password** — doing so and then letting the device reset could brick it.
   - Next concrete step: identify the exact TMS470R1x part number (package pin count / flash size vs.
     our ~1.26 MB ASW+CAL image should narrow it) to get its datasheet's MSM password address and
     memory-bank-to-MSM-zone assignment, and locate JTAG (TCK/TMS/TDI/TDO/`nTRST`/`nRESET`, standard
     ARM 20-pin or 10-pin layout) bond-pads/test-points on the bare die/substrate — CarProTool's
     published per-part pinout PDFs (e.g. `tms470r1vf689.pdf`) are a reference starting point even
     though they're for packaged parts, not this bare-die assembly.
   **Firmware-fingerprint corroboration (2026-10-05, independent of the web research above):** a
   full-corpus decompile pass confirms the TI TMS470 ARM7TDMI identification from the binary itself —
   (a) build string `"ERCOSEK V4.1.17k TMS_470 (c)ETAS Jul 12 2006"` @file 0xa4d5b (ETAS OSEK, TI
   TMS470 port); (b) CAN register semantics are TI **HECC** (16-byte mailboxes, `CANTA@+0x10 /
   CANRMP@+0x18 / CANRML@+0x1C` bit-per-object) at `0xFFF7E400/E600`, NOT FlexCAN (the old
   `flexcan_*` symbol names are mislabeled) and NOT D_CAN; (c) core is **ARM7TDMI/ARMv4T** — pervasive
   BX interwork veneers (no BLX) and zero CP15/cache/MMU code (an ARM9 would show CP15). The reset
   vector @0x0 is a self-loop, so the ASW is entered *by* SBOOT. See `variant.conf` for the full
   evidence list. The no-cache/no-MMU/3-stage-pipeline ARM7TDMI is the key fact for avenue 5 below.

5. **Fault injection (voltage/clock glitching) — primary hardware avenue if JTAG pads are
   potting-blocked (2026-10-05).** Because chip-off and likely JTAG-pad access are blocked by the
   potted bare-die hybrid, glitching is the live FI path. The ARM7TDMI core is unusually favorable:
   **no cache, no MMU, no branch prediction, 3-stage pipeline → deterministic instruction timing and
   repeatable fault windows**, far easier than a Cortex-R/TriCore. Targets, in SBOOT (reached via
   monitor `SVC #0x13–0x16/#0xFF10`, `asw_start_sboot` 0x8f440): (a) the flash readout-protection /
   TI-MSM check at boot — glitch it to drop to an unsecured state and dump flash (incl. SBOOT + the
   flash-SA key algo + the RSA/validation logic); (b) the SBOOT `27 02` key-compare branch — glitch
   the compare to force a valid-key verdict without the secret. Prereqs/unknowns to work out:
   where the glitch is injected (core Vdd vs. flash-pump rail; clock is internal-PLL on TMS470, so
   voltage glitching is likelier than clock), a reset+trigger harness (the `10 85` descent or power-on
   is the trigger), and whether the persistent flash-SA lockout also throttles glitch attempts. This
   is well-trodden ground for ARM7/TMS470-class parts. NOTE: fault injection has NOT been attempted
   yet — it's a planned avenue, pending a glitch rig and board-level access to the core/flash rails.

6. **Lockout-reset levers in the ASW — investigated, NONE exist (2026-10-05, RE-proven).** Checked
   whether a session-toggle or ECUReset (the Garcia et al. trick) or any diagnostic routine can reset
   the flash-SA lockout. Result: **no.** (i) There is **no SID 0x11 (ECUReset)** in either KWP service
   table — the ASW implements no reset service. (ii) The SID 0x10 (StartDiagnosticSession) handler
   (`FUN_00093858`) clears ~20 session cells but touches **none** of the security cells (`0x405e12`,
   `0x4079e4`, `0x408843`, `0x408500`, `0x40bffc`) — a session change does not reset lockout state.
   (iii) `kwp_security_access_sm` (`0x8b850`) only *decrements* `0x405e12` (never writes it up) and
   *clears* grant bits on session `0x86`. (iv) There is **no NvM/EEPROM manager and no RoutineControl
   (`0x31`) / WriteData (`0x3b`/`0x2e`) path that writes any security counter** — app-session `0x31`
   is a 2-byte no-op stub, prog-session `0x31` (`kwp_actuator_test_31_prog` `0x98f84`, now RE'd) is
   a volatile actuator test (sub 0/1/2/3 → test-timing params, resp `0xc3`, no NVM/security writes). So the
   persistent flash-SA counter is entirely **SBOOT/NVM-side and unreachable from this image**; the
   only non-hardware lever is to wait out its time-delay (confirm with `fbl_check.py`). Residual
   caveat: a few table-A handlers live in the `>0xa2000` seg2 that doesn't disassemble cleanly, but no
   NVM/SPI driver exists anywhere in the image for such a handler to call.

7. **Literature/community research — COMPLETED (2026-10-05, browser + web search).** Exhaustive
   sweep of nefmoto, icanhack.nl, bri3d's repos, BtB paper (Van den Herrewegen & Garcia, ESORICS
   2018), Van den Herrewegen PhD thesis, and general web search. **Key conclusion: no one has
   publicly cracked flash-level SA on a Bosch ABS/ESP module via diagnostics.** The SGO's SA2
   bytecode is the flash SA for engine ECUs (MED17/Simos/ME7) but NOT for Bosch ABS — see the
   "Where the SGO's SA2 fits" section above for the full analysis. Remaining community leads:
   (a) TI TMS470 `e2e.ti.com` thread "tms470mf06607-tms470-bootloader" (403'd via direct fetch;
   snippet described a CAN-reflash bootloader loaded to RAM at `0x207800`, 2KB, and dump tools
   "JCommander"/"savebin" over JTAG); (b) bri3d's Simos18 SBOOT docs mention Bosch SBOOTs have
   PWM "break-in" mechanisms — a new lead for avenue 3/5.

8. **RaceABS tool software-RE — DONE 2026-10-04/05.** New build = architecture only; **OLD build
   dynamic-unpacked → the actual motorsport seed→key algorithm recovered** (but it is 16-bit and
   does **NOT** match our 32-bit production SA — see "OLD build" subsection at the end). Chased the
   nefmoto "Bosch ABS Boot Mode" lead: Bosch's own RaceABS Motorsport tool implements this ECU's
   KWP2000 SecurityAccess, historically delegating the seed→key crypto to an external `SecAcc.dll`
   (community confirmed `SecAcc.dll` never shipped). Full procedure + provenance below; all RE
   artifacts kept in scratch, **not** committed (same rule as firmware).
   - **Source (better than the dead forum links):** both forum URLs are dead (the `.jp` 404s, the
     `.de` one redirects to a `bosch-motorsport.com` 404; Internet Archive has no capture of
     either). Bosch's **current** site still ships it: `RaceABS` product page →
     `bosch-motorsport.com/.../raceabs-software-tool/` → `raceabs_software_tool_3-5-5-3_70613771.zip`
     (**v3.5.5.3**, 32.5 MB, first-party; sha256 `86b7c4f5…64d4e97`). Outer zip = one `RaceAbs.exe`
     Inno-Setup-6.4.3 installer; enumerated with `innounp-2` v2.67.11 (needed — `innoextract` 1.9/1.10-dev
     can't parse Inno 6.4).
   - **`SecAcc.dll` is NOT bundled** (confirmed by full manifest; extends the 2023 community finding
     to the newest build). No file named `*SecAcc*` anywhere in the installer.
   - **Architecture recovered (this is the new detail):** the seed→key crypto is a **runtime-bound
     native delegate**, not a shipped algorithm. In `RaceAbsLogic.dll` (managed .NET):
     `RaceAbsLogic.Kwp.KwpFacade` (KWP2000 path, the relevant one for this ESP8-class/"RACEAb8II"
     module; a parallel `RaceAbsLogic.Uds.UdsFacade` serves the newer M5/"RACEAb9II" UDS units)
     holds a field `UnmanagedLibrary` + a delegate `dllFunc` with signature
     **`int Invoke(int algoNumber, byte[] dataBuffer, int dataBufferSize)`** (seed in / key out,
     in-place). It is bound at runtime via `LoadLibrary`+`GetProcAddress`+`GetDelegateForFunctionPointer`.
     The `algoNumber` selector **confirms the algorithm is chosen per variant/device** (Changelog
     `BMISW-12462 "Seed & Key implementation"` + "switching between non-seed-and-key and
     seed-and-key enabled devices" — i.e. only some ABS variants use SA at all).
   - **Why the algorithm still isn't obtainable from this download:** (a) the DLL that exports that
     `(int,byte[],int)` function is **not in the installer** — none of the bundled native DLLs
     provides it: `CPAL.dll` = Vector-style protocol transport only (exports `_Kwp2kApi_SecurityAccess@24`
     + CHAL/CCP, plus the `invalidKey`/`securityAccessDenied` strings — it *sends* 27, doesn't compute
     the key); `BoschACXHelper.dll`/`PTwinSimWrapper.dll` = Bosch **license** checks + encrypted-file
     helpers (`CheckBoschLicense*`, `GetIntermediateKey`); `PCANBasic.dll` = Peak CAN driver;
     managed `Crypt.dll` = the tool's own file/parameter encryption (RSA/MD5/`EncryptFile`), not ECU
     SA. (b) The managed glue that would reveal the DLL name/`algoNumber`/marshaling is **protected
     by a method-body-encryption obfuscator** — `KwpFacade::SecurityEcuAccess` / `DoSecurityEcuAccessTask`
     etc. are genuine IL stubs (`nop;nop;…;ret`, verified via dnlib), real bodies restored only at JIT;
     strings and namespaces are encrypted. It is **not** ConfuserEx (no ConfuserEx attribute), so the
     forum's 2022 "ConfuserEx-Unpacker" recipe no longer applies (matches the 2024 poster's "doesn't
     work with the current one"). The LoadLibrary DLL-name argument is an encrypted literal.
   - **Note on jglim/SecurityAccessQuery:** moot — its `GenerateKeyEx` convention differs from this
     tool's `(int algoNumber, byte[] buffer, int size)`, and there's no DLL to feed it anyway.
   - **OLD build (v1.4.0.9 / "1409", 2016) dynamic-unpacked — algorithm RECOVERED, but it's the
     motorsport SA, not ours (2026-10-05).** The old build *does* embed the crypto, so it was worth
     chasing. Source: the new/current Bosch URLs only serve v3.5.5.3; the 1409 build came from the
     one community re-upload (anonymous, so treated as untrusted — see method). It's an NSIS installer
     whose app `RaceABS.exe` is **ConfuserEx v0.5.0** (the forum's target), class
     `RaceABS.LayerDevice.DeviceKwpAbs` with `SecurityEcuAccess` / `GetKeyABS`. The seed→key crypto is
     a tiny **native `KH.dll`** (7680 B, exports `Get_SeedRequest_Message` / `Get_KeyRequest_Message`)
     embedded as a resource inside a sibling assembly `RaceABS.Lib`; both are ConfuserEx
     anti-tamper + resource-encrypted, so static de4dot-cex could **not** decrypt them (bodies came
     out corrupted). Recovered by running the untrusted binary **only inside a disposable,
     network-disabled Windows Sandbox** (`.wsb`): ConfuserEx *Dynamic* Unpacker → `RaceABS.exeCleaned.exe`
     (real bodies), and ExtremeDumper dumped the in-memory `RaceABS.Lib` → extracted `KH.dll`.
     The native algo (disassembled with capstone, cross-checked against the deobfuscated managed
     `GetKeyABS`) — `Get_KeyRequest_Message(algoNumber, buf, size)`, managed side hard-codes
     **algoNumber=1** (modes 2/3 are empty stubs):
     ```
     s0,s1 = seed[0],seed[1]          # first 2 bytes of the 27 01 seed response; 16-bit only
     seed16 = (s0<<8)|s1
     amt    = bit5(s0) | bit4(s1)<<1 | bit1(s1)<<2 | bit2(s1)<<3        # rotate amount 0..15
     rot    = ROL16(seed16,amt) if bit2(s0) else ROR16(seed16,amt)
     op     = bit3(s0) | bit4(s1)<<1                                    # 0..3
     key16  = {0:rot|seed16, 1:rot&seed16, 2:rot^seed16, 3:rot}[op]
     reply  = 27 02 (key16>>8) (key16&0xFF)
     ```
     Full flow: `SecurityAccess(…,1,…)`→seed → `GetKeyABS` (loads `KH.dll`) → `SecurityAccess(…,2,key,…)`.
     **Verdict for us: does NOT unlock `8R0907379BG`.** This is a **16-bit** scheme for the *motorsport*
     ABS (M4/M5 "RACEAb8II/9II" race kits). Our **production** unit uses **32-bit** seeds on both SA
     systems (coding SA proven `key=seed32+0x2909`; flash SA 32-bit, SBOOT-side) — incompatible seed
     width, and a different per-variant algorithm this 2016 `KH.dll` doesn't implement. No bench
     attempt is warranted (not applicable, not merely untested). Still useful: first complete Bosch ABS
     seed→key recovered, confirms the lightweight motorsport SA + the per-`algoNumber` design; the
     download→sandbox-unpack→native-RE pipeline is proven and reusable if a production-ABS tool or a
     newer `KH.dll` (with algo 2/3) ever surfaces.
   - **Net:** the RaceABS→`SecAcc.dll`/`KH.dll` avenue is **exhausted for our module** — the one
     algorithm it yields is the wrong (motorsport, 16-bit) one. Don't revisit without a *production*
     ABS tool or an independently-sourced production crypto DLL.

9. **ODIS-E 17.0.1 installation investigation — COMPLETED 2026-10-05.** Examined the full ODIS-E
   distribution (`H:\torrent\ODIS-E 17.0.1`) looking for ODX containers describing the ESP8's
   security method, `SecAcc.dll`, or any security DLLs. **Result: `SecAcc.dll` does NOT ship with
   ODIS-E. Flash security uses server-side key computation via VW's D3 backend.**
   - **Main installer** (449MB EXE): the 449MB `[0]` payload is a custom VW format, not Inno/NSIS.
     String search across the full binary found zero hits for `SecAcc`, `SeedKey`, `SecAccess`.
   - **VWMCD** (3.34GB diagnostic database): only one DLL in the entire archive — `libGWSK32.dll`
     (6.6KB) in `BG744/` (gateway platform), a **Gateway** Seed/Key DLL, not ABS. AU37X (Q5) has
     `BV_Brake1UDS.bv.db` (1.2MB) but **NO KWP2000 brake variant** — our ESP8's protocol isn't even
     defined in ODIS-E v17's Q5 database. The BV files are zlib-compressed proprietary binary.
   - **PostSetup ISO** (Brand-A diagnostic data): JARs contain encrypted `.class` procedure scripts
     (VW `VaudesSmardlang` custom ClassLoader encryption — `javap` cannot read any of them; the
     constant pool first byte is a non-standard tag). The `1.58.0_2c.zip` has J104 scripts
     (`Audi_Flashen`, `Komponentenschutz_Bremse`) but all are encrypted.
   - **Security access architecture** (recovered from encrypted class file names/packages):
     ODIS-E has TWO distinct server-side security mechanisms:
     - **SFD (Schutz Fahrzeug Diagnose)** — coding/adaptation protection (2019/2020+ vehicles):
       `SecurityAccessSFD.class` (27KB), `SecurityAccessSFDTokenManager.class` (14KB),
       `SecurityAccessSFDUnlock.class` (17KB); `offline\DownloadOfflineTokensAction`,
       `manual\ManualSfdTokenUtil` — for time-limited coding unlock via online/offline/manual tokens
     - **Flash D3 server mechanism** — flash-level security:
       `flash\d3server\` package — communicates with VW's **D3 backend server** for flash SA key
       computation; `VaudesKeystore.jks` — Java keystore for TLS auth to VW's backend;
       `de\vw\vaudes\security\cryptography\` — local crypto for the D3 TLS protocol, not ECU SA
     - **Shared infrastructure**: `ISecurityAccessModel$OnlineAccessMethod` /
       `$OnlineAccessDuration` / `$OnlineRequestedRole` — time-limited, role-based server access
     - Protocol-specific: `SecurityAccessScedulerJobKwp2000.class` (5.5KB) confirms KWP2000
       support exists and routes through the server-side backend
   - **What this means for our ESP8:** the flash-SA key for Bosch ABS modules is computed
     **server-side by VW's D3 infrastructure** — there is no local DLL, no local algorithm, and no
     way to extract the secret from ODIS-E. The `SecAcc.dll` referenced on nefmoto is likely
     Bosch-internal tooling, never distributed with any ODIS version.
     This avenue is **exhausted** — ODIS-E cannot help us obtain the flash-SA algorithm.

10. **Community research on SFD / D3 server architecture — COMPLETED 2026-10-05.** Searched
    nefmoto, MHH Auto, vagprogramming.com, Ross-Tech wiki, and general web for details on
    how ODIS contacts the D3 backend server.
    - **SFD ≠ flash security.** SFD = "Schutz der Fahrzeugdiagnose" (Protection of Vehicle
      Diagnostics), confirmed by Ross-Tech wiki (wiki.ross-tech.com/wiki/index.php/SFD) and
      vagprogramming.com. It is a **coding/adaptation protection** system for 2019/2020+ MQB/MQB
      Evo vehicles, replacing the old 5-digit login code for coding access. It gates Coding,
      Adaptation, Basic Settings, and Output Test — NOT flash-level SecurityAccess. There is
      also SFD2 (UNECE R155/R156 compliance extension). Affected modules: Gateway (19), Central
      Electronics (09), Instrument Cluster (17), Infotainment (5F), steering, camera, ACC.
    - **SFD process** (from Ross-Tech, vagprogramming): tool requests unlock → authenticates with
      VW backend (GeKo = "Geheimnis und Komponentenschutz") → receives signed VIN-tied token →
      time-limited window (typically 89 minutes per Ross-Tech). Online, offline (pre-downloaded),
      and manual token modes exist. Third-party providers (Vaglogins, VCTool) sell tokens ~$19.
    - **Flash D3 server** is a SEPARATE mechanism from SFD. The `flash\d3server\` package in ODIS
      handles flash-level security by contacting the VW backend for key computation during ECU
      reprogramming. This is the mechanism that replaced local DLLs / SA2 bytecode for flash SA.
    - **Pre-SFD flash security for engine ECUs** used SA2 bytecode embedded in .frf/.odx containers.
      But Bosch ABS/ESP modules **never used SA2** (confirmed avenues 1-7). The Bosch ABS SBOOT
      uses its own proprietary seed→key algorithm, and ODIS computes the key server-side via D3.
    - **Nefmoto/MHH**: zero results for Bosch ABS flash security specifics. These communities
      focus on engine ECU tuning (ME7/MED17/Simos). Nobody has published a Bosch ABS flash-SA
      algorithm from any source. MHH is Cloudflare-gated (could not access directly).
    - **Conclusion**: the original claim "ODIS contacts VW's D3 backend server with the ECU's
      seed" is CORRECT for the flash D3 mechanism, but this is NOT the same as SFD (which is
      coding protection). The `SecurityAccessSFD*` classes handle coding; the `flash\d3server\`
      package handles flash SA. Both are server-side, but they are different systems.
      For our ESP8, this means **the flash-SA algorithm exists only in the Bosch SBOOT firmware
      and on VW's D3 server** — it has never been distributed locally in any tool or container.
      Avenue **exhausted** — confirms hardware/exploit as the only remaining viable path.

## Bench tools (current, in `bench/`)

- `tp20_kwp.py` — core TP2.0+KWP2000 client (`TP20KWP`, `RawCAN`).
- `can_raw.py` — raw CAN wrapper, accepted-id RX filter list, sniff/wake helpers.
- `emu_unlock.py` — operational-gate stimulus (`Stim`, configurable `--ids`) + full unlock-attempt
  flow (coding SA, programming-session descent/reconnect).
- `esp_unlock.py` — coding (level-3) SA unlock + post-unlock capability probes.
- `fbl_sa2.py`, `fbl_keytest.py`, `fbl_check.py` — flash-SA (level-1/SBOOT) testing tools.
- `read_probe.py`, `flash_probe.py` — post-coding-unlock capability probes (21/22/2C/35/23/34).
- `nm_operational.py` — full ComM-operational (NM container) driver, untested on bench.
- `sa2_unlock.py` — the SGO SA2 VM (`Sa2SeedKey`), validated against 3 independent test vectors.
- `power.py` — scripted FEPS power-cycle control.
