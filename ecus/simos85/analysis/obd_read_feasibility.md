# Simos 8.5 — external read paths, and why there is no OBD "port" read

Scope: how the firmware image is obtained *from outside* the ECU (not the internal
cal-read mechanics in `cal_read_method.md`). Answers three linked questions:

1. How the Simos18 SBOOT exploit works and whether it does *actual* reads.
2. Whether that approach can be adapted to run over OBD instead of on the bench.
3. Why a Simos18-style **OBD** full-flash read does **not** exist for Simos 8.5 —
   grounded in this pack's own integrity findings.

Established facts are cited to repo files or primary sources; the rest is labelled
**inference**. Nothing here has been run against a car.

---

## 0. Two different doors (this is the whole point)

Getting firmware *out* of one of these ECUs uses one of two fundamentally
different attack surfaces. They are constantly conflated ("unlock"), but they
have nothing in common:

| | **Door 1 — SBOOT / boot exploit** | **Door 2 — OBD application unlock** |
|---|---|---|
| Target | the *bootloader* (SBOOT/CBOOT), before the app runs | the *running application* (ASW) + its UDS stack |
| Entry vector | boot pins: PWM on GPTA + reset / HWCFG | UDS over CAN via the OBD port |
| Physical access | **bench** — open ECU, probe/solder vias | **none** — plug into the OBD connector |
| Yields | full flash incl. boot sector | whatever the app exposes / whatever you can install |

The SBOOT exploit is **Door 1**. An "OBD read" is **Door 2**. You cannot walk
through Door 1 over OBD — not because the port is slow, but because the *entry
condition physically isn't a bus message* (see §1). So "adapt the SBOOT exploit
to OBD" is a category error; the real question is whether **Door 2** can be built
for 8.5 (§4).

---

## 1. How the Simos18 SBOOT exploit works — and yes, it does real reads

Source: [bri3d/Simos18_SBOOT], [bri3d/TC1791_CAN_BSL], and the TC1796 port
[fastboatster/Simos8_SBOOT] / [fastboatster/TC1796_CAN_BSL].

**Entry (bench, pins — not a bus feature).** SBOOT decides whether to drop into
its "recovery shell" by *measuring a PWM waveform on two harness pins with the
GPTA at reset* — two 3.2 kHz squares phase-shifted a quarter period (a
`235.2 µs` pin1→pin2 and `312 µs` pin2→pin2 timing). Only *after* that timing
gate passes does it accept CAN messages (`59 45` → `0xA0`, then `6B`) and enter
recovery. So CAN is used *inside* the exploit, but the **gate that makes SBOOT
listen at all is a physical pin/reset event** the OBD connector cannot assert.
This is why every write-up calls it bench-only ("probe or solder to several very
small vias").

**The exploit chain, once in recovery:**
1. **Seed/key bypass.** The challenge RNG is a Mersenne Twister **seeded from the
   system timer (STM)** — predictable, not entropy. Constrain the seed by
   controlling timing, then brute the remainder (~`2^31`, ~500k pairs/s/core)
   until a key decrypts to the seed. (On 8.5 the challenge uses a **1024-bit RSA
   key id `0x96`**, so only 128 bytes of seed material vs 256 on Simos18 —
   [fastboatster/Simos8_SBOOT].)
2. **CRC bounds-check leak.** The SBOOT CRC routine has weak bounds checking; ask
   it to checksum the **boot-password region** and return the CRC. CRC is
   reversible, so back-calculate the passwords (`crchack`/`twister`) from four CRC
   values harvested over ~2 min of reset-cycling.
3. **Passwords → BSL.** TC179x stores a 16-byte blob in the User Configuration
   Blocks: **first 8 bytes = read passwords, second 8 = write passwords**. Feed
   them to the CAN Bootstrap Loader and flash unlocks.

**Does it do actual reads? Yes — the fullest possible.** Once the BSL has the
passwords it does **arbitrary flash read/write/erase, including the boot sector**
that OBD never returns. This is the *only* known way to obtain Simos 8.5
`0x0–0x20000` (the region this repo marks **blank in OBD read** —
`README.md`, `analysis/RE_findings_checksum.md`, `docs/methodology.md`). It is
also exactly this pack's open TODO ("obtain a bench/boot read to study
SBOOT/CBOOT").

**Status for 8.5:** the port is real but the authors' own words are "humble
attempt" / "partial implementation" — no clean end-to-end 8.5 dump is published.
8.4 needs different pin connections than 8.5 ([fastboatster/TC1796_CAN_BSL]).

---

## 2. What a Simos18 *OBD* read actually is (Door 2)

The SBOOT exploit is **not** what gives Simos18 its OBD read. The OBD read is a
separate application-layer capability with two ingredients:

1. **Programming-session security access is computable.** The VAG "SA2" seed/key
   is a bytecode routine shipped *inside the ODX/FRF flash container*
   ([bri3d/VW_Flash], `sa2-seed-key`). Anyone with the container can answer the
   security-access challenge — this opens the programming session (write path).
2. **An RSA-signature bypass lets you write *unsigned* application code over
   UDS.** This is bri3d's core Simos18 contribution: defeat the signed-flash
   check so a modified/unsigned ASW is accepted over the ordinary OBD reflash
   (`RequestDownload`/`TransferData`).

Put together, Door 2 becomes **patch-and-read**: over OBD you write your own code
(or a patched routine) into the ECU, run it, and have *it* stream flash back —
e.g. via `$23 ReadMemoryByAddress`, which the Simos18 ASW already exposes for
logging (`simos_hsl.py`: `$23` / `$2C` / a proprietary `$3E` patch —
[bri3d/VW_Flash]). The "read" is a *consequence of being able to run your own
code over OBD*, not a native "dump firmware" service.

**Inference (load-bearing):** an OBD full-flash read requires **either**
(a) a stock service that returns the full flash, **or** (b) the ability to run
attacker code on the ECU over OBD — and (b) requires defeating the write-time
signature check. Simos18 has (b). Hold onto this test for §3–4.

---

## 3. Why the same OBD read cannot be done on Simos 8.5

Apply the §2 test to 8.5. **Both doors are shut over OBD, for different reasons.**

### 3a. Door 1 (SBOOT) is bench by construction
The 8.5 SBOOT exploit exists ([fastboatster/Simos8_SBOOT]) but its entry gate is
the **PWM-on-boot-pins + reset** measurement (§1). The OBD bus cannot generate a
reset-time GPTA waveform on the boot pins. No amount of protocol work moves this
to OBD — it is the same wall Simos18 has. Door 1 never produces an OBD read on
*any* of these parts.

### 3b. Door 2 (patch-and-read) has no key ingredient on 8.5
Patch-and-read needs the **write-unsigned-code** primitive (§2 ingredient 2).
On 8.5 that primitive **does not exist over OBD**, and this pack already
documents why:

- **Writes are RSA-1024 signed and the check lives in the boot sector.**
  `analysis/RE_findings_checksum.md`: RSA-1024, public exponent `0x10001`, key ids
  **`0x73`** (SW-component/reprogramming signature), `0x6E` (supplier reprogramming
  auth), `0x74` (switchover). Signature verification is **in SBOOT/CBOOT**, the
  `0x0–0x20000` region that is **blank/protected in every OBD read**.
  - You can't forge an RSA-1024 signature. Defeating it needs a *logic* flaw in
    the verifier (bounds/ordering/TOCTOU/partial-verify) — the same class of bug
    bri3d found in Simos18. **No such OBD-reachable flaw is known for the 8.5
    loader.**
  - Note the key ids differ from the SBOOT challenge key `0x96` in §1: `0x73/0x6E/
    0x74` gate **writing**; `0x96` gates the **boot challenge**. Different keys,
    different doors — do not conflate them.
- **The accepted OBD write path is signed-only, and that's fine for tuning.**
  A modified *calibration* flashed via Pcmflash/OBD is accepted because integrity
  is enforced at write time by the resident loader (streamed CRC-16, poly `0xA001`,
  init `0xABCD`) — **there is no in-file cal checksum** and no static signature over
  cal to defeat (`README.md`, `RE_findings_checksum.md`). But this only lets you
  write **cal that passes the loader's checks**; it does **not** let you write
  **arbitrary/unsigned ASW code**, which is what patch-and-read requires.
- **The stock 8.5 application exposes no full-flash read service.** It is
  read-protected; this is precisely why commercial tools fall back to *virtual
  read* (serve the matching stock file from a DB) rather than a real dump. No
  native `$23`/upload path returns the whole flash.

**Conclusion.** 8.5 fails **both** limbs of the §2 test over OBD: no stock
full-read service, and no way to run your own reader (the signature bypass that
would enable it is unbroken and lives in a boot region nobody has dumped over
OBD). Therefore **no OBD port read** — exactly the market reality (8.5 listed
`VR`, not `RD`). The Continental Simos8 loaders were simply never given a public
OBD code-injection break equivalent to bri3d's Simos18 work.

---

## 4. Could Door 2 be built for 8.5? (the only OBD-read route, and its chicken-and-egg)

To create a genuine OBD read for 8.5 you would have to reproduce bri3d's Simos18
Door-2 chain against the 8.5 loader. Concretely (all **inference**):

1. **Get the boot sector first — via the bench SBOOT exploit (§1).** You cannot
   look for a signature-verifier flaw in code you don't have, and `0x0–0x20000`
   is blank in every OBD read. This is the repo's standing TODO and the
   unavoidable first step.
2. **Reverse the OBD reflash authentication + RSA/CRC verifier** in that boot
   code and find a *logic* bug that admits unsigned/patched ASW over UDS
   (analogue of bri3d's Simos18 bypass). May not exist — the 8.5 loader is an
   older, different (Continental/TC1796) codebase, not Simos18.
3. **Install a reader stub over OBD** and stream flash back (`$23`/`$36`/logger).

**Why it "can't currently be done":** step 2 is gated on step 1's bench dump,
which itself is only a partial/unproven port for 8.5; and no one has published a
signature-verifier break for the 8.5 OBD path. Until both land, the honest status
is: **OBD read of 8.5 = not available; bench SBOOT is the only route to a full
image, boot sector included.** (For comparison, Pcmflash's 8.6 "unlock in BSL" is
yet a *third* mechanism — rewriting an external SPI **EEPROM** lock state on the
bench — closed, and not a signature break, so it doesn't help 8.5 either.)

---

## Sources
- Repo: `ecus/simos85/README.md`, `ecus/simos85/analysis/RE_findings_checksum.md`,
  `ecus/simos85/analysis/cal_read_method.md`, `docs/methodology.md`.
- [bri3d/Simos18_SBOOT] — https://github.com/bri3d/Simos18_SBOOT
- [bri3d/TC1791_CAN_BSL] — https://github.com/bri3d/TC1791_CAN_BSL
- [bri3d/VW_Flash] — https://github.com/bri3d/VW_Flash
- [fastboatster/Simos8_SBOOT] — https://github.com/fastboatster/Simos8_SBOOT
- [fastboatster/TC1796_CAN_BSL] — https://github.com/fastboatster/TC1796_CAN_BSL
- Pcmflash module 57 instructions — https://remaptools.com/instruction-pcm-m57/

[bri3d/Simos18_SBOOT]: https://github.com/bri3d/Simos18_SBOOT
[bri3d/TC1791_CAN_BSL]: https://github.com/bri3d/TC1791_CAN_BSL
[bri3d/VW_Flash]: https://github.com/bri3d/VW_Flash
[fastboatster/Simos8_SBOOT]: https://github.com/fastboatster/Simos8_SBOOT
[fastboatster/TC1796_CAN_BSL]: https://github.com/fastboatster/TC1796_CAN_BSL
