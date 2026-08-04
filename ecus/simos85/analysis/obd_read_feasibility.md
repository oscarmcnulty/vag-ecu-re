# Simos 8.5 — external read paths, and why there is no OBD "port" read

Scope: how the firmware image is obtained *from outside* the ECU (not the internal
cal-read mechanics in `cal_read_method.md`). Answers:

1. How the Simos18 SBOOT exploit works and whether it does *actual* reads (§1).
2. What a Simos18-style **OBD** read actually is, and whether it can be built for 8.5
   (§2, §4).
3. Why no OBD full-flash read exists for 8.5 — grounded in this pack's integrity
   findings (§3).
4. The **CCP/XCP "measurement protocol" read vector** (the AL551 dump vector) and a
   **static analysis of every CAN read path this ECU actually exposes** (§5, §6).

Established facts are cited to repo files, primary sources, or specific firmware
function addresses (regenerable via `reproduce.sh`). Inference is labelled **inference**.
Nothing here has been run against a car.

---

## 0. Three doors (this is the whole point)

Getting firmware *out* of one of these ECUs uses one of three fundamentally different
attack surfaces. They are constantly conflated as "unlock," but they share nothing:

| | **Door 1 — SBOOT / boot exploit** | **Door 2 — OBD reflash unlock** | **Door 3 — CCP/XCP measurement slave** |
|---|---|---|---|
| Target | bootloader (SBOOT/CBOOT), pre-app | running app (ASW) + its UDS stack | a measurement/calibration slave on CAN |
| Entry | boot pins: PWM on GPTA + reset | UDS over the OBD port | CCP/XCP frames on a CRO/DTO mailbox |
| Physical access | **bench** (open ECU, probe vias) | **none** (OBD connector) | **none** (OBD / CAN tap) |
| Read primitive | BSL arbitrary read after pw recovery | run your own code, then read | `SET_MTA` + `UPLOAD` reads memory directly |
| Needs a signature bypass? | no (boot-level pw) | **yes** (to write unsigned code) | **no** (if `UPLOAD` is ungated) |
| Yields | full flash incl. boot sector | whatever you can install | whatever the slave will read out |

Door 1 is the SBOOT exploit (bench, §1). Doors 2 and 3 are the two ways an "OBD read"
can happen — and they are independent: Door 2 needs a signature bypass, Door 3 does not.
**On 8.5, §6 shows Door 3 does not exist (no CCP/XCP slave) and the only CAN read
surface is UDS, which is session+security-gated and has no read-by-address service.**

---

## 1. How the Simos18 SBOOT exploit works — and yes, it does real reads

Source: [bri3d/Simos18_SBOOT], [bri3d/TC1791_CAN_BSL], and the TC1796 port
[fastboatster/Simos8_SBOOT] / [fastboatster/TC1796_CAN_BSL].

**Entry (bench, pins — not a bus feature).** SBOOT decides whether to drop into its
"recovery shell" by *measuring a PWM waveform on two harness pins with the GPTA at reset*
— two 3.2 kHz squares phase-shifted a quarter period (`235.2 µs` pin1→pin2, `312 µs`
pin2→pin2). Only *after* that timing gate passes does it accept CAN messages (`59 45` →
`0xA0`, then `6B`) and enter recovery. So CAN is used *inside* the exploit, but the **gate
that makes SBOOT listen at all is a physical pin/reset event** the OBD connector cannot
assert. This is why every write-up calls it bench-only ("probe or solder to several very
small vias").

**The exploit chain, once in recovery:**
1. **Seed/key bypass.** The challenge RNG is a Mersenne Twister **seeded from the system
   timer (STM)** — predictable, not entropy. Constrain the seed by controlling timing, then
   brute the remainder (~`2^31`, ~500k pairs/s/core) until a key decrypts to the seed. (On
   8.5 the challenge uses a **1024-bit RSA key id `0x96`**, so 128 bytes of seed material vs
   256 on Simos18 — [fastboatster/Simos8_SBOOT].)
2. **CRC bounds-check leak.** The SBOOT CRC routine has weak bounds checking; ask it to
   checksum the **boot-password region** and return the CRC. CRC is reversible, so
   back-calculate the passwords (`crchack`/`twister`) from four CRC values harvested over
   ~2 min of reset-cycling.
3. **Passwords → BSL.** TC179x stores a 16-byte blob in the User Configuration Blocks:
   **first 8 bytes = read passwords, second 8 = write passwords**. Feed them to the CAN
   Bootstrap Loader and flash unlocks.

**Does it do actual reads? Yes — the fullest possible.** Once the BSL has the passwords it
does **arbitrary flash read/write/erase, including the boot sector** that OBD never returns.
This is the *only* known way to obtain Simos 8.5 `0x0–0x20000` (the region this repo marks
**blank in OBD read** — `README.md`, `analysis/RE_findings_checksum.md`,
`docs/methodology.md`). It is also this pack's open TODO ("obtain a bench/boot read to
study SBOOT/CBOOT").

**Status for 8.5:** the port is real but the authors' own words are "humble attempt" /
"partial implementation" — no clean end-to-end 8.5 dump is published. 8.4 needs different
pin connections than 8.5 ([fastboatster/TC1796_CAN_BSL]).

---

## 2. What a Simos18 *OBD* read actually is (Door 2)

The SBOOT exploit is **not** what gives Simos18 its OBD read. Door 2 is a separate
application-layer capability with two ingredients:

1. **Programming-session security access is computable.** The VAG "SA2" seed/key is a
   bytecode routine shipped *inside the ODX/FRF flash container* ([bri3d/VW_Flash],
   `sa2-seed-key`). Anyone with the container can answer the security-access challenge —
   this opens the programming session (write path).
2. **An RSA-signature bypass lets you write *unsigned* application code over UDS.** This is
   bri3d's core Simos18 contribution: defeat the signed-flash check so a modified/unsigned
   ASW is accepted over the ordinary OBD reflash (`RequestDownload`/`TransferData`).

Put together, Door 2 becomes **patch-and-read**: over OBD you write your own code into the
ECU, run it, and have *it* stream flash back — e.g. via `$23 ReadMemoryByAddress`, which the
Simos18 ASW exposes for logging (`simos_hsl.py`: `$23`/`$2C`/a proprietary `$3E` patch —
[bri3d/VW_Flash]). The "read" is a *consequence of running your own code over OBD*, not a
native "dump firmware" service.

**Load-bearing test.** An OBD full-flash read requires **one of**:
- (a) a stock service that returns arbitrary flash (Door 2 native, or Door 3's `UPLOAD`), **or**
- (b) the ability to run attacker code over OBD — which requires defeating the write-time
  signature check.

Simos18 has (b). §3 and §6 apply this test to 8.5: (a) is absent (no read-by-address
service, no CCP/XCP), and (b) is unbroken.

---

## 3. Why the same OBD read cannot be done on Simos 8.5

**Every door is shut over OBD, for different reasons.**

### 3a. Door 1 (SBOOT) is bench by construction
The 8.5 SBOOT exploit exists ([fastboatster/Simos8_SBOOT]) but its entry gate is the
**PWM-on-boot-pins + reset** measurement (§1). The OBD bus cannot generate a reset-time GPTA
waveform on the boot pins. Door 1 never produces an OBD read on *any* of these parts.

### 3b. Door 2 (patch-and-read) has no key ingredient on 8.5
Patch-and-read needs the **write-unsigned-code** primitive (§2 ingredient 2). On 8.5 that
primitive **does not exist over OBD**:

- **Writes are RSA-1024 signed and the check lives in the boot sector.**
  `analysis/RE_findings_checksum.md`: RSA-1024, exponent `0x10001`, key ids **`0x73`**
  (SW-component/reprogramming signature), `0x6E` (supplier repro auth), `0x74` (switchover).
  Verification is **in SBOOT/CBOOT**, the `0x0–0x20000` region **blank/protected in every
  OBD read**. You can't forge RSA-1024; defeating it needs a *logic* flaw in the verifier —
  the class of bug bri3d found in Simos18. **No such OBD-reachable flaw is known for the 8.5
  loader.** (Key ids `0x73/0x6E/0x74` gate **writing**; the SBOOT challenge key `0x96` in §1
  gates the **boot challenge** — different keys, different doors.)
- **The accepted OBD write path is signed-only**, which §6 confirms in the firmware: the
  reflash path streams into a fixed RAM buffer and CRC-16-validates predetermined flash
  blocks — it takes **no caller-supplied arbitrary address** and accepts **no unsigned ASW
  code**. Fine for flashing cal; useless for patch-and-read.

### 3c. Door 3 (CCP/XCP) does not exist on 8.5
No measurement slave is present (§6). So there is no ungated `UPLOAD` to abuse.

**Conclusion.** 8.5 fails limb (a) *and* limb (b): no stock read-by-address/upload service,
no CCP/XCP, and no way to run your own reader. Therefore **no OBD port read** — exactly the
market reality (8.5 listed `VR`, not `RD`).

---

## 4. Could Door 2 be built for 8.5? (the only OBD-read route, and its chicken-and-egg)

To create a genuine OBD read for 8.5 you would reproduce bri3d's Simos18 Door-2 chain
against the 8.5 loader (all **inference**):

1. **Get the boot sector first — via the bench SBOOT exploit (§1).** You cannot look for a
   signature-verifier flaw in code you don't have, and `0x0–0x20000` is blank in every OBD
   read. This is the repo's standing TODO and the unavoidable first step.
2. **Reverse the OBD reflash authentication + RSA/CRC verifier** in that boot code and find a
   *logic* bug that admits unsigned/patched ASW over UDS. May not exist — the 8.5 loader is
   an older, different (Continental/TC1796) codebase, not Simos18.
3. **Install a reader stub over OBD** and stream flash back.

**Why it "can't currently be done":** step 2 is gated on step 1's bench dump, which is only a
partial/unproven port for 8.5; and no signature-verifier break for the 8.5 OBD path is
published. Until both land: **OBD read of 8.5 = not available; bench SBOOT is the only route
to a full image.** (Pcmflash's 8.6 "unlock in BSL" is a *fourth* mechanism — rewriting an
external SPI **EEPROM** lock bit on the bench — closed, not a signature break, no help to
8.5.)

---

## 5. Door 3 — the CCP/XCP measurement vector (the "AL551" dump)

A third OBD-read avenue exists in principle and is **not** covered by the §2 signature-bypass
logic, so it deserves its own treatment. It is how ECUs like the AL551 TCU are dumped
([andiradulescu/openpilot CCP reader]).

**What it is.** CCP (CAN Calibration Protocol) and its successor XCP are ASAM measurement/
calibration protocols an ECU runs on a dedicated CAN mailbox pair (CRO command / DTO
response) so tools like INCA/CANape can read and write live memory against an A2L. The read
primitive is trivial: `CONNECT` → `SET_MTA(addr)` → `UPLOAD(n)`, which copies memory straight
out. Because it reads the raw address space, an `UPLOAD` dump includes **the boot sector that
UDS/Pcmflash reads omit** — the AL551 dump pulled SBOOT/CBOOT/ASW/CAL this way.

**Why it's a distinct door.** It needs **no signature bypass and no code execution** — just a
slave that (a) is present in production firmware and (b) does not gate `UPLOAD` behind a
`GET_SEED`/`UNLOCK` you don't have. The AL551's `UPLOAD` was ungated; that is a per-firmware
config choice, not a protocol guarantee.

**Correction to §2.** The earlier framing treated the OBD read as impossible without a
signature bypass. That is the Door-2 story; Door 3 is a second OBD avenue the signature
argument doesn't touch. The reason 8.5 still has no OBD read is **not** that Door 3 is
theoretically closed — it is that Door 3 is **empirically absent** on this ECU (§6).

**Command bytes** (so the §6 search is auditable): CCP CRO byte[0] `CONNECT=0x01,
SET_MTA=0x02, DNLOAD=0x03, UPLOAD=0x04, SHORT_UP=0x0F, GET_SEED=0x12, UNLOCK=0x13`. XCP byte[0]
`CONNECT=0xFF, GET_SEED=0xF8, UNLOCK=0xF7, SET_MTA=0xF6, UPLOAD=0xF5, SHORT_UPLOAD=0xF4`.

---

## 6. The 8.5 CAN read surface — static findings (reproduced decompiles)

Static analysis of the reproduced corpus (`analysis/decompiles_r/`, 7265 functions,
regenerable via `reproduce.sh`; gitignored). Function names are `llm` hypotheses unless the
`source` column says otherwise, so the **addresses** are the durable evidence, not the names.

### 6a. Door 3 is absent — no CCP/XCP slave (definitive)
- **No CCP/XCP symbols or structures.** Nothing in `symbols_merged.csv` names ccp/xcp/mta/
  daq/odt; no MTA pointer-latch, no DAQ/ODT lists.
- **No command-byte dispatch.** Every occurrence of the XCP bytes `0xF3–0xF8`/`0xFF` and CCP
  `0x02/0x04` is a bitmask, an event/DTC id, an array index, or an E2E complement sentinel —
  never a switch on a received CAN payload byte. There is **no `SET_MTA`→`UPLOAD`
  memcpy-to-mailbox** anywhere.
- **CAN RX is 100% COM-table-driven.** The acceptance filter `@0x80082f18` admits only
  powertrain IDs (`0x100–0x17f`, see `maps/can_signal_map.md`); the only non-powertrain
  traffic is diagnostic ISO-TP (`0x70a/0x719/0x71a`) routed through the generic COM stack
  (`com_process_ipdu`@`800af8bc`). No raw non-COM mailbox reads a frame and switches on
  `data[0]` to build a response — the defining shape of a CCP/XCP slave.

⇒ **There is no ungated `UPLOAD` to abuse. The only request/response memory path on CAN is
UDS.**

### 6b. The UDS read surface — no read-by-address, no upload
The diagnostic stack is a Continental generic **table-driven** implementation: services
dispatch through function-pointer tables (`handle_diagnostic_request`@`800b3e6e`, gate
`8002c3c4`) whose SID→handler map and per-service session/security bytes live in **RAM/RODATA
config not present in the function decompiles** — Ghidra reports "Could not recover jumptable
… Too many branches." So the master SID list can't be read directly; the findings below rest
on the **absence of any handler body** implementing a service across all 7265 functions, plus
the transfer module being write-only.

| UDS service | On 8.5? | Reads memory? | Gating | Evidence (fn addr) |
|---|---|---|---|---|
| `0x23` ReadMemoryByAddress | **absent** | — | — | no handler in 7265 fns; all `==0x23` are string/state/map indices |
| `0x35` RequestUpload | **absent** | — | — | no handler; transfer module is write-direction only |
| `0x34/0x36/0x37` Download/TransferData/TransferExit | present | **writes only** | programming session + security (NRC `0x33`) | `801d1ebe` (validates 0x1e00-byte block: `crc16(data+4,len,0xABCD)==word[0x1dfa]`), `801d22a0`, `800a59f0` (verified), flash driver `801f13b8` (staging buf `0xc03fd3d0`), `801f3b5e` (req→RAM→flash), `801d371c` (programming executor) |
| `0x22` ReadDataByIdentifier | present | **fixed DIDs only** | session-gated | `8011fc40…`→`801dbd84`; DIDs `0x2e0,0x2ed,0x2ee,0x2ef,0x2f9,0x2ff` (versions/CRCs/part-ids) |
| `0x2e` WriteDataByIdentifier | present | writes whitelisted DIDs | NRC `0x33` if unsecured, NRC `0x31` off-list | `801229b4` (whitelist `0x2e1,0x310,0x319,0x4fc,0x4fe,0x600,0x927,0x937,0x444b,0xf198,0xf19e,0xf1a2,0xf1f0,0xf1f1`) |
| `0x27` SecurityAccess | present (the gate) | n/a | — | access gate `8002c3c4` (NRC `0x11` unless session/security bits); per-service byte `entry[3]` @`8002c65e`; **seed/key algorithm + level table in RODATA — unresolved** |

Key structural facts:
- **The only "arbitrary" data motion is INTO flash, never OUT.** TransferData lands in a
  fixed RAM staging buffer (`0xc03fd3d0`) and flashing is driven by a config table at
  `0x800826c0` with per-block CRC-16 (`0xABCD`) — **predetermined programmable regions, not a
  caller-supplied address argument.** So even the write path can't be inverted into a reader.
- **`0x22` is the only service that returns bytes, and it returns fixed identifier payloads**
  (SW versions, CRCs, part numbers) — not memory-by-address. This is what a tool reads to
  *identify* the box for a **virtual read**, which is the whole VR mechanism.
- **Everything is session+security gated** (NRC `0x33 securityAccessDenied` when the
  session/security bitmask `& 0xf == 0`).

### 6c. Two naming corrections surfaced by this pass (fix in `symbols_merged.csv` when tracing)
- `handle_uds_command`@`800aa922` is **not** UDS — it is a **GPTA/PCP timer-channel
  dispatcher** (`DAT_d0000580` is filled with GPTA0 timer config by `801cd388`). `param & 0x3f`
  is a timer channel, not a SID. The real diagnostic router is `800b3e6e`/`8002c3c4`.
- `read_memory_value`@`800a2c54` is a **2-D calibration-table indexer** (`base + row*width +
  col`), not an address-based memory read.

### 6d. What remains in RODATA (honest static limit)
Not resolvable from the function set alone, and where a determined analyst would go next:
the **SID→handler dispatch table** and **per-service security-level bytes** (behind
`DAT_d00005c8` / the `param_1[7]` diagnostic context), the **`0x27` seed/key algorithm,
level list, and attempt/delay limiter**, and the **`0x800826c0` flash-config table's exact
writable window**. These live in const/RAM tables, reachable by decoding the diagnostic-init
that populates them or by resolving the recovered-jumptable targets in the raw image — not by
reading more C. **The step-by-step recovery plan (anchors, techniques, new `ResolveDispatchTables`
pass, sequencing) is in `uds_dispatch_recovery.md`.** None of this changes the read conclusion:
**no `0x23`, no `0x35`, no CCP/XCP → no CAN path returns arbitrary flash → VR, not RD.**

---

## Sources
- Repo: `ecus/simos85/README.md`, `analysis/RE_findings_checksum.md`,
  `analysis/cal_read_method.md`, `maps/can_signal_map.md`, `docs/methodology.md`; findings in
  §6 from the reproduced `analysis/decompiles_r/` (regenerable, gitignored).
- [bri3d/Simos18_SBOOT] · [bri3d/TC1791_CAN_BSL] · [bri3d/VW_Flash] ·
  [fastboatster/Simos8_SBOOT] · [fastboatster/TC1796_CAN_BSL]
- [andiradulescu/openpilot CCP reader] (the AL551 CCP `SET_MTA`+`UPLOAD` dump)
- Pcmflash module 57 instructions — https://remaptools.com/instruction-pcm-m57/

[bri3d/Simos18_SBOOT]: https://github.com/bri3d/Simos18_SBOOT
[bri3d/TC1791_CAN_BSL]: https://github.com/bri3d/TC1791_CAN_BSL
[bri3d/VW_Flash]: https://github.com/bri3d/VW_Flash
[fastboatster/Simos8_SBOOT]: https://github.com/fastboatster/Simos8_SBOOT
[fastboatster/TC1796_CAN_BSL]: https://github.com/fastboatster/TC1796_CAN_BSL
[andiradulescu/openpilot CCP reader]: https://github.com/andiradulescu/openpilot/commit/e12723c1759e0d77b83c9b198c163645e5310913
