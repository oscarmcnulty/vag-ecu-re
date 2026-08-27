# Emulation findings (Unicorn ARM BE32) — 8R0907379BG

A function-level Unicorn harness (`emu/harness.py`) that maps flash+RAM+stack, auto-detects
ARM vs Thumb per entry, logs RAM writes and unmapped (MMIO) accesses, and calls any function
with args. Experiments in `emu/exp_*.py`. Setup: `python3 -m venv emu/.venv && emu/.venv/bin/pip
install unicorn capstone`.

## VALIDATED empirically (ground truth, not inference)
1. **Harness sanity** (`exp` in harness): `ecd_emergency_pressure` (0x9c788, Thumb) copies the ANB
   request value at 0x407c0a into all 6 setpoints 0x403d94[0..5]. PASS.
2. **Arbitration = MAX-wins, type ≡ mode** (`exp_arbitration.py`):
   - single type-4 (ANB) request 0x1000 → `ecd_mode`=**4**, primary_max=0x1000
   - type2=0x0800 vs type4=0x1500 → mode=**4** (larger wins); reversed → mode=**2**
   - single type-1 → mode=1. Exactly matches the static model.
3. **Full brake path** (`exp_fullpath.py`): type-4 request 0x1000 → `decel_ctrl_top` → `ecd_mode`=4
   → `ecd_state_machine` → **all 6 setpoints = 0x1000 (flat)** → `ecd_actuation_pipeline` runs and
   writes only RAM (0x408xxx). Confirms mode-4 ⇒ flat setpoints end-to-end.
4. **Calibration init** (`exp_calib.py`): `variant_cfg_select` (0x872cc) populates the calib
   pointers (0x40081c…) into flash calib blocks — per-variant at **0xb0510 / 0xb0bc4 / 0xb1278 /
   0xb192c** for codes 6/10/0x10/0x11. So calibration lives at 0xb0510–0xb1fbc, selected by variant.

## The two boundaries — why even emulation can't fully close them from THIS image
- **Reset vector @0x0 = `b #0` (self-loop filler).** The **SBOOT bootloader is absent** from this ASW
  image (consistent with the FRF lacking SBOOT). SBOOT is what (a) initializes the peripheral/SFR
  block and (b) populates the runtime COM buffer pointers. Therefore:
  - **Peripheral/valve MMIO map cannot be recovered by boot-emulation** — there is no boot code here
    to watch configure the SFRs. The `ecd_actuation_pipeline` computes pressure demands into RAM
    (0x408xxx); the valve/pump driver is a **separate high-rate task** not reached from that entry,
    and its MMIO target is set up by SBOOT.
  - **The per-message CAN→signal buffer binding** depends on the same runtime COM buffer pointers.
- To close either: obtain **SBOOT** (bench/BDM dump — see [[esp8-abs-firmware]]) and emulate the full
  boot, or use JTAG/BDM on a live ECU. Static analysis + ASW-only emulation cannot.

## Bottom line for openpilot
The **control behaviour** — which message brakes, gated vs not, priority, ramp vs flat, and that
ACC_10/ANB drives a flat mode-4 step below 15 km/h — is now **empirically proven**, not just traced.
That is what the below-15 smoothing work needs. The unresolved edges (exact solenoid registers,
per-signal CAN binding) are blocked by the missing SBOOT, not by analysis effort.
