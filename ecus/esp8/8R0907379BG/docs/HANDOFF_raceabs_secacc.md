# Handoff — recover the real flash-SA algorithm from Bosch's own RaceABS tool

Paste everything below the line into a new session. Self-contained; assumes the repo at
`C:\Users\om\vag-ecu-re` and the state committed as of 2026-10-05 (commit `fa07a67` and later).

---

## Mission

Bosch's own factory/motorsport calibration tool ("RaceABS") implements the exact KWP2000
SecurityAccess mechanism this ECU uses, in a method called `SecurityEcuAccess()`, which delegates
the actual seed→key crypto to an external DLL (`SecAcc.dll`). Goal: obtain or get close enough to
that algorithm — either the DLL itself (bundled in some installer release, or found through a
legitimate channel), or protocol-level detail from the deobfuscated calling code around it — to
crack the **flash-level SecurityAccess** (KWP level 1, post-`10 85` descent), which is the one
thing still blocking a memory dump / patched-firmware flash on the physical ESP8 module. This is
software reverse-engineering of a downloaded Windows tool, not firmware RE of the ECU — read
`CLAUDE.md` first, but this task doesn't touch the firmware pipeline directly.

## Required reading before starting

`ecus/esp8/8R0907379BG/docs/SECURITY_ACCESS.md` — the single current source of truth for this
module's diagnostics/SecurityAccess/flash-security status. Key facts to carry in:
- **Coding-level SA (KWP level 3, `27 03/04`) is SOLVED**: `key = seed + 0x2909` (big-endian),
  emulator- and bench-verified. Not what we're chasing here.
- **Flash-level SA (KWP level 1, post-`10 85` descent) is the open problem**: its seed-gen/key-verify
  live in SBOOT, a separate flash region not in our firmware dump. Candidates tried so far (SGO's
  SA2 bytecode in all 4 byte orders, a `0x5FBD5DBD` login variant, 2 of the coding SA's 6 deltas)
  all cleanly rejected (`invalidKey`), so the compare mechanism is real and these are genuinely
  wrong keys — not a harness bug.
- **MCU identified as TI TMS470R1x** (likely `TMS470R1B1M`) — confirmed independently via our own
  firmware's CAN controller addresses matching TI's documented HECC1/HECC2 base addresses exactly.
- **BENCH STATUS, check before touching hardware:** the flash-SA lockout escalated during the last
  session to the point where it now blocks the `10 85` descent itself, not just the key compare
  (`bench/fbl_check.py` showed `10 85` → `conditionsNotCorrect`). The module needs an extended
  cool-off (hours, untested how many) before `bench/fbl_check.py` (seed-request only, never burns
  an attempt) shows it's clear again. **Do not run `fbl_sa2.py` / `fbl_keytest.py` candidates until
  `fbl_check.py` confirms the lockout has cleared.** This handoff's task (below) doesn't need the
  bench at all — it's pure software RE on a PC — so it can proceed regardless of lockout state.

## Where this lead came from

A nefmoto forum thread ("Bosch ABS Boot Mode", `nefariousmotorsports.com/forum/index.php?topic=14951.0`
— **fetch via the `claude-in-chrome` browser tool, not `WebFetch`, which 403s on this forum**)
documents a community member deobfuscating Bosch's official RaceABS Motorsport software and finding
`RaceABS.LayerDevice.SecurityEcuAccess()` — confirmed to be "part of the kwp2000 seed/key stuff
which lets you inside the ecu." A later poster confirmed the actual crypto is in a separate
`SecAcc.dll` that neither ships with the installer nor was obtainable by the community ("perhaps
its distribution is severely limited to only those who are authorized to have them"). The thread
itself ends inconclusively in 2025 ("for now, we are stuck") — there is no published solution, so
this is genuine, not-yet-public RE territory.

## Procedure (from the forum thread, to be verified/adapted)

1. **Download Bosch's official RaceABS installer** from Bosch's own domain. Two URLs surfaced
   (verify which is current/live — one was reported dead in the thread):
   - `http://www.bosch-motorsport.jp/media/msd/downloads/software/bremssysteme_1/RaceAbs_1409_Setupexe.zip`
   - `http://www.bosch-motorsport.de/content/downloads/Raceparts/Resources/zip/RaceABS%20Software%20Tool%203.5.3.1_70613771.zip`
   This is Bosch's own first-party distribution of their own tool — downloading it is not the
   "untrusted source" case. Do **not** use the anonymous Google Drive link posted later in the same
   thread by user "SqueeMax" — no provenance, can't be verified, real risk.
2. Extract with 7-Zip. **Before deobfuscating, just enumerate every file the installer contains** —
   check directly whether `SecAcc.dll` (or any similarly-named security/crypto DLL) ships bundled.
   If it does, that may be the whole answer without needing step 3 at all.
3. If `SecurityEcuAccess()`'s surrounding logic is still needed: get **ConfuserEx-Unpacker** from
   its official GitHub release only (`github.com/XenocodeRCE/ConfuserEx-Unpacker/releases`) and run
   it against the RaceABS executable to strip anti-tamper/deobfuscate:
   `"ConfuserEx Dynamic Unpacker.exe" -s RaceABS.exe` → produces `RaceABS.exeCleaned.exe`.
4. Open the cleaned executable in **dnSpy**, from its **official GitHub release only**
   (`github.com/dnSpy/dnSpy/releases`) — **do not download dnSpy from any other source or mirror**;
   there is a documented trojanized-dnSpy malware campaign (see
   `bleepingcomputer.com/news/security/trojanized-dnspy-app-drops-malware-cocktail-on-researchers-devs/`),
   flagged in the same forum thread. Verify the release checksum if possible.
5. In dnSpy, navigate to `RaceABS.LayerDevice.SecurityEcuAccess()`. Read what it does: does it call
   out to `SecAcc.dll` via P/Invoke (note the exact exported function name and signature — likely
   `GenerateKeyEx`/`GenerateKeyExOpt`, the standard convention used by this class of vendor security
   DLL per `github.com/jglim/SecurityAccessQuery`, confirmed to work with Vector-ecosystem DLLs and
   plausibly compatible if `SecAcc.dll` follows the same convention)? What seed/key byte lengths and
   ECU-identification logic does it use (does it select different security parameters per
   part-number/hardware-variant — this ECU is `8R0907379BG` — which could directly tell us whether
   the flash-level algorithm is shared across the ESP8 family or per-variant)? Any embedded
   constants, byte arrays, or opcode-like sequences worth comparing against the SGO's SA2 tape
   (`ADD 0x974c58ab; BCC+7; EOR 0xfedcba98; BRA+5; EOR 0x98765432; FOR 11 {RSR}; FINISH`) or the
   coding-SA deltas (`0x2909/0x564f/0x75fb/0x9ce8/0xefc2/0xfe10`)?
6. If `SecAcc.dll` is found (bundled, or through any other legitimate channel), use
   `github.com/jglim/SecurityAccessQuery` to actually invoke it and compute real key(s) — test
   candidates against the physical module later, in a fresh session, respecting the lockout-cooldown
   status above.

## If this doesn't pan out

Don't force it — if the installer doesn't ship the DLL and the unpacked code reveals nothing
beyond "calls an external DLL we don't have," that's a real, useful negative result: it means this
specific avenue is exhausted and not worth revisiting without a different source for `SecAcc.dll`.
Record whatever was found (or the clean negative) in `SECURITY_ACCESS.md`'s "Open avenues" section
and the `esp8-sa-key` Claude memory note — don't create a new scattered doc; this repo just went
through a consolidation pass specifically to avoid accumulating contradictory handoff docs (see
commit `3d63b6f`).

## Reminders / constraints (unchanged from the rest of this project)

- Bench + RE only. No ODIS/ODIS-E, VCDS, dealer tools, or capturing a real (seed,key) pair from any
  other tool — this task is downloading and reading Bosch's **own published software**, which is a
  different thing and already in scope, but don't cross into using a dealer tool against the module.
- No brute-forcing the physical ECU's SecurityAccess. If this research yields a candidate key,
  that's one single informed attempt, not a sweep.
- Firmware images, decompiled C, and `ghidra_proj/` stay gitignored. The RaceABS installer and any
  extracted/deobfuscated executables are **also** not something to commit — keep them in a scratch
  location outside the repo (or gitignored), same spirit as firmware artifacts.
- Attribute findings and commit any doc/memory updates per the repo's normal convention.
