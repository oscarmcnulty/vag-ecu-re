# ACC_01 (0x109) — field-by-field consumption trace

Every field is described by its **frame bit position** and the **code path** that consumes it, traced in
the decompiles of this image (8R0907551F). No meaning is inferred from DBC/FR field names. Decoder =
`canrx_ACC_01_DCC1_109` (`0x801383e8`), dispatched from `canrx_poll_dispatch_acc_esp` (`0x80108cc4`),
mailbox handle 0x240. Addresses: load base `0x80000000`; RAM is `0xd000xxxx`.

## Ingress gate (runs before any field is used)

- Frame is decoded only if cal `DAT_80043bc6 & 0x100 != 0`. This image = `0x0900` → true (ACC_01 is the
  coding-selected frame; ACC_05/0x10D would be the alternative).
- **E2E**: XOR of all 8 bytes must equal 8, else error flag `a3c0 = 1`.
- **Rolling counter**: `byte1 & 0x0f`, compared to the previous value (`b06c`), debounced via `b06d`/`a3c2`.
- Functional fields are written only when the validity gate passes
  (`a3c1==0 && a3c5==0 && a3c3==0 && a3c0==0 && a3c2==0`); otherwise `FUN_801a61c0` runs (reject/hold).
- Two copies are made at ingress: the **raw 8 bytes** → `b060..b067`, and the **decoded fields** below.

## Decoded functional fields

| Frame bits | Decoded var | Extraction | Traced consumer(s) | Verdict |
|---|---|---|---|---|
| byte3[0:7] + byte4[0:2] (11-bit) | `acc01_ACC_Sollbeschleunigung` `d0007bac` | `(b4&7)<<8 \| b3` | **8013c5d4**: clamped and compared against bound values → sets flags `a580`/`a581` (read by `8014614c`, `8014681a`, `8014682e`); **801408bc**: interpolated → setpoint `Ramd0007cc6` (read back by `8013c5d4:232`), and SNA-tested (`== 0x7ff`) | **USED** — the live acceleration command |
| byte7 bit1 | `acc01_ACC_Anhalten` `a7ae` | `(b7>>1)&1` | **8013ef46:945**: copied to `tsk02_TSK_Anhalten_src` (`a58d`) **iff** `STATE_CRU_CTL ∈ {1,5}` and `LV_DCC_ENA != 0`, else 0; `a58d` packed into **TSK_02 (0x10C) byte2 bit4** by `80137a00` | **USED** — relayed to the ESP as the standstill-hold request, gated by regulating state + DCC coding |
| byte7 bits2-3 | `acc01_ACC_Dynamik` `b06a` | `(b7>>2)&3` | **8013e47c:37**: 4-way switch selecting cal `WORD_ARRAY_80043a5c[0x1d/0x23/0x23/0x24]` for a torque-rate blend | **READ but INERT** — the three selectable cals are all **500** (`0x80043a96/aa2/aa4`), so the value cannot change the output |
| byte7 bits4-6 | `acc_ACC_Status_ACC` `b057` | `(b7>>4)&7` | Many: `8009c0b4` (L2 torque monitor), `800b83f0`, `8010a4fc`, `8010a6ec` (standstill-hold SM), `8011101c`, `80141248`, `80141528` (drive-off/momentenanf), `80137f2c` — compared against 3/4 as a discriminator | **USED heavily** — the ACC master-status discriminator across many subsystems |
| byte7 bit7 | `DAT_d000a7af` | `b7>>7` | **801408bc**: copied → `d00016f8` → `a597` (conditional path); `a597` is read as a gating condition in **8013c5d4** (L71/106/161/354/365/541/545/1149) | **USED (conditional)** — a gate flag in brake formation |
| byte2 bits0-5 | `DAT_d000b3e3` | `b2 & 0x3f` | **801408bc**: scaled → `Ramd0007cc2`, read by (a) **8013c5d4:195** (brake formation) and (b) **80137d0c** → packed into the TX frame at **mailbox 0x840** (active on this image) | **USED** — feeds brake formation and is relayed out on a TX frame |
| byte4 bits3-7 | `DAT_d000b3e4` | `(b4&0xf8)>>3` | **801408bc**: min-clamped + scaled → `Ramd0007cc4`, read by **8013c5d4** (L68/348/386) | **USED** — feeds the brake/accel-limit formation |
| byte5[0:7] | `DAT_d000b3e5` | `b5` | **8013c5d4:283**: scaled → `sRamc000110e` (a limit bound), only when `LV_DCC_ENA != 0` | **USED** on the ACC/DCC-coded path — an accel/decel limit bound |
| byte6[0:7] | `DAT_d000b3e6` | `b6` | **8013c5d4:277**: scaled → `sRamc0001110` (a limit bound), only when `LV_DCC_ENA != 0` | **USED** on the ACC/DCC-coded path — an accel/decel limit bound |

## Bits the decoder does NOT extract (no functional decode)

| Frame bits | Functional decode | Only appearance |
|---|---|---|
| byte0[0:7] | none | E2E XOR sum; raw byte `b060` → L2 monitor |
| byte1 bits0-3 | rolling counter (`b069`) | counter validation + L2 monitor |
| byte1 bits4-7 | none | raw byte `b061` → L2 monitor |
| byte2 bits6-7 | none | raw byte `b062` → L2 monitor |
| **byte7 bit0** | **none — never read** | raw byte `b067` → L2 monitor only |

## The parallel raw-copy / L2 path

`egas_l2_torque_monitor_companion` (`0x8009cf94`) reads the **whole raw frame** `b060..b067` (L1264-1271),
the counter `b069`, and the message-valid flag `a3c4`. So every byte of ACC_01 reaches this ASIL/L2
safety monitor even when it is not functionally decoded — but the monitor consumes the raw frame for
plausibility, not as per-bit commands. `b068` (a separate byte0 copy) is written but **read by nothing**
(dead). Validity flags `a3c1/a3c3/a3c5` also reach diagnostics (`80104a2c`, `801241c0`) and `801408bc`.

## Direct answers on "Anhalten" and "Anfahren"

- **Hold / stop (byte7 bit1)** is **actually used**: it is forwarded, gated by regulating state and DCC
  coding, into TSK_02 as the standstill-hold request to the ESP (chain above).
- **Drive-off / "Anfahren"**: there is **no ACC_01 bit the code reads as a drive-off command**. **byte7
  bit0 is never extracted** by the decoder. The ECU's own drive-off logic (`acc_driveoff_active`, used in
  `800b83f0`/`80141528`) keys off `ACC_Status_ACC` (byte7 bits4-6) and the ACC_05 momentenanf path, not a
  discrete ACC_01 bit. So whichever bit a DBC labels "Anfahren", this ECU does not consume it as a command.

## Method note

Ghidra's static reference DB is **incomplete** for these globals (it captured only absolute-addressed
writes from the reset functions, missing the base-register-relative reads the consumers use). The trace
above is from the decompiles, which resolved the base registers (`a0/a1/a8`), cross-checked by grepping
every decompile set for each variable by name and address.

---

# What `ACC_Sollbeschleunigung` (byte3 + byte4[0:2]) actually controls

Traced from the decoded value `d0007bac` to the actuator outputs. **It is the single unified longitudinal
acceleration command** — the same field produces both the brake request and the engine-torque request,
by sign.

## Encoding (from the decode + downstream compares)

11-bit raw 0..0x7ff, `phys ≈ raw·0.005 − 7.22 m/s²`:

| raw | phys | meaning |
|---|---|---|
| 0x000 | −7.22 | max decel command (clamped downstream to −3.0) |
| 0x5a4 | 0.00 | zero / coast (the reset default) |
| 0x7fe | +3.01 | near-max accel command |
| 0x7ff | — | **SNA / invalid** (801408bc tests `== 0x7ff`) |

## The one gate that decides whether it is used at all

`LV_DCC_ENA` (`d000a757`, long-coding cell 27). In `8013c5d4` the accel-limit lookup branches on it:
DCC/ACC-coded → curve `0xa005b728` and **the CAN value is used**; GRA-coded → curve `0xa005b71c` and the
GRA cals are used instead. So on a GRA-coded car the received `Sollbeschleunigung` has **no effect**. The
CRUC state machine must also be regulating (`STATE_CRU_CTL ∈ {1,5}`) for the output to leave the ECU.

## The data path (traced)

```
d0007bac ─801408bc─(interp FUN_800a4efc)→ Ramd0007cc6
   └─8013c5d4:233 min_value_selector(cc6, min-accel-kennlinie, sRamc00010e4) → Ramd0007c8e  (unified setpoint)
        ├─ DECEL branch → clamp chain → Ramd0007c9a = max(request, 0x7237=−3.0 m/s²)
        │     → read by the CRUC machine (8013ef46 + handlers 8013e13c/e3f8/e47c/e674/e8aa)
        │     → Ramd0007cb8 → 80137a00 → TSK_02 (0x10C) byte8 (TSK_Verzoeg_Anf) → ESP
        └─ ACCEL branch → Ramd0007c96 → Ramd0007ca0 / select_max with torque request Ramd0007caa
              → engine-torque path (CRUC state-1 handler 8013e47c; torque PI 801e9b86)
```

## How it affects behavior

- **Negative command (decel):** becomes `Ramd0007c9a`, the brake request to the ESP, **hard-clamped to
  −3.0 m/s²** by the min-accel kennlinie (`0xa005b728 → 0x7237`), regardless of how negative the command
  is. Delivered to the wheels only if the ESP grants ECD (`d000b296 == 2`), which it withdraws below
  ~15 km/h — so below 15 km/h a decel command is computed but not executed (see `low_speed_floors.md`).
- **Positive command (accel):** becomes engine torque through the accel/torque branch. It is **not**
  ECD-gated, and the whole-ECU pipeline emulation showed a positive `Sollbeschleunigung`
  regulated identically from 20 down to 3 km/h (`emu_accel_below_15.md`).
- **Zero (0x5a4):** coast — no torque add, no brake.
- **SNA (0x7ff):** flagged invalid in `801408bc`; not used as a live command.
- **Plausibility only:** `8013c5d4` also compares the value against bounds → flags `a580`/`a581`
  (`acc01_soll_thr_lo/hi`), which feed a debounce/timer monitor in `8014614c` (diagnostic, not actuation).

**Net for an external ACC master (openpilot):** `ACC_01.ACC_Sollbeschleunigung` is the effective
accel/decel command on this ECU, provided the car is ACC/DCC-coded and cruise is regulating. Usable
range is about −3.0 to +3.0 m/s² delivered (decel saturates at −3.0); accel works to low speed, decel is
surrendered to the ESP below ~15 km/h.
