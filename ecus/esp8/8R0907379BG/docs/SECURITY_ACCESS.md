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

### 2. Flash SA — level 1 — **SOLVED: it is the SGO SA2** (ground-truth from an ODIS flash, 2026-10-10)

The flash-level SecurityAccess is the **SA2 bytecode shipped in the SGO**, big-endian seed →
big-endian key. Proven by decoding a real ODIS flash session of *this* module
(`captures/20a2-0001-20261010-153902.pcap`, usbmon → TP2.0/KWP2000; decode pipeline in the
`esp8-odis-flash-capture` memory note):

```
10 85                     -> 50 85 14           StartDiagnosticSession (ProgrammingSession)
[TP2.0 channel reconnect to logical addr 0x03, same IDs TX 0x4a3 / RX 0x300]
27 01                     -> 67 01 fe a6 d6 ca  seed
27 02 bd ad 65 f2         -> 67 02 34           ACCEPTED
34 00 80 00 00 0b 80 00   -> 74 cd              RequestDownload addr 0x008000 len 0x0B8000
... full flash follows (see "Flash sequence" below)
```

`SA2(0xFEA6D6CA) = 0xBDAD65F2` via `bench/sa2_unlock.py` (`Sa2SeedKey`, script
`93974c58ab4a0787fedcba986b058798765432680b82494c` @0x1bb) — an **exact match** to the key ODIS
sent and the ECU accepted. One live-validated (seed,key) pair; the algorithm generalizes it for any
seed. The VM was already validated against 3 independent public test vectors; it is now also
validated against live OEM traffic on this exact part.

**Context (all confirmed by the capture):** reached after `10 85` + a TP2.0 reconnect to addr 0x03
(the channel refreshes before the key exchange). Seed high byte is `0xFD/FE/FF` (timer-idiom
seed-gen). `27 02` is state-gated — ODIS sends it **immediately** after `27 01` (~40 ms, no
intervening frame). A separate SBOOT dispatcher answers this level-1 SA (it presents a different
`0x27` subfunction-support set than either KWP table; `asw_start_sboot` @0x8f440 shows the ASW is
launched by SBOOT) — but that SBOOT dispatcher **uses the SGO SA2**, not a proprietary algorithm.

**Why the earlier bench run saw `invalidKey` on SGO SA2 (correction):** the prior conclusion that
all 4 SGO-SA2 byte orders were "genuinely wrong keys, not a harness bug" is **disproven** by the
capture — BE seed / BE key is exactly what ODIS uses. The bench failures were state/lockout
artifacts, not a wrong algorithm:
- the NVM-persistent flash-SA lockout (`7F 27 36 exceedNumberOfAttempts`), which the bench
  repeatedly tripped and escalated — eventually even blocking the `10 85` descent itself
  (`7F 10 22 conditionsNotCorrect`), so `27 02` was being compared against a locked/garbage state;
- and/or a stale per-request seed or a non-back-to-back `27 02` (any intervening frame →
  `subFnNotSupported` or a compare against a rotated seed).

**Flash sequence ODIS used (two download blocks, both accepted):**

| step | request | response |
|---|---|---|
| session | `10 85` | `50 85 14` |
| SA | `27 01` / `27 02 <SA2(seed)>` | `67 01 <seed>` / `67 02 34` |
| block 1 download | `34 008000 00 0B8000` (addr 0x008000, 753 664 B) | `74 cd` |
| block 1 erase | `31 C4 0080000bffff00000000002e` | `71 C4 1f` |
| block 1 data | `36 …` × 3695 (753 664 B) | `76 …` (all positive) |
| block 1 exit | `37` | `77` |
| block 1 checksum | `31 C5 0080000bffff cc76` | `71 C5` (results `73 C5 00` = OK) |
| block 2 download | `34 804000 00 07C000` (addr 0x804000, 507 904 B) | `74 cd` |
| block 2 erase | `31 C4 80400007ffff00000000002e` | `71 C4 19` |
| block 2 data | `36 …` × 2490 (507 904 B) | `76 …` |
| block 2 exit / checksum | `37` ; `31 C5 80400007ffff cc6a` | `77` ; `73 C5 00` = OK |

Routine `0xC4` = erase, `0xC5` = checksum/verify (last 2 bytes of its request = the expected
checksum word). Total ~1.26 MB over ~15 min, zero transfer errors.

**Remaining bench caveat:** the flash-SA lockout is NVM-persistent and was last seen escalated
(power-cycle did not clear it; it clears on a time delay). Before reproducing ODIS's unlock,
confirm the lockout has cleared with `bench/fbl_check.py` (seed-only, never burns an attempt), then
do the clean back-to-back `27 01` → `27 02 <SA2(seed)>` on a fresh power-cycle. Tools:
`bench/fbl_sa2.py` (single back-to-back attempt), `bench/sa2_unlock.py` (the SA2 VM),
`bench/fbl_check.py` (lockout probe).

**SGO SA2 provenance:** the OEM container (`8R0907379BG_0030.sgo`) embeds the 24-byte SA2 program
at offset `0x1bb`, identical across all 4 sibling SGOs: `ADD 0x974c58ab; BCC+7; EOR 0xfedcba98;
BRA+5; EOR 0x98765432; FOR 11 {RSR}; FINISH`. For VAG generally, SA2 bytecode in the flash
container is the standard flash-level seed/key mechanism (bri3d/`sa2_seed_key`, icanhack.nl,
nefmoto 18663/20977); this ESP8 follows that pattern — the detour searching RaceABS, ODIS-E and
VWMCD for an "external" Bosch-ABS algorithm (see the condensed research avenues below) was looking
for something that was in the SGO the whole time.

### Does the coding (level-3) unlock open the memory-read/flash-write services?

**No — but the flash SA (above) does.** With only the *coding* SA unlocked: `23`/`35`/`2C` in the
app session all refuse (`35`→`7F 35 80`; `2C`→`7F 2C 11 serviceNotSupported`; `23` not in table A
at all), and `34`/`35` in the programming session also `7F .. 80`. The transfer/read services are
gated by the **flash SA**, not the coding one: `kwp_security_access_sm` (`0x8b850`) records the
session-0x85 grant via `security_unlock_set` only **after a valid flash-SA key**. Since the flash SA
is now solved (SGO SA2), the correct unlock sequence — `10 85` → SA2 key → grant — is what opens
`23`/`34`/`35`. ODIS's capture shows `34` RequestDownload accepted immediately after the SA2 key, so
`23` ReadMemoryByAddress in the same unlocked programming session is the expected memory-dump path
(bench-confirm it after reproducing the unlock).

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

- **Flash SA — SOLVED.** It is the SGO SA2 (BE/BE), confirmed against live ODIS traffic (§2).
- **Memory dump (`23` ReadMemoryByAddress) — unblocked, pending bench confirm.** It is gated behind
  the flash SA; with the SA2 unlock in hand, the `10 85` → SA2 → `23` path should read arbitrary
  memory. Reproduce ODIS's unlock on the bench, then probe `23`.
- **Flashing stock/OEM firmware — possible now** (this is exactly what the captured session did).
- **Flashing *patched* firmware — still blocked, by the RSA-1024 signature, NOT by the SA.** Both
  signed regions carry RSA-1024 signatures that can't be forged (private key is SBOOT-side). A
  modified image won't validate at flash time regardless of having the SA2 key. Bypassing that
  verification is the one remaining hard problem, and it's what the hardware/exploit avenues below
  are for — they are no longer needed to *reach* the module, only to defeat signature enforcement
  (or to dump SBOOT itself, which the SGO container doesn't ship).

**Open avenues** — now scoped to the RSA-signature bypass / SBOOT dump, not to the flash SA
(avenue numbers kept stable; cross-references elsewhere still resolve):
1. **Flash-SA candidate sweep — CLOSED (solved).** The flash SA is the SGO SA2 (§2); no further
   key-guessing is needed. What remains of this avenue is purely operational: reproduce ODIS's
   unlock on the bench (clear the NVM lockout first — see §2 and avenue 6).
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

7. **Literature/community research — done (2026-10-05, browser + web search).** Swept nefmoto,
   icanhack.nl, bri3d's repos, BtB paper (Van den Herrewegen & Garcia, ESORICS 2018), the Van den
   Herrewegen PhD thesis, and general web search. At the time this concluded "nobody has publicly
   cracked Bosch ABS flash-SA, so the SGO SA2 must not apply to ABS" — **that inference was wrong**
   (the 2026-10-10 ODIS capture proves the SGO SA2 *is* our flash SA; see §2). Still-useful leads
   for the RSA-bypass / SBOOT-dump work: (a) TI TMS470 `e2e.ti.com` thread
   "tms470mf06607-tms470-bootloader" (CAN-reflash bootloader to RAM `0x207800`, 2KB; dump tools
   "JCommander"/"savebin" over JTAG); (b) bri3d's Simos18 SBOOT docs — Bosch SBOOTs may have a PWM
   "break-in" mechanism (feeds avenues 3/5).

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
     (6.6KB) in `BG744/` (gateway platform), a **Gateway** Seed/Key DLL, not ABS. The ESP8's
     project is **`AU48X`** (B8 Q5, 8R), which has **`@BV_Brake1KWP2000CAN20`** — the TP2.0+KWP2000
     brake variant matching this module; its diagnostic layer is present, but it holds only the
     SecurityAccess service definition, not the seed→key (brake defined at base-variant level, no
     per-part SA2 in the data — see the AU48X/VWMCD notes under the SGO/flash-SA discussion above).
     `AU37X` is the unrelated modern e-tron Q5. The `.bv.db`/`.sd.db` files are zlib-compressed
     proprietary binary.
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
   - **What this means for our ESP8:** `SecAcc.dll` / a local seed→key DLL does not ship with
     ODIS-E, and the `flash\d3server\` package shows ODIS *can* also compute flash keys server-side
     via VW's D3 backend. **But that does not mean our module's flash-SA is server-side-only** — the
     2026-10-10 ODIS capture shows this ESP8 is unlocked with the plain SGO SA2 (§2). The D3 path is
     a parallel/newer mechanism, not a prerequisite here. The search through ODIS-E for an external
     ABS algorithm was unnecessary (the algorithm was in the SGO).

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
    - **Pre-SFD flash security for engine ECUs** used SA2 bytecode embedded in .frf/.odx/SGO
      containers. (An earlier claim here that "Bosch ABS/ESP modules never used SA2" is **wrong** —
      see §2: this ESP8's flash SA *is* the SGO SA2.) The D3 server is a separate/newer server-side
      key path ODIS can also use; it is not required for this module.
    - **Nefmoto/MHH**: zero results for Bosch ABS flash-SA specifics — those communities focus on
      engine ECU tuning (ME7/MED17/Simos). MHH is Cloudflare-gated. (Lack of a public ABS write-up
      is why the SGO SA2 was wrongly assumed inapplicable; the ODIS capture settled it directly.)
    - **SFD ≠ flash SA** stands: `SecurityAccessSFD*` = coding protection; `flash\d3server\` = a
      server-side flash-key path. Useful context, but orthogonal to this module's SA2 unlock.

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
