# Base ESP/ABS hydraulic path — does an external/EPB brake request enter it? (fork, 2026-09-02)

Goal: find the base ESP/ABS active-pressure controller (separate from ECD) and any external/EPB
deceleration-request input. Result: **base hydraulic MMIO not reached (behind HW-ISR indirection);
NO external/EPB request input found in the reachable actuation thread.**

## Traced chain (proven, code)
- ECD setpoints `0x403d94` are read ONLY inside the ECD subsystem (`ecd_decel_pressure_calc` peak-
  track); they reach the actuator via the ctrl-struct pointer, not by address. ECD is self-contained.
- ECD executor `FUN_0009d75c`: runs the ECD pipeline (`ecd_actuation_pipeline` 0x9f190) **only when**
  ctrl `+0x5a` bit10 set, then calls `FUN_000a0da0` **unconditionally**.
- `FUN_000a0da0` → terminal drivers: `FUN_000a1d98`/`a1db0` (ECD-gated) and `FUN_000a1d88`
  (unconditional) → `FUN_00070ec0`.
- `FUN_00070ec0` is a **CAN-TX status packer** (scales an internal pressure value, packs a 16-bit
  field + a CRC via the XOR table at `DAT_000711d8`), **not** a valve/pump driver.

## Conclusion
- The reachable ECD-actuation thread has **no external/driver/EPB pressure-request input** — consistent
  with the parent's exhaustive ECD result.
- The actual base ABS/ESC valve+pump MMIO driver is a **separate main-loop subsystem** whose terminal
  writes are behind RAM-ptr / HW-ISR indirection (peripheral space `0xfff7xxxx`); it was not reachable
  within this bounded pass, so an external-request input there can be **neither confirmed nor excluded**.
- No EPB (handle 0x25b) hydraulic path found. **Evidence (not proof) leans toward: this variant does
  NOT expose an autonomous ESP-hydraulic external brake-request interface beyond the 4 ECD decel
  sources** — which would mean lever-hold dynamic braking is not an ESP-hydraulic feature here.

## Next (for the parent)
Reaching the base ABS/ESC pressure arbitration needs the main hydraulic control loop (yaw/slip), a large
subsystem not entered here; or the terminal MMIO map (needs SBOOT/emulation of the HW-ISR indirection).
