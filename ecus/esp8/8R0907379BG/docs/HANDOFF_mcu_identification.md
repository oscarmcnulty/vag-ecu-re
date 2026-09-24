# Cloud handoff — identify the ESP8 ABS microcontroller (and the flash-dump path)

You are continuing reverse-engineering of a **Bosch ESP8 quattro ABS/ESP, Audi B8 Q5, part
`8R0907379BG`** (the owner's own vehicle + a spare/donor unit). Read `CLAUDE.md`, then
`ecus/esp8/8R0907379BG/variant.conf`, `ecu.conf`, and the docs referenced below. **Reproduce the
firmware + Ghidra project first** (`source .env.sh && ecus/esp8/8R0907379BG/reproduce.sh`, Ghidra
12.1.2 + JDK 21; see CLAUDE.md for the container setup). Firmware is gitignored — only metadata is
committed.

## Why this matters (goal chain)

openpilot longitudinal/standstill on the Q5 needs to understand — and eventually modify — the ABS.
Modifying flash requires defeating its integrity checks. We have established:

- **Flash integrity over the ASW+CAL image is RSA-1024 only** — no recomputable checksum layer a
  flasher could correct (proven: `decode/flash_checksum_probe.py`; CSV labels
  `esp8_sig1_descriptor_asw`/`esp8_sig2_descriptor_cal`; `docs/signature_analysis.md`). So a patched
  image needs a **bootloader (SBOOT/CBOOT) bypass**, and reversing the sign/checksum enforcement
  needs the **bootloader code, which is NOT in our image** (we have ASW+CAL only).
- Getting SBOOT/CBOOT is the blocker. Two routes: (a) **over-the-wire UDS read** on the bench, or
  (b) **hardware dump**. Both are open; see below.

## State of the two dump routes (build on this, don't redo)

**Route A — UDS over CAN (bench, non-destructive).** The ASW's own diagnostic service config
DECLARES the memory services — two byte-verified service tables (CSV `diag_service_table_kwp`
@0xb4be4, `diag_service_table_uds` @0xb4d80): **0x23 ReadMemoryByAddress, 0x35 RequestUpload, 0x3D
WriteMemoryByAddress**, + 0x34/0x36/0x37 transfer, 0x27 security. BUT the dispatch + executors are
**boot-installed** (function pointers patched at boot / in the seg2 Dcm stack, not statically
followable), and every statically-reachable handler reads only fixed/indexed data. So whether
0x23/0x35 actually answer, in which session, and whether their address check reaches the boot
region is **empirically open — bench-only** (`docs/uds_read_primitive.md`, memory
`esp8-uds-read-primitive`). Prog-security is bootloader-side; the SA2 seed/key algorithm is known
(memory `abs-sa2-key`, in the `.sgo`, computable via `sa2_seed_key`).

**Route B — hardware.** The unit is a **bare-die chip-on-board hybrid, fully potted (clear
encasement), no legible markings, no non-destructive JTAG bond-out** (prior die-level photo —
`docs/HANDOFF_wake_investigation.md`). We have a donor for destructive work. Feasibility of any
boot-pin/JTAG/BSL dump depends entirely on **which MCU this is** and whether its debug/BSL is
security-fused — which is the task below.

## YOUR TASK: identify the MCU rigorously (it is currently UNKNOWN)

Prior sessions only ever called it "the Bosch ASIC." A chat exploration floated **Freescale
MAC7100** (ARM7TDMI + FlexCAN, automotive) — but that was an anchored guess from a single generic
inference and is **NOT confirmed**. **Do not assert or commit any MCU identity until it is
confirmed against a primary datasheet/reference-manual memory map.** Treat MAC7100 as one
hypothesis among several.

### Firmware fingerprint (facts, from the RE)
- Core: **ARM, big-endian (BE32)**, Ghidra `ARM:BE:32:v5t`, mixed **classic ARM+Thumb**;
  `0xEAFFFFFE` (`B .`) vector fillers; ~40% of BE words have top nibble 0xE (ARM AL cond).
- **Flash at 0x0** (app image linked at 0x0; reset vector is a `B .` stub → real reset is in the
  absent SBOOT). Total image 0x134011 (~1.25 MB).
- **SRAM at 0x00400000** (used ~0x400800–0x407xxx).
- **Peripherals at 0xFFF7_xxxx**: two CAN controllers @ `0xFFF7E800`/`0xFFF7EA00` (mailbox regions
  0xFFF7E400/E600), valve/solenoid controllers 0xFFF7D400/D500, pump 0xFFF7F0A0, config
  0xFFF7EC00/F400. Config table `can_mailbox_config` @0xaea38 (stride 0x18) holds the bases; CAN
  arbitration word = standard-ID<<18.

### The differential — evaluate these, don't anchor
| Family | Core / endian | CAN IP | Notes |
|---|---|---|---|
| Freescale MAC7100 | ARM7TDMI, BE | FlexCAN | automotive; peripheral base UNVERIFIED against our 0xFFF7xxxx |
| **TI Hercules TMS570/RM4x** | Cortex-R4F, BE | **D_CAN** | THE automotive ABS/EPS/safety ARM-BE part; peripherals natively at 0xFFF7_xxxx; SRAM normally 0x08000000 |
| Freescale MPC5xxx/SPC5 | PowerPC, BE | FlexCAN | same peripheral style but **not ARM** → out |
| ST STR7/9, NXP LPC2000, Atmel SAM7 | ARM7/9, **LE** | bxCAN/CCAN | endian + map wrong → out |
| Bosch-custom ASIC (licensed ARM+CAN) | ARM, BE | ? | can't exclude; would explain no markings + flash-size/mailbox deviations |

Important corrections to carry forward: the `ID<<18` arbitration format does **NOT** distinguish
FlexCAN from D_CAN (it is the generic CAN 2.0B layout) — the CAN vendor is **not yet established**.
Our image (~1.25 MB) exceeds base-MAC7100's 1 MB, and module B carries ~50 mailboxes vs MAC7100's
32/module — so if Freescale, likely a derivative, or a Bosch-custom part.

### Decisive tests — all inside the firmware, no datasheet needed (do these FIRST)
1. **CAN register-access model** (the clean vendor discriminator): **FlexCAN** = a directly
   memory-mapped array of 16-byte message buffers (CS/ID/DATA) at `base+0x80`, with MCR/CTRL at
   base+0/+4; **D_CAN** = indirect access via **IF1/IF2 command+data registers** into a separate
   Message RAM. Find the code that drives `0xFFF7E800`/`0xFFF7EA00` (it's reached via the config
   table base pointers / HW-ISR indirection, not literals — you may need light emulation or to
   trace the mailbox-config consumers) and classify the access pattern → Freescale-FlexCAN vs
   TI/Bosch-D_CAN.
2. **Thumb encoding**: *classic* Thumb ⇒ ARM7/9 (MAC7100-class); **Thumb-2** (32-bit encodings) ⇒
   Cortex-R (Hercules). Check the Thumb stream (`decode/second_code_segment.py`, seg2 VMA=file+3).
3. **SRAM/vector/peripheral bases** vs each candidate's documented map. SRAM `0x00400000` argues
   against Hercules (0x08000000); confirm what family actually uses `0x00400000` SRAM +
   `0xFFF7_xxxx` peripherals.

Then cross-reference the surviving candidate(s) against the primary reference manual memory map
(FlexCAN/D_CAN base, SRAM base) to reach **100% before recording anything**. Sources tried and
currently hard to fetch: MAC7100 RM (NXP 404s the discontinued part; Internet Archive was offline —
retry it, and the Ronetix `arm7/mac7100.cfg` PEEDI config). Also viable: a CMSIS/SVD or
Lauterbach/CodeWarrior device file with the peripheral `#define`s. For TI Hercules the TRMs are
freely on ti.com.

### If/when identified, answer the dump-feasibility question
For the confirmed part: does it have a **BSL/boot mode** or JTAG that can read internal flash, and
is that interface **security-fused** in production? (E.g. Freescale CFM parts: secured → JTAG
disabled; unsecure = mass-erase unless a backdoor key is set — which destroys the firmware. TI
Hercules: check its debug-security/JTAG-lock. ) That determines whether the boot-pin/donor route
can yield SBOOT/CBOOT at all, or whether only fault-injection or a same-platform donor SBOOT image
remains.

## Constraints (hard)
- **Never commit firmware-derived artifacts** (firmware, decompiles, ghidra_proj). Only
  addresses/names/scripts. See CLAUDE.md.
- **Do not assert or commit an MCU identity until confirmed against a primary datasheet.** Record
  findings as CSV labels / concise doc updates stating only correct current understanding; no
  speculative markdown.
- Reproduce the firmware + Ghidra project before analysis; a clean run ends `done.` with
  `analysis/coverage.log`.

## File pointers
- `docs/signature_analysis.md`, `decode/flash_checksum_probe.py` — flash integrity = RSA-only.
- `docs/uds_read_primitive.md` + CSV `diag_service_table_kwp`/`_uds` — the declared UDS memory
  services + why they're empirically open.
- `docs/HANDOFF_wake_investigation.md` — the die-photo / no-bond-out hardware constraint.
- `docs/bench_harness_pinout.md`, memory `esp8-bench-pinout` — bench wiring (module A vs B CAN).
- `decode/rx_filter_table.py`, `decode/second_code_segment.py`, `emu/harness.py` — tooling.
- Memories (`~/.claude/.../memory/`): `esp8-abs-firmware`, `esp8-uds-read-primitive`,
  `esp8-flash-signature`, `abs-sa2-key`, `esp8-bench-pinout`.
