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

Wrong key → `7F 27 35 invalidKey`, resets state, decrements `sa_lockout_counter` (`0x405e12`,
3-try, **volatile — resets on power-cycle**). Confirmed live: `27 03`→seed, `27 04 <seed+0x2909>`→
`67 04` **UNLOCKED**. This opens session `10 86` (confirmed `50 86`) and `21 ReadDataByLocalId`
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
appeared to lengthen with repeated attempts). Test candidates sparingly, one at a time, with waits
between — do not loop automated retries against it. Tool: `bench/fbl_sa2.py` (single back-to-back
attempt), `bench/fbl_keytest.py` (candidate list, one per invocation via `--start`/`--n 1`),
`bench/fbl_check.py` (lockout-state probe — seed-only, never burns an attempt).

**Where the SGO's SA2 fits:** the OEM flash container (`8R0907379BG_0030.sgo`) embeds a 24-byte SA2
bytecode program at offset `0x1bb` (identical across all 4 sibling SGOs — genuine, not a template):
`ADD 0x974c58ab; BCC+7; EOR 0xfedcba98; BRA+5; EOR 0x98765432; FOR 11 {RSR}; FINISH`. Our VM
implementation (`bench/sa2_unlock.py`, `Sa2SeedKey`) is **validated against 3 independent public
test vectors** (bri3d/sa2_seed_key format, incl. one using the `0x5FBD5DBD` constant) — it is
correct. Its constants (`0x974c58ab`, `0x98765432`) are **absent from the ASW image**, consistent
with it being the SBOOT/flash-SA algorithm (not the coding one) — but all 4 byte-order variants of
it were rejected by the live flash-SA compare, so either the byte order differs in a way not yet
tried, the seed is preprocessed before the SA2 runs, or ODIS computes the flash key from a different
input than the SGO's SA2 blob entirely. Open question.

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
3. **Hardware SBOOT dump** — BDM/JTAG/boot-mode off the physical module. The bench cable's
   `CNF1`/`BOOT1`/`BOOT2` leads are exactly what commercial boot-mode tools (bFlash, Autotuner, SM2
   Pro's own TriCore boot support) use. Blocked so far only by not having identified the die/MCU
   (bare-die hybrid, decapped, unmarked — see `docs/` images from 2026-10-04) and not having
   established which pins are CNF1/BOOT1/BOOT2 on *this* harness.
4. Un-mined idea sources: other fully-reversed VAG modules (UnlockECU project — our `VolkswagenSA2`
   implementation matches it exactly, confirming correctness, not the fix), VAG KWP2000 forum
   threads (nefmoto "Bosch ABS Boot Mode" — not yet successfully fetched, worth another attempt via
   browser rather than WebFetch, which 403s on that forum).

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
