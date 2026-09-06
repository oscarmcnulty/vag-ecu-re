# Boot / config-init emulation for object-table materialization — RESULT

Goal: model the SBOOT SVCs, boot far enough for the COM object table (`*0x4069b4`) to
materialize in emulated RAM, then dump handle->buffer (esp. EPB = handle `0x25b` / CAN `0x104`).
Script: `emu/exp_boot_svc.py`.

## Approach A (full boot from _start 0x8f440, SVCs modeled) — DEFINITIVELY BLOCKED

Modeled the crt0 SVCs in the Unicorn intr hook (decode imm from the svc at `pc-4`; return the
loop-exit sentinel `-1` for the context calls `#0xff10`/`#0x7f10`, `0` for the mode calls
`#0x13`-`#0x16`). With that, crt0 completes its mode/exception setup in exactly **6 SVCs**
(`0x15, 0xff10, 0x7f10, 0xff10, 0x7f10, 0x16`) — but then hands off via **`bx sp`** to an address
SBOOT is supposed to have placed in SP/context. That target is not set (SBOOT absent), so execution
branches to `0x0`, whose reset vector is `b #0` (self-loop). It never reaches `main`/COM-init and
`*0x4069b4` stays 0.

**Root cause (firm):** the ASW boot is SBOOT-context-dependent by design. crt0 (`0x8f440`) transfers
control through `bx sp` to SBOOT-provided targets and saves/restores task contexts via SBOOT monitor
SVCs. Reconstructing where `bx sp` goes, and the RTOS/driver init that would follow, requires the
**SBOOT image**, which is not in the ASW. So full-boot emulation cannot materialize the object table
here — this is not a tuning problem, it is a missing-dependency problem.

## Approach B (direct config-init) — needs the .data object table this fork does not have

`FUN_0006b936` (THUMB bump allocator) runs, but it reads the object table + per-message descriptors
from `.data` (`*0x4069b4` etc.), which are populated by the (SBOOT-performed) `.data` copy. Without
the object-table `.data` image, seeding is not possible from this fork. Locating that image is the
sibling `.data`-alignment task; once it yields `(LMA, VMA)`, apply the copy and call
`FUN_000892a0`/`FUN_0006b936` to get the assignments.

## Bottom line
Boot-emulation is exhausted as a software-only route to the object table: the object-table
materialization depends on SBOOT (either its `.data` copy or its boot context). The remaining
software-only path is **static** recovery of the `.data` load image (the sibling alignment approach)
or the **output-trace** approach (find EPB's handler from the hydraulic-output side, which never needs
the object table). A live RAM read on a bench remains the trivial alternative.
