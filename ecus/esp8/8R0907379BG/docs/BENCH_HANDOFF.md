# ESP8 ABS bench — session handoff (Linux → Windows)

Spare **Bosch ESP8 quattro, 8R0907379BG** (B8 Q5 ABS) on the bench. Goal: establish UDS,
test flashing, work toward SBOOT. Read this first, then the linked docs.

## Hardware / wiring (unchanged on any tool)
- Connector **T38a (38-pin)**. Full map: `bench_harness_pinout.md`.
- Bench harness = 5 wires: **B+ (term30) pins 1,7,25**; **term15 pins 35,32**; **GND pins 13,38**;
  **CAN-H pin 37**; **CAN-L pin 24**. 500 kbps. 120 Ω term (ABS provides one end).
- Single CAN pair = the chassis/sensor CAN (no gateway on the bench → address the ABS directly).
- Powerup: BATT+/12V first (term30), then tool drives VCC (term15) to wake the ECU.

## Tool status
- **Scanmatik SM2 Pro (USB 0x20A2:0x0001):** on Linux the open-source `sm2can` driver drives the
  USB/system layer fine (INIT/ECHO/DEVICE_INFO all OK, HW_ID 88 17 11, HW rev 3.2), BUT its **CAN
  channel layer is unimplemented — CAN_OPEN NACKs** (the CAN command encodings are unknown/guessed;
  repo spec lists them as Unknown). So no CAN over SM2CAN on Linux yet.
- **On WINDOWS the SM2 Pro works natively** via Scanmatik's official J2534 driver — this is the
  reason to move to Windows. Use with PCMflash / ODIS.
- **Openport clone** works fully on Linux (VW_Flash, ISO-TP+UDS) as a Linux alternative.

## Firmware findings (from the ASW+CAL image; we do NOT have SBOOT/CBOOT)
- **The ASW does NOT implement UDS 0x23 ReadMemoryByAddress.** Exposed services = 0x22 DID
  (identity/coding only), 0x19 DTC, routine/checksum, response TX. No arbitrary memory read.
  (`uds_read_primitive.md`, SESSION CONCLUSION.) Memory-read + programming security are
  bootloader-resident, like the sibling AL551 TCU.
- **ASW + CAL are each RSA-1024 signed** (`signature_analysis.md`). Cannot re-sign. A patched flash
  needs a CBOOT/SBOOT bypass, not a re-sign.
- **SBOOT is not in the image** and can't be read via ASW UDS. The unit is a bare-die chip-on-board
  hybrid with no JTAG breakout, so a hardware dump is hard; a bootloader image from another source
  is the unlock.
- First on-bench comms test: session `0x10 0x02`, physical req **0x713** / resp **0x77D**, 500 kbps;
  if silent scan 0x700–0x7FF, retry 100 kbps.

## Windows setup
1. Install **Claude Code for Windows**, then `git clone git@github.com:oscarmcnulty/vag-ecu-re.git`
   (or pull) — all docs travel with the repo; open this file first.
2. Install **Scanmatik software** (bundles the J2534 driver), **PCMflash**, **ODIS-Engineering**.
3. Register the Scanmatik J2534 device in PCMflash/ODIS; wire T38a per above; power up.
4. Confirm comms (0x713/0x77D), then: check whether **PCMflash lists this exact part (8R0907379BG /
   Bosch ESP8)** and whether it flags it OBD vs bench-boot — that reveals whether ESP8 boot is
   checksum-gated (easy) or RSA-gated (needs bench/exploit).
5. Optional, to finish the Linux `sm2can` CAN layer later: run **USBPcap + Wireshark** while the
   Scanmatik software opens a 500 kbps channel and sends a few frames; that capture pins the real
   CAN_OPEN/SEND/READ encoding.

## What does NOT auto-transfer
- The live Claude conversation (sessions are local to `~/.claude`). The repo docs + this handoff are
  the portable record. Memory files at `~/.claude/projects/.../memory/` can be copied but the repo
  is the reliable carrier.
- Firmware images are gitignored (won't push). Not needed for the Windows tool work; copy separately
  only if you want to continue offline RE on Windows.
