# EPS rack (J500) — Audi B8/8R Steering Assist (8R0909144F, RCEPS)

RE pack for the **electric power steering rack** — VCDS Address 44 "Steering Assist J500",
part `8R0909144F`, SW `0507`, component `RCEPS`, ASAM `EV_RCEPSAU48X`. This is the **torque**
actuator and the module that carries the lane-keeping function (`lkf_container`) — i.e. the
one that would read/execute an external HCA-style steering-torque request. It is a *different*
ECU from the Dynamic Steering angle actuator in `ecus/dynsteer` (both are Renesas V850).

## Architecture (established from the image)

**Renesas / NEC V850, little-endian, load base `0x00000000`** — same core family as the
Dynamic Steering unit. Proof: a V850 linear sweep of the code is 0% invalid with strong
call-target concentration (one function called 79× and 52 targets reused over a single 64 KB
window). TriCore was rejected (0 functions recovered; the `0x80xxxxxx` "self-pointers" were a
cal-fill artifact — the middle `0x48000..0x78000` is filled with the constant `0x8007e007`);
ARM decodes but shows zero call reuse; PowerPC fails outright.

## Getting the image

```bash
python3 -m frf.decryptfrf --file FL_8R0909144F_0507_BP.frf --outdir firmware   # VW_Flash
python3 ../../core/odx/odx_extract.py firmware/FL_8R0909144F_0507_BP.odx -o firmware
cp firmware/DB_2_50.bin firmware/8R0909144F_0507.bin     # DB_2 (block id 0x50) = ASW+CAL
```

`DB_2` is the application block: a metadata/string header (`EV_RCEPSAU48X`, the `EPS_CORE`/
`EPS_AUDI` C source manifest incl. `lkf_container.c` / `lkf_datapool.c`), then V850 code and
interspersed calibration, then a reserved fill region.

## Reproduce

`source ../../.env.sh && ./reproduce.sh` → **1898 functions**, 1883 decompiled clean. Config
in `ecu.conf`; firmware / project / decompiled C are gitignored.

## Lane-keeping / HCA torque limit — status

The SW **does** contain the lane-keeping function (`lkf_container`, `lkf_datapool`), so this
is the right module for the HCA question (unlike `ecus/dynsteer`, which has no external
command).

The V850 `gp`/`tp` base registers are now **resolved** (`gp=0xFFFF0000`, `tp=0x0001A238`, set by
the pipeline via `BASEREGS` in `ecu.conf`), so the whole corpus decompiles with zero `unaff_gp`
and cal/RAM reads fold to absolute addresses. One gotcha remains when reading *const tables*: the
firmware's baked-in data pointers are **0x12000 higher** than their file offset — see the note in
`ecu.conf` and `docs/RE_findings.md`. Still open: the exact lane-keep torque-limit *constants*
(cap/rate/cutout cals); everything else on the HCA/PLA path is traced.

## docs/

| doc | contents |
|---|---|
| `RE_findings.md` | arch proof, gp/tp resolution, **const-data +0x12000 offset**, torque-path status |
| `can_rx.md` | consumed messages, AFCAN RX, reassembly transport, **RX CAN-ID map correction** |
| `can_tx.md` | **TX map (LH_EPS_01/02/03 = 0x32A/0x11D/0x9F), CRC8H2F magics, mailbox ID table** |
| `can_to_torque.md` | CAN signal → steering-torque propagation |
| `control_loop.md` | 100µs tick / 1.2ms control task, motor PWM, state vars |
| `hca_vs_pla.md` | HCA status 5-vs-7 analysis; PLA angle-command path, limits, gating |
| `hca_fault_statemachine.md` | EPS_HCA_Status fault → READY/ACTIVE recovery machine |
| `hca_engagement_lockout.md` | **~6-min max-continuous-engagement timer (counter 0xfffede84 / 180000), reset + override behavior** |
| `lkas_fault_route.md` | openpilot LKAS-fault route debug (LH_EPS_03 `EPS_HCA_Status`) |
