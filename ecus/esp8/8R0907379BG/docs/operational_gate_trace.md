# Operational-gate trace — why the ESP8 stays pre-operational on the bench (8R0907379BG)

Session 2 result. The handoff (`BENCH_SESSION2_PROMPT.md`) recorded the TX gate
`*0x40944c==1 && *0x409438!=0` but noted the `=1` writer was *not statically resolvable* (the
disable path `FUN_6a9d4` had no caller). **Both writers are now found and the whole chain is
resolved** — statically, from the committed decompiles + firmware pools. It is an **AUTOSAR
ComM/Nm network-state gate**: on a bare bench with no partner NM traffic the Nm stays in
NoCommunication, so ComM never enables the COM TX scheduler.

Method note: seg1 globals are reached through big-endian literal-pool pointers (bytes `00 40 94 4c`
= `0x0040944c`), which is why grepping the decompiles for the raw address finds nothing. Every
address below was recovered by reading the pool slot in `firmware/8R0907379BG_0030.bin` as a
big-endian u32 and matching it to the `DAT_xxxxxxxx` / `PTR_DAT_xxxxxxxx` token in the decompile.

## The chain (all addresses confirmed)

```
can_tx_scheduler (0x5bfc)            normal broadcast (ESP_01 0x100 / ESP_02 0x101 / ESP_08 0x11e)
  gate @L61:  runs iff  *0x40944c == 1   AND   *0x409438 != 0
        pool 0x5f64 -> 0x40944c (comm_enable) ; pool 0x5f78 -> 0x409438 (tx_gate2)

  *0x40944c = 1   <-  FUN_0006a71c        <-- ComM/Nm MAIN RUNNABLE (the enable writer)
        writes *0x40944c='\x01' (via alias pcVar2 = DAT_0006aa34) when the network-mode byte
        *0x409230 & 0xf0  in {0x30, 0x40, 0x80, 0xa0}   (i.e. NOT 0x00 and NOT 0x20/NoCom).
        FUN_0006a9d4 is its DISABLE sibling: *0x40944c=0 + logs DTC 0x169 (FUN_0008473e(0x169,..)).
        Both are Nm callbacks -> no direct caller by design (runtime object-table wired).

  *0x409230 (netmode)  <-  FUN_0008f5cc  via  FUN_0008f5a4(param):
        param == 0  -> 0x20   (NoCom  => stays DISABLED)      <-- the bench default
        param == 3  -> 0x40   (enable)
        param == 4  -> 0x30   (enable)
        param  else -> 0x80   (FullCom => enable)
        So the ENTIRE wall reduces to: on the bench, param stays 0.

  *0x409438 (tx_gate2) <-  bit21 of the Nm PDU/status word *0x408f10   (FUN_0008f5cc @L12,
        also set by FUN_00040794 @L19/23 from the received NM PDU bit).
```

## The Nm layer (source of both gate inputs)

- **Nm PDU / status word = `0x408f10`** (COM signal `0x046f`, 4 bytes — `decode/can_to_buffer.csv`:
  `sig_0xb038c … 0x046f,4 -> 0x00408f10`). Consumers spread across the image read individual bits:
  bit20 (`FUN_0000525c`), bit21 -> `0x409438`, bit26 (`FUN_00049940` early gate), bit25.
- **`FUN_00040950` = Nm message processor / RxIndication.** `param_2` is the event:
  - `==1` (NM PDU received): validates source node-id against the flash node table `0xbd83c`
    (masks `0xbda3c/0xbda3e`, "own id" mask `0xfeffffff`), checks control bits
    (`(pdu & 0x30)!=0x30`, `!(pdu & 0x9000)`), calls `FUN_00040794` (the `0x409438` unpacker),
    then **stores the raw PDU word at `0x408f10`** (`*DAT_00040a7c = uVar5`) and sets the
    network-active flags `0x408f21`/`0x408f22`.
  - `==2` (NM timeout / bus-sleep): `*0x408f10 = 0x1000000` (bit24 only), clears the flags,
    `*0x408f1c = 3`. **This is the bench steady state** — no NM RX ever arrives.
- **`FUN_0006a71c`** (Nm main) uses PDU ptr `0x408f10`, Nm channel struct `0x406d02`, and the
  flash Nm timing consts `0xbd8f8/0xbd904`; it is where `*0x40944c` flips to 1 once netmode says so.

## What this means for the bench

The ECU is a **passive/waiting Nm node**: with itself as the only node on the chassis/sensor CAN
(no gateway, no sensor cluster, no steering/AWD), it receives no partner NM PDU, so:
`FUN_00040950` only ever runs the `param_2==2` timeout branch → `0x408f10=0x1000000`, flags clear →
netmode param stays 0 → `FUN_0008f5a4` returns 0x20 (NoCom) → `FUN_0006a71c` never sets
`0x40944c=1` → `can_tx_scheduler` stays gated → only the raw 0x060 heartbeat goes out and Dcm
never answers. This is exactly the observed wall, now mechanistically explained.

**The minimal trigger is a valid partner NM PDU on the chassis CAN** that passes `FUN_00040950`'s
`param_2==1` checks (recognized source node-id from table `0xbd83c`, control bits with
`(pdu&0x30)!=0x30` and `pdu & 0x9000 == 0`). That drives netmode nonzero → comm enable → operational.

### Still object-table-gated (the one remaining unknown)
The exact **CAN-id** that delivers signal `0x046f`/the NM PDU into `0x408f10` is routed through the
runtime object table `0x40a1a8` (the project's long-standing runtime blocker; see
`com_init_objtable.md`). The static receive inventory (`decode/can_inventory.csv`) tops out at
`0x267` and contains no `0x4xx` NM entry, confirming NM RX is object-table-routed, not statically
filtered. So the *mechanism* is fully resolved but the *CAN-id* needs either object-table
materialization or a bench experiment (below).

## E2E CRC of the 0x060 heartbeat (reversed this session)

`bench/nm_crc.py` — the ECU's 0x060 TX (`00 00 00 00 00 08 CTR CRC`) checksum is
**CRC-8/SAE-J1850** (`poly 0x1D, init 0xFF, xorout 0xFF, no reflection`) over bytes 0..6, no
per-message data-id. Verified against all 8 on-bench samples (CTR 0..7 → 50 4d 6a 77 24 39 1e 03).
This is the E2E profile the ECU applies to its own status TX and the most likely profile for the
partner frames it expects (a per-message data-id may prepend the RX form — confirm against a real
captured partner frame).

## Bench results (session 2, SM2 live on the bench)

Ran on the powered bench (SM2 present, `PassThruOpen` OK, ECU ACKs). Tools: `bench/can_raw.py`.

- **State confirmed:** sniff shows **only CAN 0x060 at ~98 Hz** (nothing else) — pre-operational,
  exactly as the handoff described. Fresh 0x060 samples (CTR 0x06..0x0f) **validate the CRC-8/J1850
  solution out-of-sample** (all 10 match, incl. counters never in the original 8-sample set).
- **Accepted-RX-ID list extracted from firmware** (`0xafae0`, big-endian): **225 ids, max 0x258,
  and ZERO in the 0x4xx range.** The ECU does not accept standard VW NM (0x400+node) on this
  private chassis/sensor CAN — so the handoff's "0x441 NM" lead is a dead end. The NM PDU / signal
  0x046f arrives on one of these ≤0x258 ids, object-table-routed.
- **Full-network replay does NOT wake it (decisive negative).** Transmitting **all 225 accepted
  ids** as valid counter+CRC frames (J1850, byte6=counter) at 10 Hz for 12 s produced **no new tx
  id** — the ECU stayed on 0x060 only (TX verified: writes return STATUS_NOERROR and are ACKed).
  This is a stronger negative than session 1's 33-id replay. **Bus presence alone is insufficient**;
  the wake needs either per-message *valid E2E content* (real sensor-cluster data, not filler) or a
  ComM-user request — not merely recognized CAN ids being present.

Conclusion refinement: the wall is not NM-0x4xx and not "no traffic"; it is that no partner delivers
the *specific valid content* that drives the ComM channel request (netmode `param`) off zero. The
most probable single trigger is the **ESP sensor cluster (G419)** data the ESP polls via its 0x060
sync — reproducing that needs the sensor-cluster message id + valid signal/E2E, or the RAM-write
fallback below.

## Bench experiments still to try (needs the SM2 + 32-bit Python re-provisioned)

1. **NM-wake sweep.** Broadcast a plausible partner NM PDU on candidate chassis-CAN IDs (VW NM is
   commonly `0x400 + node`; also try the `0x441` NM-range mailbox already noted, and the sensor
   cluster / steering / AWD source ids) at ~20 Hz, control byte with `bit4/bit5` set to request
   network (`pdu & 0x30 != 0x30`, `pdu & 0x9000 == 0`), CRC per `nm_crc.py` if the RX form is E2E.
   Success signal: the ECU starts broadcasting ESP_01 `0x100` / ESP_02 `0x101` / ESP_08 `0x11e`
   (i.e. `0x40944c` flipped) — watch the bus, no diag needed.
2. **Confirm which id lands in 0x408f10.** Once operational (or with a live-RAM read), read
   `0x408f10` and correlate with the injected id to pin the NM CAN-id, closing the object-table gap
   for this one signal.
3. **Then retry UDS** on the native diag mailbox `0x6b4`/`0x6b8` per `uds_read_primitive.md`.

Fallback if NM proves unreachable without a gateway: the enable is a single byte `0x40944c` and the
netmode `0x409230` — a live-RAM write (bench debug/`0x23`-style primitive, once found) to
`0x40944c=1` + `0x409230=0x80` would force operational without NM, isolating whether anything
downstream also checks NM state.
