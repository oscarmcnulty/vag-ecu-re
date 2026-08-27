# Dynamic Steering (J792) — Audi "Dynamiklenkung" (8K0907144L)

Reverse-engineering pack for the **Audi B8 Active/Dynamic Steering (superposition angle actuator)** control
unit (EPS/SCU). Single image so far:

| part | SW | build | supplier | project |
|---|---|---|---|---|
| `8K0907144L` | `0720` | 2013-01-02 | ZF Lenksysteme ("Servolectric") | `SCU_B8` / `ADS_B8_4` |

## Architecture (established from the image, not assumed)

**Renesas / NEC V850 (V850E), little-endian, load base `0x00000000`.**

The `.sgo` *container* is identical to the Bosch ESP8 ABS one (`ecus/esp8`) — `SGML Object
File`, whole file XOR-`0xFF`, 0x200 header — but the container says nothing about the core:
the ABS is ARM/BE32, the engine ECUs are TriCore, and this EPS is V850. Proof:

- The header/cal ASCII decodes under XOR-`0xFF` (part# `8K0907144L`, `0720`, the ZF strings,
  a full German K-Line debug monitor, the `KFC_*` fault enum, the state-machine names).
- A little-endian **data-pointer table** (just before the `KFC_*` block) decodes to flash
  addresses `0x000xxxxx` **and** RAM addresses `0x03FFxxxx` — the textbook V850 on-chip
  RAM/peripheral window, and exactly the `0x03FF0000` the ECU's own debug monitor writes
  to (`wr 0x03FF0000 ...`).
- Disassembly shows V850-only opcodes: `callt`, `switch`, 3-operand `movhi` split
  immediates (why no absolute string pointers exist), `sld/sst [ep]`, `satadd/satsubr/mulh`
  (motor-control DSP). Ghidra `V850:LE:32:default`, 0 invalid over long runs.

See `docs/RE_findings.md` for the full arch-ID trail (every other candidate — TriCore, PPC
VLE, SuperH, ARM, MIPS — was tested and rejected on decode self-consistency).

## Reproduce

```bash
source ../../.env.sh                       # JDK 21 + Ghidra 12.1.2
python3 extract_sgo.py <the>.sgo -o firmware/8K0907144L_0720.bin   # XOR-0xFF, strip 0x200
./reproduce.sh                             # -> ghidra_proj/ + analysis/ (both gitignored)
```

Parameters live in `ecu.conf`; the driver is the shared `core/pipeline/reproduce.sh`.
Firmware, the Ghidra project and decompiled C are **derived work → gitignored**; only
metadata (this pack's config, scripts, docs, and any confirmed symbol CSV) is committed.

## Why this ECU

Part of the openpilot-on-Q5 effort (`[[openpilot-integration-goal]]`): the EPS is the
steering actuator, so its handling of an **external steering-torque request** and the
**limits** it enforces (saturation, rate, hold-time cutout) are what govern whether a
spoofed lane-keep torque is accepted. See `docs/torque_limit.md`.
