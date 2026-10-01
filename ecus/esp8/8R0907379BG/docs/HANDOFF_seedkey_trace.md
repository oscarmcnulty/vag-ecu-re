# Handoff prompt — RE the KWP2000 SecurityAccess seed→key (ESP8 8R0907379BG)

> Paste everything below the line into a new session. It is self-contained; it assumes the repo at
> `C:\Users\om\vag-ecu-re` and the committed state as of 2026-10-01.

---

## Mission
Recover the **KWP2000 SecurityAccess (`27 01` seed → `27 02` key) algorithm** for this Bosch ABS so we
can unlock the gated diagnostic services and dump flash. This is a **firmware reverse-engineering**
task on the (now un-degraded) seg2 code. The transport/protocol is already fully cracked and working.

## What is already DONE (do NOT redo — see docs/HANDOFF_uds_dump.md for full detail)
- **Diagnostics are VAG TP2.0 + KWP2000, NOT UDS.** Working, reproducible from the bench:
  - Channel setup `03 C0 00 10 00 03 01` → `0x200`; ECU replies `0x203: 00 d0 00 03 a3 04 01`.
  - Channel: **we TX→0x4a3, we RX←0x300**. Params `A0 0F 8A FF 32 FF` → `A1` (send A0 the instant the
    first `0xD0` arrives; answer the ECU's `0xA3` channel-tests with `0xA1` or it drops in ~1s).
  - `10 85` (StartDiagnosticSession) → `50 85 00`. Tooling: **`bench/tp20_kwp.py`** (full working client).
- **Service map (session 0x85):** nearly all services return NRC **`0x90`** (VAG "security/session
  required") — supported but gated. **SecurityAccess level 01 only**; seed is **random 4 bytes**
  (`67 01 <seed>`, e.g. `fe ba 40 73`). `27 03/05/09` → `7F 27 12`. 36→7F33, 37→7F22, 22→7F31.
- **Key is NOT SA2** (no SA2 bytecode in the firmware) → it is a **direct algorithm in code**.
- **Pipeline fix applied (reproducible):** `EspSeg2.java` now recovers **Thumb** functions in seg2
  (+103), fixing the degraded decompiles where the KWP diag stack lives. `function_entries.txt`
  regenerated (2670 Thumb / 1999 ARM).

## FIRST STEP in the new session
Run a full reproduce so all decompiles reflect the Thumb fix:
```
source .env.sh && ecus/esp8/8R0907379BG/reproduce.sh      # needs Ghidra 11.4.2 (GHIDRA_HOME) + JDK21
```
(ends `done.`; decompiles land in `ecus/esp8/8R0907379BG/analysis/decompiles_r/`). If reproduce is
too heavy, at minimum the committed manifest already lists the Thumb funcs; decompile seg2 with
`core/ghidra/DecompileAll.java`.

## The trace to run (seg2 code is now readable)
Goal: TP2.0 reassembly → KWP SID dispatch → the `0x27` case → the seed-gen + key-check code.
1. **Anchor A — TP2.0 state machine:** examine `FUN_000e8658` / `FUN_000ed808` (switch on states
   0..0xd — the TP2.0/transport SM). Find where a *complete reassembled KWP message* is handed to a
   dispatcher; follow that call.
2. **Anchor B — the KWP SID dispatch** is an if-chain / jump-table (NOT a `switch`). From Anchor A's
   dispatch call, find the function that branches on the first PDU byte (SID) and reaches a `0x27`
   case. That case: subfunction `01` → generate+store a 4-byte seed, respond `67 01 <seed>`;
   subfunction `02` → read stored seed, compute expected key, compare with the received 4 bytes, set a
   "security unlocked" RAM flag on match.
3. **Anchor C — the security-unlocked flag:** the gated services return NRC `0x90` by checking one RAM
   flag. Find a byte that is *written in one place* (the `0x27 02` success path) and *read in many*
   diag handlers (the `0x90` gate). The writer is the key-check; work backward to the transform.
4. **Anchor D — seed generation:** the `01` path reads a free-running timer/counter for the random
   seed (observed seeds start `0xfd..0xff`). The key transform operates on the *stored* seed.
5. Once the transform is found, implement `key_from_seed(seed)->key` and **verify on the bench**:
   `bench/tp20_kwp.py` → `27 01` (get seed) → `27 02 <key>`. A `67 02` = unlocked. ⚠️ **Do NOT brute
   force** — KWP locks out after ~3 bad keys (power-cycle to reset; ignition switch must be ON).

## RULED OUT (do not repeat)
- SA2 bytecode: none in firmware. SID/opcode **constant-grep is useless** (0x10–0x3e collide with
  struct offsets/masks everywhere). The rx-filter "handler 0xa43f5" is a **red herring** (0xa43f4 is a
  control-data pointer table). The 8 known seg2 DID readers (0xc71ac/d2090/d5ab8/dcd3c/dcdb4/dd004/
  dd378/ddf5c) are not it. Crypto-signature search (xor+shift+loop) finds only **`FUN_000d82d4`** — a
  table-driven **CRC-8 validator** (table ~`DAT_000d83c0`), a message/E2E CRC, not the key (though the
  CRC table *might* be reused by the key — worth a look).
- Candidate data tables worth parsing: a per-SID/subfunction flag table at **`0xae95c`** (just before
  the rx-filter table `0xaea38`); the DID tables at `0xb44e4`/`0xb4598`.

## Alternative (faster if available): capture a real (seed,key) pair
If an ODIS/dealer tool can unlock this ABS, log one `27 01`/`27 02` exchange. One valid pair strongly
constrains/confirms the algorithm and sidesteps the firmware trace.

## Environment
- 32-bit Python embed (for `smj2534.dll`): `…/claude/C--Users-om-vag-ecu-re/35dcc8f2-…/scratchpad/
  py311x86/python.exe` (re-download python-3.11.9-embed-win32 if the scratchpad was cleaned).
- Bench: Scanmatik 2 Pro, module B = SM2-Pro/T38a **pins 26(H)/14(L) @500k**, **ignition switch = ON**
  (the pigtail 3-pos switch; term-15 must be on or the module sleeps/won't do diag). Keep bus >5Hz.
- Ghidra 11.4.2 at `C:\Users\om\ghidra_11.4.2_PUBLIC` (GHIDRA_HOME in `.env.sh`), JDK21.
- Commit only metadata (CSV labels / scripts); firmware + decompiles are gitignored. End commits with
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
