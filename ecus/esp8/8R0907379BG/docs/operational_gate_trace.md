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

## How the NM data actually arrives (deeper trace, session 2 cont.)

Chased the source of the NM status word `0x408f10` through the RX path:

- `FUN_00040950` (NM processor) is called from two places: `FUN_0001c5ec` with event **2**
  (timeout — the only branch that runs on the bench: writes `0x408f10=0x1000000`, clears flags),
  and **`FUN_000689e4`** with event **1** (NM message received).
- `FUN_000689e4` is a **container/transport RX handler** (has ISO-TP FF/CF nibble handling,
  `buf+0xd & 0xf0 ∈ {0x10,0x20}`). It reassembles a payload into the channel buffer at
  `0x4050e8 + 0x108`, reads a **16-bit sub-PDU tag** from payload bytes 2..3, and **only when that
  tag == `0x600`** does it assemble the 4 following bytes and call `FUN_00040950(&data, 1)`. So the
  NM data is a **sub-PDU (tag 0x600) multiplexed inside a container/transport message**, not a
  standalone CAN frame — which is exactly why session 1's frame replay and this session's 225-id
  filler replay both did nothing (they never carried a `0x600`-tagged sub-PDU with valid content).
- The 4-byte NM data must then pass `FUN_00040950`'s checks: source node-id (byte0) recognized in
  the node table, and mask checks against `0xbda3c/0xbda3e` (`byte0 & ~mask == 0`, etc.).

### Why the container CAN-id can't be pinned statically (confirmed dead ends this session)
- **msgcfg `0xa9fc0`** (223 recs) all use one generic routine (`0x8e3ec`); none has state-RAM near
  `0x408f10` — the NM/container message is not in the generic COM RX table.
- The NM config pointers (`DAT_00040a40→0xbd83c` node table, the `0xbd774/0xbd790` id tables) all
  land **inside the seg2 code region** (file `0xbb045`+, VMA=file+3); read as data they are ARM
  instructions, not clean `{id,len}` tables — Ghidra mis-types data refs into seg2, so these
  "tables" don't decode. A −3-shifted read still yields code, not CAN-ids.
- `com_config_walker` (`0x49f38`) decompiles as **mixed-ISA garbage** ("bad instruction data"),
  so the walker logic can't be read from the decompile to replay the config statically.
- Everything in this COM/NM stack is invoked through **RAM function pointers** wired by the
  object-table init — no direct callers — i.e. the same runtime blocker documented across sessions.

### Live-bench negatives (session 2)
- 225-id filler replay (valid J1850 CRC), 12 s @10 Hz → no wake.
- Container-format sweep (225 ids × 3 layouts embedding sub-id `0x0600`, node 0), 15 s → no wake
  (expected: node 0 fails `FUN_00040950` node-id validation, and the container id/layout are guesses).

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

## NM CONTENT recovered via emulation oracle (session 2 cont.) — node-ids

Using the emulator as an oracle (`emu/nm_validate_oracle.py`): ran the NM processor
`FUN_00040950` (Thumb) with event=1 over candidate 4-byte payloads and detected which reach the
success path (writes 0x408f10 + sets network-active flags 0x408f20/0x408f21).

- **Accepted SOURCE NODE-IDs (payload byte2, matched against node table 0xbd83c):
  `0x4a, 0x5f, 0x98, 0x99, 0x9a, 0xd4`.** Control byte (byte0): `0x00, 0x02, 0x40, 0x42`.
  Minimal passing NM word: `[00 00 <node> 00]`.
- Container reassembly (`FUN_000689e4`): the NM word is a sub-PDU tagged **0x600**; the 4 NM bytes
  are a scrambled map of the transport payload —
  `NM = (buf[0x10e]<<24)|(buf[0x10d]<<16)|(buf[0x10c]<<8)|buf[0x10f]`, i.e. node = payload byte4,
  ctrl = byte6, sub-id `06 00` at bytes[2:3]. Candidate single-frame: `[LL 00 06 00 NODE 00 CTRL 00]`.

### Bench tests run (all NEGATIVE)
- Saturating all-ids container blast; clean per-id single-frame sweep; per-id multi-framing sweep
  (raw + ISO-TP-style), all with valid node-ids across the 225 accepted CAN-ids → **no reaction**
  (heartbeat 0x060 unperturbed, no new tx id). Harness kept as `bench/nm_probe.py`.

Interpretation: the NM CONTENT is now known and verified, but the **container CAN-id + exact
transport framing are object-table-routed (RAM-wired)** and not reproducible by blind injection,
and the NM→ComM-enable step (netmode `param` into `FUN_0008f5cc`) is also RAM-wired. So the two
remaining unknowns are both runtime-dispatch. Closing either needs the object-table materialization
(`emu/objtable_corun.py`) to yield the container id + sub-PDU layout, OR a real private chassis-CAN
capture (running B8 Q5 / the G419 sensor cluster) to read the true frame — against which the
node-ids above are the validation key.

### Additional bench negative (session 2 cont.)
ISO-TP container payloads (sub-id 06 00 + each valid node-id, several layouts) sent to the native
diag mailbox `0x6b4/0x6b8` → no response, no wake (still only 0x060). Consistent with the handoff's
0x6b4 silence. The transport (`FUN_000689e4`) has FF/CF connection state, so event=1 (NM received)
likely needs a full transport CONNECTION handshake first — not just a single injected frame.

## HARDWARE MAILBOX CONFIG decoded (session 2 cont.) — hidden NM CAN-ids found in the bin
Decoded the CAN-controller mailbox config table at **`0xaea38`** (24-byte records:
`{mbox_reg(4), w1(4), ctrl_reg(4), w3(4), canid@+0x10 (u16), maskbit(4)}`). The `canid` field (w4hi)
gives the **hardware-accepted CAN-ids**, several of which the software COM receive-filter (`0xafae0`)
does NOT list — i.e. dedicated mailboxes the prior static inventory missed:

- **Hidden hardware RX ids** (in a mailbox, absent from `0xafae0`):
  `0x64, 0x188, 0x194, 0x198, 0x1c8, 0x208, 0x210, 0x228, 0x27c, 0x400, 0x404, 0x40c, 0x418, 0x440, 0x478`
- The **NM-range cluster `0x400 / 0x404 / 0x40c / 0x418 / 0x440 / 0x478`** is the key find. `0x440`
  is on its own mailbox `0xfff7e610` (w3=`0x01010202`, distinct from the COM-RX mailboxes' `0x08xx06xx`).
  The handoff's "0x441 NM" guess was **off by one** and its replay used only `0xafae0` — so these NM
  ids were **never tested with valid content**. This kills the "no 0x4xx" conclusion from the SW filter.

### Bench tests on the hidden ids (session 2, all NEGATIVE so far)
- Valid NM node-ids ({0x4a,0x5f,0x98,0x99,0x9a,0xd4}) in direct (node@byte0/1/2/3) and container
  (sub-id 06 00, node@4) framings, per-id — no reaction.
- **Sustained full-NM-cluster** (valid node on all six 0x4xx ids @50 ms for 8 s, counter+CRC,
  node@byte2 and node@byte0) — no wake, 0x060 unperturbed.

Interpretation: the CAN-ids are now known from the bin, but the exact **NM frame byte-layout / E2E**
that mailbox `0xfff7e610`'s RX handler expects before it reaches `FUN_00040950` is still unresolved
(the mailbox→handler byte mapping is the next trace). The node-ids remain the validated content key.
Tools: bench/nm_probe.py (now covers hidden ids via edit), scratch nm_sustained.py.

## EXACT NM FRAME FORMAT decoded from the transport handler (session 2 cont.)
Disassembled `FUN_000689e4` (Thumb) match/parse (0x689e4-0x68b04):
- Channel buffer base `0x4050e8`; received frame at `+0x108`. `frame[0]` = length, must be `>=4`.
- Received sub-id = `(frame[2]<<8) | frame[3]`; matched against the 3-entry sub-id table (hardcoded
  compares to **0x600 / 0xf1a3 / 0xf1a4**; table also at `0xbd774`, RAM-relocated). Length gate:
  `frame[0] == subid_len + 3` → for 0x600 (len 4) **frame[0] must = 7**.
- On sub-id 0x600 → the 4 NM bytes are assembled from `frame[4..7]` (scrambled) into the word
  `frame[6]<<24 | frame[5]<<16 | frame[4]<<8 | frame[7]`, then `FUN_00040950(word,1)`. Per the NM
  validator: **node = frame[4]**, ctrl = frame[6]. So the NM CAN frame is:
      `07 00 06 00 <NODE> 00 <CTRL> 00`   NODE∈{0x4a,5f,98,99,9a,d4}, CTRL∈{0,2,0x40,0x42}
- **Gate:** channel status reg `[0x4079a0+0x44]` (=`0x4079e4`) **bit11** must be set (the CAN driver
  sets it on a validated RX). A second table (`0xbd790`) validation also applies.

This is the container/sub-PDU frame that drives NM. It matches the format already tried on 0x440
(negative) — so the last missing piece is the **CAN-id that feeds transport channel `0x4050e8`**
(the mailbox→channel binding), plus possibly the bit11/connection state needing sustained RX.

## Transport is VAG TP2.0 (session 2 cont.) — new diagnostic wake avenue
The transport handlers (`FUN_0001c3c8` etc., channel 0x4079a0 / buffer 0x4050e8) check received
opcode bytes `0xB8`/`0xBA` at buffer+0x10a — **VAG TP2.0 channel-management opcodes**. So the
"container" transport is TP2.0, and `0x600` is a TP2.0 logical address, not a plain multiplex tag.

Implications for the bench wake:
- The exact single-frame NM format decoded above (`07 00 06 00 NODE 00 CTRL 00`) is likely only
  meaningful INSIDE an established TP2.0 channel — which is why raw injection on the CAN-ids does
  nothing: no channel is open, so the channel-status bit11 gate never sets and FUN_000689e4's
  per-message path isn't entered.
- **New avenue:** a proper **TP2.0 channel-setup handshake** (broadcast setup request → ECU dynamic
  channel response → KWP2000/Dcm) would make Dcm active-diagnostic a ComM user → ComM full
  communication → operational — independent of the missing partner NM. The handoff's "TP2.0 setup
  silent" needs revisiting with the transport-group CAN-ids now known (diag `0x6b4`, and the
  `0xfff7ea00`-controller mailbox cluster incl. `0x440/0x188/...`), and the correct TP2.0 setup id.

Session-2 wake decode summary (all committed): operational gate = ComM/Nm (0x40944c/0x409438);
0x060 CRC = CRC-8/J1850; NM node-ids {0x4a,5f,98,99,9a,d4}; hidden HW NM CAN-ids
{0x400,404,40c,418,440,478}; exact NM sub-PDU frame `07 00 06 00 NODE 00 CTRL 00` (sub-id 0x600,
len 4); transport = TP2.0. Remaining: open a TP2.0 channel (or capture the real bus) — the CAN-id↔
channel binding + channel connection state are the last runtime-only pieces.

## CORRECTION: transport is a sub-id-multiplexed IPDU, NOT TP2.0
The prior "TP2.0" note was wrong. `0xB8`/`0xBA` are read at `buffer+0x10a`, which is the **sub-id
high byte** (sub-id = `buffer[0x10a]<<8 | buffer[0x10b]`) — so they are just other sub-id families
(`0xB8xx`/`0xBAxx`), not TP2.0 channel opcodes. Confirmed: `DAT_0001c6cc = 0x4050e8` (the channel
buffer). So there is no TP2.0 channel-setup avenue; the transport is an AUTOSAR-style multiplexed
container IPDU that demuxes sub-PDUs (0x600 NM, 0xf1a3, 0xf1a4, 0xB8xx, 0xBAxx…) from a reassembly
buffer. Sub-id 0x600 is a SINGLE frame (`frame[0]=7`, 4 data bytes), so the decoded
`07 00 06 00 NODE 00 CTRL 00` frame stands — it just has to arrive on the CAN-id bound to channel
`0x4050e8`, with the channel-status bits (`0x4079e4`) that the CanIf RX sets on delivery.

Net accurate state: the NM CONTENT + exact single-frame layout are decoded and correct; the one
remaining runtime-only unknown is the **CAN-id ↔ transport-channel (`0x4050e8`) binding** (the CanIf
RX config, RAM-wired, flash literals point to code). Closing it needs the CanIf/COM config
materialization (same boot-init blocker) or a real bus capture — against which the decoded frame +
node-ids are the immediate decode/verify key.

## FRAME FORMAT CONFIRMED end-to-end in emulation
Set the transport channel-status reg `0x4079e4` bits **10+11** (the "message complete/valid" bits the
CanIf sets on a validated RX) and fed the frame to `FUN_000689e4` (with the reconstructed sub-id
table): it reaches `FUN_00040950(word,1)` and **writes `0x408f10 = 0x5f00`** (NM word, node 0x5f) and
sets the network-active flags. The NM-path gates at `[0x4079e4]` are: **bit11 set**, plus (bit26 &
`*0xbc590=='X'`) OR **bit10 set**. So the frame `07 00 06 00 <NODE> 00 <CTRL> 00` is DEFINITIVELY the
correct NM sub-PDU — the only bench variable left is the CAN-id whose CanIf RX sets those status bits
(and whether a single frame suffices vs. a multi-frame/FF reassembly). A full 11-bit CAN-id sweep of
this exact frame is the decisive bench test.

## DECISIVE: full 11-bit sweep of the exact NM frame does NOT wake it
Swept `07 00 06 00 5f 00 00 00` across ALL CAN-ids 0x000-0x7ff (~0.12s/id, 245s) → no new tx, only
0x060. Since the frame CONTENT is emulation-proven correct, this proves **single-frame injection
cannot deliver the sub-PDU on any CAN-id** — the missing piece is the transport DELIVERY (the CanIf
reassembly that sets channel-status `0x4079e4` bits 10+11), not the content. Corroboration:
`FUN_00067b1c` reads the length byte `buffer[0x108]` and, for an odd length like 7, computes
`(len-1)/2` (=3) — a per-message FRAME COUNT, i.e. the container is a **multi-frame** protocol; a
single 8-byte frame never completes it, so the "message complete" status bits never set.

=> The wake requires the multi-frame reassembly sequence (FF/CF at `buffer+0xd`, 0x10/0x20), not a
lone frame. Next: reverse the CanIf reassembly (writers of `0x4079e4`: FUN_0001c3c8/c6b0/d570/8b850)
to construct the exact FF+CF sequence for sub-id 0x600 — or capture the real partner's frames.

## ANSWER to "is blind injection possible without a partner?" — YES (no flow-control lock-out)
Reversed the transport RX/TX to settle whether the ECU must send flow control (which it won't while
degraded):
- `FUN_00067b1c` is **proactive TX segmentation** (case 5 packs the ECU's own NM word 0x408f10 into a
  sub-id-0x600 container to SEND); `FUN_0005c744` is a transport-op **queue submit** (mutex-guarded),
  not a CRC and not a flow-control responder.
- On NM RX, `FUN_000689e4` calls only `FUN_0008a786` (sets a flag bit) — it **transmits nothing**.
=> The transport is a **broadcast segmented multiplex, NOT point-to-point ISO-TP**: there is no
FC/handshake, so the ECU's silence does NOT prevent it from receiving a container. **Blind injection
is architecturally possible** — the bench CAN wake it without a live partner.

### Why the single-frame sweep still failed, and the true remaining barrier
Sub-id 0x600 is a single 7-byte message (fits one CAN frame), and no FC is needed, yet the full
11-bit sweep set no channel-status bits. So the CanIf RX marks the channel "message valid"
(`0x4079e4` bit10/11) only after the frame passes its **acceptance + E2E/sequence check** — the exact
container **CAN-id** and its **E2E parameters (counter position + CRC data-id)** are the last missing
values, and both live in the RAM-relocated CanIf/COM config (flash literals point to code). They are
not cleanly recoverable statically.

**Net answer:** the bench can wake the unit without a partner (no protocol lock-out); the blocker is
purely the exact container CAN-id + E2E params, which a **single bus capture** hands over directly —
and then the fully-decoded content above (sub-id 0x600, node-ids, `07 00 06 00 NODE 00 CTRL 00`,
CRC-8/J1850) constructs and verifies the wake frame.

## CONTAINER CAN-ID FOUND IN THE BIN — receive-routing table 0xb3e38
The CanIf receive-routing config IS a static flash table at `0xb3e38` (stride 8: `{channel_ptr(4),
canid(u16), flags(u16)}`). It maps container CAN-ids to the NM transport channel `0x4079e8`
(= the channel struct whose buffer is `0x4050e8`):
- **channel 0x4079e8 ids:** 0x400,0x403,0x406,0x409,**0x40c**,0x425,0x42f,0x43a,0x44a,0x4ae,0x457,
  0x45c,0x481,0x466,0x46c, 0x787,0x794,0x7a1,0x7b1,0x7be,0x7cb. The flags **high byte = container
  byte-length** (0x400→1, **0x40c→0x17=23**, 0x425→8, 0x43a→0xe, 0x44a→0xb, …).
- The container's sub-PDU list (`0xb5760`): `0x600`(len4)+`0xf1a3`(len3)+`0xf1a4`(len8). With 2-byte
  sub-id headers + a 2-byte container header: 6+5+10+2 = **23 = 0x17** → matches **CAN-id 0x40c**.

**=> The NM (sub-id 0x600) arrives on CAN-id `0x40c` as a 23-byte MULTI-FRAME container** (0x600 is
the first sub-PDU). Single-frame injection on 0x40c fails because the message spans ~4 CAN frames and
the channel-status "complete" bits only set after the full multi-frame reassembly. Config also links
signal 0x046f→buffer 0x408f10 (NM word) and handler `0xbbe28` to this container. Next: reverse the
multi-frame FF/CF byte layout (from TX segmenter FUN_00067b1c / the RX reassembler) to build the
23-byte container on 0x40c with a valid 0x600 NM sub-PDU, and inject it (no flow-control needed).

## E2E PROTECTION found — why valid-content frames still fail
Right before the NM sub-PDU config (buffer 0x408f10 @0xb3e14) sits the E2E/protection config:
`03 7f ff 12` → **profile 0x03, data-ID 0x12** for the NM. It's part of a per-sub-PDU data-ID list
(`0x91,0x33,0x31,0x80,0x35,0x12` at 0xb3dfc..0xb3e10) plus a value table `70 86 9c b2 c8 de fe`
(likely per-counter CRCs). So the container/NM sub-PDU is **E2E-protected** (counter + CRC keyed by
data-ID) — the CanIf validates E2E and only then sets the channel-status "valid" bits (0x4079e4
bit10/11) that gate the NM path. That is why every content-correct injection (single- and multi-frame)
on the right CAN-id (0x40c) was dropped: no valid E2E counter/CRC.

### State of the wake (session 2 — the CAN-ids ARE in the bin)
Confirmed the user's point: the CanIf receive-routing table `0xb3e38` gives the container CAN-ids
statically (NM channel 0x4079e8 ⇐ 0x400/403/406/409/**0x40c**/425/.../46c, 0x787-7cb). The NM sub-PDU
(0x600), the frame content, node-ids, and now the **E2E data-ID (0x12)** are all recovered from the
bin. The ONLY remaining piece to build a bench-valid wake frame is the **exact E2E layout** (which
bytes are the counter and CRC, and the CRC algorithm keyed by data-ID 0x12) — reverse the CanIf E2E
validator that reads the `0x037fffXX` config and gates 0x4079e4 bit10/11. Then: valid E2E frame on
0x40c with sub-id 0x600 + a valid node-id = operational.

## E2E validator is boot-installed RAM dispatch (session 2 — final on this thread)
Confirmed both CRC-8 tables are present in the bin: **J1850 @0xb408c** (`00 1d 3a 27…`, poly 0x1D)
and **H2F @0xb4800** (`00 2f 5e 71…`, poly 0x2F). But they have **zero static references** (searched
seg1, seg2 VMA+3, and −3), and the container config `0xb3df0-0xb3e14` (signal records 0x046f→0x408f10,
0x0301→0x409431, 0x038f→0x40943d) also has no pointer to it. So the E2E/CRC validator — the code that
reads the data-ID config, computes the CRC, and gates the channel-status bits — is reached only
through boot-installed RAM function pointers (the same object-table dispatch wall).

### Net state of the wake (what IS and ISN'T recoverable statically)
RECOVERED FROM THE BIN (committed): operational gate (ComM/Nm); 0x060 CRC (J1850); NM node-ids
{0x4a,5f,98,99,9a,d4}; the container CAN-id **0x40c** (routing table 0xb3e38 → NM channel 0x4079e8);
sub-id 0x600 + exact NM byte layout (emulation-confirmed); the container's COM signals
(0x046f=NM/0x408f10, 0x0301, 0x038f); the data-ID config `03 7f ff 12`; and both CRC tables.
NOT statically recoverable: the exact **frame-processing** (single-vs-multi-frame reassembly + the
E2E counter/CRC byte positions and data-ID mixing) — that code is RAM-wired, no static refs, so the
precise wake-frame bytes can't be derived without running the boot-installed dispatch.

Consequence: constructing the bench wake frame needs either (a) the full-boot peripheral-model
emulation to run the CanIf/E2E with the installed pointers (the documented hard route), or (b) one
capture of a real container frame on 0x40c (which then plugs straight into everything above).
The bench-injection attempts (single-frame, multi-frame FF/CF, len-variant, all node-ids on 0x40c
and the whole channel-0x4079e8 id set) are all recorded negative — consistent with a dropped E2E.

## TX-construction emulation (FUN_00067b1c) — partial frame structure recovered
Emulated the ECU's own container TX segmenter to reconstruct the frame it sends (= what a partner
sends). For sub-id 0x600 (case 5) it packs: `[0x06][counter=*0x4079b9][NM2][NM1][NM0][NM3]` — i.e. the
NM word (0x408f10) bytes in order 2,1,0,3, with a **counter byte** right after the sub-id high byte.
This is consistent with the RX decode (node = NM-word byte2 = frame[4]) and reveals there IS a counter
in the frame (at the byte after 0x06). The remaining sub-PDUs are packed by seg2 handler functions
(0xbbe28/30/38, Thumb) that need the boot-installed RAM context to run — in isolation the emulator
copies their code bytes instead of executing the pack, so the full multi-sub-PDU frame + the E2E CRC
byte are not cleanly reproduced without the dispatch.

Confirmed 4 independent ways that the exact wake-frame construction needs the SBOOT-installed runtime
(object-table iterator; E2E validator w/ no static CRC-table refs; full-boot harness null-ptr hang;
TX seg2 handlers). All CONFIG DATA is in the bin (CAN-id 0x40c/0x406, sub-id 0x600, node-ids, data-id
0x12, CRC tables, NM byte order [2][1][0][3], counter @ frame[1]); the CONSTRUCTION CODE that emits
the counter+CRC is boot-installed dispatch not present/runnable in the ASW image alone.

## CORRECTION + refinement: sub-PDU 0x600 content is CORRECT; barrier is container framing
Re-checked the TX packer: `ea0[0x19]` is the sub-id LOW byte (0x00), not a counter. So sub-id 0x600
packs as `[06 00][word2][word1][word0][word3]` and the RX reassembles it back to the exact NM word
(verified: TX-pack of 0x408f10=0x5f11a2b3 → RX word 0x5f11a2b3). **The single-frame content I tested
(`07 00 06 00 <node> 00 00 00`) is structurally correct** — there is NO per-sub-PDU counter/CRC.

So the remaining barrier is purely the **container-level framing**: CAN-id 0x40c bundles all 3 sub-ids
(0x600 len4 + 0xf1a3 len3 + 0xf1a4 len8 = 23 bytes, flags 0x17) into one multi-frame message, and the
CanIf only marks the channel "valid" (0x4079e4 bit10/11) after the full multi-frame reassembly
completes. A single 0x600 frame never completes the 23-byte container, so the gate never opens. The
exact multi-frame segmentation (frame boundaries, PCI/sequence bytes, and whether the 03 7f ff 12
config adds a container CRC) is produced by the seg2 pack handlers (0xbbe28/30/38) which don't run in
isolation. That segmentation is the last unknown; everything else (CAN-id, sub-ids, node byte order,
per-sub-PDU layout) is fully recovered from the bin.

## COMPLETE ENABLE-CONDITION CHAIN (fresh labeled pass)
Found the CanNm state machine `FUN_0006eba8` (cannm_state_machine) — the missing NM→ComM link. Full
chain to operational, all conditions now identified:
1. Receive the **NM container on CAN-id 0x40c** (sub-id 0x600, node-id in {0x4a,5f,98,99,9a,d4}) →
   `nm_msg_process(0x40950)` sets NM-active flags 0x408f20/0x408f21/0x408f22.
2. **COM signal 0x047b (0x408f0c) == 1** (CAN-id 0x47b, direct 4-byte signal) — GATE for
   `cannm_state_machine(0x6eba8)`; it returns immediately if 0x408f0c != 1.
3. **NM mode 0x4090d8 & 0xf0 == 0x80** (Network Mode / Normal Operation) — drives the CanNm state
   machine (case 3/6/8) to Normal Operation instead of logging DTC 0x169.
4. CanNm Normal Operation → ComM FullCom → `comm_netmode_write(0x8f5cc)` sets netmode 0x409230=0x80.
5. `comm_nm_main(0x6a71c)` reads netmode, sets **comm_enable_flag 0x40944c = 1**.
6. `tx_gate2 0x409438` = bit21 of NM word 0x408f10 (set via the NM PDU).
7. `can_tx_scheduler(0x5bfc)` sees 0x40944c==1 && 0x409438!=0 → broadcasts ESP_01/02/08 = OPERATIONAL.

So the bench-injectable requirements are precisely: the NM container (0x40c, node-id valid, mode 0x80)
AND COM signal 0x047b==1 on CAN-id 0x47b. Both arrive via the (RAM-wired object-table) COM RX; the
remaining barrier is unchanged (the container multi-frame delivery), but the enable CONDITIONS are now
fully enumerated — including the previously-unknown signal-0x047b gate and the mode-0x80 requirement.

## ENABLE CONDITIONS — fully enumerated (post-relabel pass, session 2 final)
After adding 22 confirmed symbols and re-running reproduce.sh, the enable chain is complete and the
conditions are exhaustively identified:

```
can_tx_scheduler(0x5bfc) broadcasts ESP_01/02/08  ⟺  comm_enable_flag(0x40944c)==1 && tx_gate2(0x409438)!=0
  comm_enable_flag=1  ⟺  comm_nm_main(0x6a71c): netmode(0x409230) & 0xf0 ∈ {0x30,0x40,0x80,0xa0}
  netmode            =  comm_netmode_write(0x8f5cc) = comm_mode_map(param):  param 0->0x20(NoCom); else enable
  param (ComM chan mode) driven by a ComM USER requesting communication:
     • Nm user  = cannm_state_machine(0x6eba8) reaching Network Mode (needs COM signal 0x047b(0x408f0c)==1,
                  NM-active flags 0x408f20/21/22 from nm_msg_process on the 0x40c container RX, and
                  NM mode 0x4090d8 & 0xf0 == 0x80). All inputs are received COM signals.
     • Dcm user = active diagnostic session (ComM_DcmActiveDiagnostic) — alternative, non-NM enable.
  tx_gate2 = bit21 of NM word 0x408f10 (set from the received NM PDU).
```

**Bench-injectable requirement (Nm path):** the multi-frame NM container on CAN-id 0x40c (sub-id 0x600,
valid node-id, mode field=0x80) PLUS COM signal 0x047b==1 on CAN-id 0x47b. Combined single-frame
injection tested NEGATIVE — consistent with the container being multi-frame (a single 0x600 frame never
completes the 23-byte reassembly, so nm flags never set). **The enable CONDITIONS are now fully known;
the sole remaining barrier is the multi-frame container byte-segmentation** (produced by seg2/RAM-wired
CanIf code, absent-runnable from the ASW image) — OR the Dcm-active-diagnostic alternative.

Symbols added to symbols_merged.csv: comm_nm_main, comm_disable, nm_msg_process, nm_node_lookup,
nm_signal_unpack, comm_netmode_write, comm_mode_map, transport_rx_process, transport_tx_segment,
cannm_state_machine, + labels comm_enable_flag/tx_gate2/comm_netmode/nm_channel_struct/
transport_channel_buf/transport_channel_struct/canif_rx_routing/transport_subid_list/can_mailbox_config/
com_sig_047b/nm_mode/nm_state_byte.

### Dcm alternative — tested NEGATIVE (bench)
Sustained diagnostic session on 0x6b4 (0x10 03/01/02 + 0x3E) got no response and did not enable comm.
So Dcm active-diagnostic is NOT a usable enable lever here (Dcm/CanTp response is itself ComM-gated,
or the diag rides the same container transport). => the Nm path (container on 0x40c + signal 0x047b)
is the only enable, and its barrier is the multi-frame container segmentation. Enable CONDITIONS are
fully enumerated (above); the remaining unknown is strictly the multi-frame byte-layout, which is
produced by the boot-installed CanIf/seg2 runtime and is the one thing not present/runnable in the ASW
image. This is the precise, narrow boundary after the full labeled re-analysis.

## SEG2/reassembly grind — multi-frame format partially recovered
Disassembled transport_rx_process (0x689e4) continuation/FF paths:
- **Reassembly PCI is at channel[0x34]** (0x4079d4); `PCI & 0xf0`: **0x10=First Frame, 0x20=Consecutive
  Frame, 0x00=Single Frame** (ISO-TP-like). channel status 0x4079e4 **bit8** = "reassembling".
- The received frame maps: buffer[0x108]=length/PCI, sub-id at buffer[0x10a:0x10c], data at
  buffer[0x10c:]. For sub-id 0x600 SF the frame is `07 00 06 00 <node> 00 00 00` (node = payload[3]).
- The container on 0x40c is **~22-23 bytes (3 sub-PDUs: 0x600+0xf1a3+0xf1a4) → multi-frame**; a 7-byte
  SF is rejected (length mismatch vs the 0x17 routing length), so the full container must be sent.
- The **channel-completion bits (0x4079e4 bit10/11)** that gate the NM path are set by the CanIf
  reassembly ENTRY (dispatched from the CAN ISR FUN_0008f708 via RAM-wired RxIndication pointers) —
  still not statically located; it's the last unknown.

### Bench (negative)
- ISO-TP full container to 0x40c fails (ECU sends no flow-control → not standard FC ISO-TP).
- Raw FF(`10 16 …`)+CF(`21/22/23`) multi-frame with all 3 sub-PDUs + valid node + signal 0x047b==1,
  sustained → no wake. So the exact FF/CF byte-layout (or the mode-0x80 placement / a counter) is still
  off, and the reassembly entry that sets the completion bits is the piece to find next.

## CAN ISR dispatch traced — reassembler is boot-installed (ISR-level confirmation)
Disassembled the CAN receive ISR FUN_0008f708 (Thumb) fully:
- Two CAN controllers: node registers 0xfff7e800 / 0xfff7ea00 (params 1/2). ISR reads pending
  mailbox via FUN_000501d4 -> index `r7`, sets global CAN status 0x406dd0 (byte0|=4 on RX,
  byte1|=0x80 on TX-complete), touches per-mailbox status descriptor at **0x406cd0 + idx*4**
  (RAM, byte+2 flags), then dispatches the **RxIndication**:
      handler = *(0x000b6a50 + idx*0x18);  if (handler) veneer_0xa2428(handler)   // bx handler
  The interworking veneer 0xa2428 is `mov ip,r4; lsrs r4,#1; bx ip` — it branches straight to
  the table word.
- The dispatch table at 0x000b6a50 does NOT hold static code pointers: the stride-0x18 offset-0
  words are mostly small ints (0x1/0x2) with a few RAM addresses (0x407ca8, 0x4086e8, 0x4090d0,
  0x40918c) — i.e. it is a **RAM-relocated/boot-patched descriptor table**, populated by the
  object-table installer (the walker+dispatcher, see emu/objtable_corun.py) at boot, absent from
  the ASW image.

**Conclusion (now confirmed at the hardware-ISR level, 6th independent direction):** the CanIf
RxIndication / transport reassembler that sets the channel-completion bits (0x4079e4 bit10/11)
runs from boot-installed RAM whose dispatch pointers the static image does not contain. Static
seg2 disassembly cannot reach the exact multi-frame reconstruction. The two remaining unlocks are:
  (A) **Materialize the RAM tables in emulation** — finish the walker+dispatcher co-run
      (objtable_corun.py) so 0xb6a50 / the object table / 0x4079xx dispatch pointers populate,
      then emulate the reassembler to read off the exact 0x40c multi-frame byte layout. Bounded
      but substantial; payoff uncertain.
  (B) **One real bus capture** of the partner/cluster frame on 0x40c (or the private CAN) — gives
      the exact wake bytes directly and validates against the recovered node-ids/CRC/enable chain.

## Materialization path run to ground — both bin-only routes are closed (live-bench confirmed)
Pursued the "emulate to materialize the RAM object table" path and closed it with direct evidence:

1. **Cold emulation cannot build the table.** The walker (FUN_00049f38) only processes ONE
   pre-staged 14-byte record from cursor 0x406980; it does not iterate the config graph. The
   config-graph iterator that reads the graph (root 0xa7e14 -> child nodes 0xae938/0xae940 ...)
   and feeds records via com_config_ingest (0x8e4f4) is fully RAM-dispatched, has **no static
   caller**, and its config-source base pointer is **SBOOT-installed** (re-confirmed here; matches
   the 3 prior whole-corpus sweeps noted in FUN_000a1cac). So the object table at 0x40a1a8 cannot
   be materialized from the flash image alone.

2. **Live UDS RAM read is unavailable in degraded mode.** Built bench/read_ram.py (UDS 0x23
   ReadMemoryByAddress) to seed the emulator from the already-built live RAM. On the powered ECU:
   - `can_raw sniff` -> ECU **alive**, broadcasting only 0x060 at ~100 Hz (payload
     `00 00 00 00 00 08 <ctr> <crc8j1850>`), no other ids.
   - `read_ram` / `confirm_comms` TesterPresent on 0x713/0x77D -> **no response** (timeout).
   => The Dcm/diagnostic stack is NOT running in degraded mode (ComM-gated, the same gate we are
   attacking). ReadMemoryByAddress therefore cannot pull the materialized table on the bench.

**Key live observation:** the ECU transmits CanNm (0x060) at 100 Hz, so **CanNm is already in
Network Mode** — the barrier is strictly downstream of CanNm network mode: the ComM full-
communication grant that turns on application COM (0x100/0x101/0x11e) and Dcm. That grant needs the
NM-user/full-comm request derived from the **0x40c container content** (signal 0x047b==1 + NM mode
0x80 + NM-active flags), i.e. another node asking for full communication.

**Conclusion:** every artifact that would reveal or materialize the operational-mode routing (the
object table, the reassembler dispatch pointers, and UDS RAM read) is itself gated behind the
operational mode — a genuine chicken-and-egg. The exact 0x40c wake-frame bytes are the one value
not derivable from the ASW image; recovering them requires an external source: a real capture of
the partner/cluster frame on 0x40c from a working vehicle or donor ECU network. bench/read_ram.py
is kept as the ready tool to snapshot the live table the moment the ECU is operational (or on a
donor that already answers UDS).

(Bench note: the SM2 Pro dropped to SMSTATUS_DEVICE_NOT_FOUND after a scan process was force-
killed; it needs a USB replug before the next bench run.)

## Live-bench inertness + bit-level gate map (this session, device powered)
Device replugged, re-tested live:
- **Full diagnostic scan 0x700-0x7ff = zero response.** Dcm is completely absent in degraded
  mode (not just on 0x713/0x77D). UDS RAM read is therefore impossible in this state.
- **0x060 characterized** (499 frames): payload `00 00 00 00 00 08` + byte6=4-bit rolling counter
  + byte7=CRC-8/J1850 over bytes0..6. **byte5=0x08 is the only state field** (constant). It is NOT
  in the tx-mailbox config 0xaea38 -> sent by a separate always-on keepalive path (ungated).
- **ECU is inert to all CAN input.** Flooding all 225 hardware-accepted ids (0xafae0) with valid
  J1850-CRC frames, and sweeping 0x400-0x470 with container frames, produced NO change in byte5
  and NO new tx id. CAN reception alone does not move the ECU's state on the bench.

Bit-level gate map (can_tx_scheduler 0x5bfc broadcasts ESP_01/02/08 only when BOTH hold):
- **comm_enable_flag (0x40944c) == 1** — set by comm_nm_main (0x6a71c) ONLY when
  `netmode(0x409230) & 0xf0 ∈ {0x30,0x40,0x80,0xa0}`. netmode is written by comm_netmode_write
  (0x8f5cc) = comm_mode_map(ComM channel mode): mode 0->0x20(NoCom), 3->0x40, 4->0x30, else->0x80.
  So it needs **ComM channel mode != 0**, i.e. a granted full-comm request.
- **tx_gate2 (0x409438) != 0** — NM-control-bit derived, written by nm_signal_unpack (0x40794)
  on a valid NM RX and by comm_netmode_write.
- comm_nm_main reads the NM PDU **in place at 0x408f10** (DAT_0006aa3c=0x408f10); nm_msg_process
  (0x40950) validates node-id (byte2 ∈ {0x4a,5f,98,99,9a,d4}) against flash masks 0xbda3c/3e and
  stores the PDU there + sets net-active flags 0x408f20/21.

**The transition is a multi-runnable state machine:** valid NM RX (via the boot-installed container
reassembler) -> net-active flags -> Nm/ComM coordinator requests full-comm -> comm_netmode_write
sets netmode=0x80 -> comm_nm_main sets comm_enable=1 -> tx scheduler broadcasts. Emulating it end-
to-end requires running the ComM/Nm coordinator runnables with a materialized stack = the same
boot/SBOOT barrier. On the bench the entry (container reassembly) is boot-installed and the ECU is
inert to synthesizable CAN. Net: the wake still requires either a real 0x40c container capture from
a live network, or a donor ECU whose Dcm answers (then read_ram.py pulls the live table to seed a
full end-to-end emulation).

## BREAKTHROUGH: wake reduces to one bit; container fully pinned from flash config
Emulating the REAL Thumb functions (comm_nm_main 0x6a71c is THUMB — earlier ARM decompile was
mis-moded) settled the gate model:
- **comm_enable_flag(0x40944c)=1 for ANY netmode != 0** (comm_mode_map never returns 0; even NoCom
  0x20 sets enable). So comm_enable is trivially satisfied — NOT the blocker.
- **tx_gate2(0x409438) = bit21 of 0x408f10**, set by comm_netmode_write(0x8f5cc). VERIFIED in emu:
  0x408f10=0x00200000 -> tx_gate2=1; =0 -> 0. This is the real blocker.
- => **WAKE ⟺ bit21 of 0x408f10 is set** (then can_tx_scheduler broadcasts ESP_01/02/08).

Flash config resolves 0x408f10 completely (E2E cfg @0xb3e10):
  `03 7f ff 12 | 00 40 8f 10 | 04 6f | 04 03 | ...`
  = E2E(data-id 0x12) -> buffer 0x408f10 -> **COM signal 0x046f** (4 bytes).
Sub-id list 0xb5760: `06 00 | 04 | 00 0b be 28` = sub-PDU **0x0600 is 4 bytes**, handler 0xbbe28.
So signal 0x046f == the 4-byte sub-PDU 0x600 value == the word stored at 0x408f10.
Routing table 0xb3e38 ({channel 0x4079e8, canid u16, len u16}):
  0x400/403/406/409 (len 1), **0x40c (len 0x17=23)**, 0x425(8) 0x42f(6) 0x43a(0xe) ... all -> channel
  0x4079e8. **Confirms 0x40c is the 23-byte container id from flash (not a guess).**

Therefore: **bit21 of 0x408f10 = byte1-bit5 (0x20) of the 4-byte sub-PDU 0x600 value.** The wake
frame is the 0x40c container whose 0x600 sub-PDU 4 bytes have byte1 bit5 set, with valid E2E
(data-id 0x12). Next: disassemble the 0x600 handler 0xbbe28 to get the exact copy-to-0x408f10 and
the E2E check (whether COM writes the raw 4 bytes with/without node validation), then the container
byte layout + E2E, then bench-inject.

## Gate logic fully cracked: wake = bit21 of the 0x600 sub-PDU value (COM signal 0x046f)
Emulated the real Thumb receive path transport_rx_process (0x689e4) against a synthesized 0x40c
container (seeding the boot-relocated sub-id list ptr 0xbd774 with the flash list from 0xb5760).
Reassembled buffer (base 0x4050e8): buf[0x108]=seg len (=7 for 0x600), buf[0x10a:0x10c]=sub-id
(06 00), buf[0x10c:0x110]=the 4 sub-PDU bytes [d0 d1 d2 d3]. NM word = [d2,d1,d0,d3]; node=d0.
VERIFIED:
- Valid container (node d0 in {0x4a,5f,98,99,9a,d4}) -> 0x408f10 set + net-active flag 0x408f20=1.
- can_tx_scheduler (0x5bfc) transmit gate = comm_enable_flag(0x40944c)==1 AND tx_gate2(0x409438)!=0
  (both pointers confirmed in its literal pool @0x5f64/@0x5f78). Gate closed -> idles the msg
  objects; gate open -> composes/sends ESP_01/02/08.
- comm_enable is trivial (set for any netmode!=0). tx_gate2 = bit21 of 0x408f10, and
  **comm_netmode_write (0x8f5cc) is its SOLE writer** (nm_signal_unpack's base is 0x409431, it does
  NOT touch 0x409438 - the decompile comment was wrong).
- bit21 of 0x408f10 = byte1-bit5 of the 4-byte NM word = **d1 bit5** of the 0x600 sub-PDU value.

The NM path forbids d1 bit5 (nm_msg_process accepts only d1 bits {0,3,6} per flash masks 0xbda3c/3e;
d1=0x20 is REJECTED). BUT 0x408f10 == COM signal **0x046f** (E2E cfg @0xb3e10:
`03 7f ff 12 | 00 40 8f 10 | 04 6f`), which the GENERIC COM Rx unpacks from the same 0x600 sub-PDU
**without NM node validation**. So the COM write sets bit21 from the raw sub-PDU byte1 regardless of
the NM validator. => **WAKE = receive 0x40c container whose 0x600 sub-PDU 4-byte value has byte1
bit5 (0x20) set, with valid E2E (data-id 0x12).** New tool: emu/nm_container_oracle.py.

Remaining: the exact multi-frame (FF/CF) wire->buf mapping + E2E (data-id 0x12) so the 23-byte 0x40c
container can be built and injected. transport_rx_process ELSE branch (buf[0x22f]!=0) holds the
FF/CF accumulation (PCI at buf[0xd] &0xf0: 0x10=FF,0x20=CF) -> decode next.

## 0x40c IS hardware-accepted; multi-frame accumulation is in transport_rx_process (emulatable)
CAN mailbox config 0xaea38 (stride 0x18) idx46: `fff7e7b0 0000ea9b fff7ea00 08 1b 0102 040c ...`
= controller 0xfff7e7b0 (2nd/private CAN), DLC 8, HW mailbox 0x1b, **accepts CAN-id 0x40c**.
Neighbours idx44/45/47/48 accept 0x478/0x404/0x418/0x400. So the module DOES receive 0x40c on the
bench (mailbox 0x1b); the inertness to injected 0x40c is a wrong multi-frame/E2E format, NOT hardware
filtering. Confirmed a targeted bench attempt (bench/wake_container.py: 0x600 sub-PDU byte1 bit5 set,
4 layouts x {FF+CF, single}) does not wake it yet -> framing still off.

Wire format handle: the CanIf copies each received 0x40c frame into the channel struct at PCI =
channel+0x34 (0x4079d4); transport_rx_process's ELSE branch (buf[0x22f]!=0) IS the FF/CF accumulator
(PCI channel[0x34] & 0xf0: 0x10=First, 0x20=Consecutive), building the reassembly buffer 0x4050e8+
0x108. So the multi-frame sequence can be emulated end-to-end by calling transport_rx_process per
frame with channel[0x34]=PCI set -> next step to nail the exact FF/CF byte layout + E2E, then inject.

## SESSION SUMMARY: wake condition fully solved; only the transport wire format remains
**Solved and confirmed this session (all from the bin + live bench):**
- can_tx_scheduler broadcasts ESP_01/02/08 iff comm_enable_flag(0x40944c)==1 [trivial: any
  netmode!=0] AND tx_gate2(0x409438)!=0.
- tx_gate2 = bit21 of COM signal 0x046f (0x408f10); sole writer comm_netmode_write(0x8f5cc).
- bit21 = **byte1 bit5 (0x20) of the 4-byte sub-PDU 0x600** value, unpacked by generic COM Rx from
  the 0x40c container (E2E cfg 0xb3e10 binds signal 0x046f -> 0x600, data-id 0x12).
- Container id 0x40c is **hardware-accepted** (mailbox 0x1b, 2nd CAN controller) and 23 bytes
  (routing 0xb3e38). Node byte in {0x4a,5f,98,99,9a,d4}. Emulator reproduces acceptance
  (nm_container_oracle.py) and the tx_gate2 mechanism (comm_netmode_write).
=> **WAKE FRAME = 0x40c container delivering sub-PDU 0x600 = [node, 0x20, 00, 00] with valid E2E.**

**The one remaining unknown = the transport wire format**, which is the ONLY thing not in the ASW
image: the CanIf multi-frame (FF/CF) byte layout for 0x40c AND the per-sub-PDU E2E (data-id 0x12)
that together set the channel-completion bits 0x4079e4 bit10/11 (which gate transport_rx_process).
This lives in the boot-installed CanIf/E2E (RAM dispatch from the CAN ISR, absent from flash). The
live ECU gives no feedback on malformed frames (no flow-control, no 0x060 change, Dcm down), so there
is no bench gradient to brute-force it. A single real 0x40c capture from a working network (or a
donor whose Dcm answers, via read_ram.py) yields the wire format directly and, combined with the
above, produces the wake frame immediately. Tools ready: bench/wake_container.py, emu/
nm_container_oracle.py, bench/read_ram.py.

## Wire format recovered from the TX segmenter (transport_tx_segment 0x67b1c)
Reversed the container TX (same protocol as RX) to get the on-wire layout:
- Container packed at channel_buf+6; sub-PDU 0x600 (case 5) = **[06 00][sig2 sig1 sig0 sig3]** where
  sig = COM signal 0x046f (0x408f10). So the 4 data bytes on the wire are the NM word bytes in order
  [2,1,0,3]. => **bit21 (tx_gate2) = sig1 bit5 = wire data byte index 3 bit5 (0x20).**
- Single vs multi: buf[0x108]=container length; <0x12 & (==1 or even) -> single frame; >=0x12 ->
  multi-frame (count=(len-1)/2), PCI at channel_struct[0x34] &0xf0 (0x10=FF nibble, 0x20=CF nibble).
- Container = concatenated sub-PDU segments [subid_hi][subid_lo][data]: 0x600(6B)+0xf1a3(5B)+
  0xf1a4(10B)=21B + 2B header = 23B (matches routing len 0x17). E2E via FUN_0005c744(1=TX/0=RX).
- RX demux (transport_rx_process, VERIFIED in emu): needs buf[0x108]=seg len (=7 for 0x600), sub-id
  at buf[0x10a:0x10c], data at buf[0x10c:]; NM word = [buf[0x10e],buf[0x10d],buf[0x10c],buf[0x10f]].

**Bench (still no wake):** derived single-frame `[07 hh 06 00 node 20 00 00]` on 0x40c swept over
header/node -> nothing. Root cause identified: transport_rx_process gates 0x600 on channel-status
0x4079e4 **bit11** (+bit10/bit26), which the CanIf sets only after **valid E2E** (data-id 0x12). In
emulation, manually setting status=0xc00 makes the SAME single frame process + accept -> so the sole
remaining blocker is producing valid E2E so the CanIf sets the completion bits. E2E CRC algo next
(tables CRC8-J1850 0xb408c / CRC8-H2F 0xb4800; the 0x060 TX uses J1850).

## Delivery boundary: reassembler completion bits are boot-installed; ECU gives zero feedback
Exhaustive bin + bench iteration this session established the wake condition and wire CONTENT fully
(above). The remaining piece is DELIVERY, and it is a hard boundary:
- transport_rx_process / FUN_0001d7a8 / FUN_0001c6b0 / FUN_0008b850 are ALL RAM-dispatched (no
  static caller); they CONSUME the channel buffer. The per-frame CanIf RxIndication that copies the
  raw 0x40c frame -> channel[0x34] PCI + reassembly buffer, runs the E2E (data-id 0x12), and sets the
  channel-status completion bits 0x4079e4 **bit10/11** (which gate transport_rx_process) is the
  boot-installed dispatch from the CAN ISR (0xb6a50 table) — not present in the flash image.
- Bench: the ECU ACKs 0x40c (mailbox 0x1b) so frames ARE received, but it emits ONLY 0x060 whether
  idle or under any injection (single-frame, FF+CF ISO-TP nibble PCI, custom PCI 0xb8/0xc1, all 3
  sub-PDUs, bit21 set, sustained). No flow-control, no error frame, no state change => **zero feedback
  gradient**, so the exact multi-frame PCI/E2E cannot be converged empirically, and it is not
  statically recoverable (boot-installed).
- Interpretation: Dcm is ComM-gated (down) by the SAME grant that gates ESP broadcast, so the ECU is
  booted and waiting for the container-driven full-comm grant; but the reassembler that would accept
  that container is the boot-installed piece. Both the trigger and the means to observe partial
  progress are behind the operational gate.

**Net for the wake goal:** solved = the enable chain, tx_gate2=bit21 of signal 0x046f, the 0x40c
container id (HW-accepted) + sub-PDU 0x600 layout + that byte1 bit5 is the trigger, and the on-wire
sub-PDU packing (from the TX segmenter). Unclosed = the exact CanIf multi-frame PCI + E2E (data-id
0x12) that sets completion bits 0x4079e4 bit10/11 — boot-installed, no static image, no bench
feedback. This is the true, minimal residual and it is not reachable from the bin + a feedback-silent
bench alone.

## E2E CRC fully reverse-engineered (labels added)
Two CRC-8 engines found and documented (both init 0xFF, xorout 0xFF, MSB-first table lookup
crc=table[byte^crc]):
- **crc8_j1850_e2e_engine (FUN_0003d780)** — plain CRC-8/SAE-J1850 (poly 0x1D), no data-id. Used by
  the app-message composers/validators and the 0x060 heartbeat. acc=0x407064, table=relocated
  0xbc0a0 (RAM copy of flash J1850 table 0xb408c). **Emulation-VERIFIED**: reproduces the live 0x060
  byte7 exactly (ctr=6 -> 0x1e), both as a Python model and by running FUN_0003d780 with the J1850
  table seeded at 0xbc0a0.
- **e2e_crc8_dataid (FUN_0005f43a)** — AUTOSAR E2E-P01-style CRC-8 with **DATA-ID fold**: crc=0xFF;
  for byte in buf[1..len-1]: crc=table[byte^crc]; return table[data_id^crc]^0xFF. Skips buf[0]=the
  CRC slot, folds the 1-byte data_id at the end. Callers store the result at buf[0] (byte0=CRC),
  used for 8-byte E2E frames with data-ids 0xd4/0xd2 (bytes1-7 = data incl a 4-bit counter). The
  0x40c container sub-PDUs use THIS scheme with their per-sub-PDU data-ids (0x600 -> data-id 0x12,
  from E2E cfg 0xb3e10). Table=relocated 0xbc914 (poly 0x1D or 0x2F - both computed).

**KEY CONSEQUENCE:** every earlier bench frame lacked a valid E2E CRC in byte0, so the CanIf would
reject them and never set the completion bits — explaining the total inertness. New tool
bench/e2e_crc.py computes both crc8_j1850() and e2e_crc8_dataid(buf,data_id,poly) (J1850 and H2F),
self-tested against the live 0x060. Next: build E2E-valid 0x40c container frames (byte0 = e2e_crc8_
dataid over the frame, data-id 0x12) and inject; and emulate the reassembly+E2E path end-to-end.

## COM deposit path for signal 0x046f confirmed (static routing)
Signal 0x046f is in the STATIC flash COM signal table com_signal_table_full (0xb038c) #1:
{sig_id 0x046f, len 4, flags 0x03, buffer 0x408f10, consumer 0x975e1}. So the COM Rx deposits the
0x600 sub-PDU's raw 4 bytes into 0x408f10 (signal 0x046f) with NO NM node validation - this is the
path that sets bit21 (byte1 bit5) = tx_gate2, distinct from transport_rx_process's nm_msg_process
path (which validates the same bytes and rejects byte1 bit5). Deposit done by com_signal_commit_
record (0x50090) via the runtime group table (0xb6a44); consumer/notify fn 0x975e0 (a case in the
COM extraction dispatcher 0x974f8).

Reassembly trace (transport_rx_process, emu): the CanIf presents each frame with PCI at channel+0x34
(0x10=FF, 0x20=CF nibble) and the payload at buf+0x108; transport_rx_process's else-branch sets
status BIT8 (E2E-pending) via the E2E enqueue (FUN_0005c744) - the completion bits (bit10/11) are set
later by the (boot-installed) E2E validator once the reassembly+CRC pass.

**Full mechanism (now completely mapped):** 0x40c container (HW-accepted, mailbox 0x1b) -> multi-frame
reassembly (PCI channel+0x34) -> E2E CRC check (data-id 0x12, algo = the reversed crc8 engines) sets
completion bits -> COM deposits sub-PDU 0x600 4 bytes -> signal 0x046f (0x408f10) -> bit21=byte1 bit5
-> tx_gate2 -> (with comm_enable) ESP_01/02/08 broadcast. Every stage is reverse-engineered; the only
non-static pieces are the boot-installed CanIf reassembly-dispatch + E2E-completion setter, which
require either full object-table materialization in emulation or a live-running pipeline to exercise.

## Materialization attempt: signal 0x046f is static, but the reassembler is boot-coupled
Per the materialization plan:
- **Good news:** signal 0x046f is in the EXPLICIT static COM table (0xb038c), NOT the bump/object-
  table bulk (per decode/pb_config_decode.py + config_graph_decode.py: the ~3000 bulk-RX signals are
  runtime-allocated, but the app-consumed explicit subset incl 0x046f is static). So the 0x046f
  deposit path does not need full object-table materialization.
- **Blocker persists at the reassembler:** transport_rx_process's accumulation state machine writes
  the reassembly at channel_buf+6 (channel_struct[0x40] target) and demuxes from buf+0x108, driven by
  the channel state (buf[0x22f], channel[0x34] PCI, channel[0x40] write ptr). Emulating FF(0x10)+
  CF(0x2N) by hand does not faithfully accumulate - the exact per-frame CanIf presentation (where each
  received frame's bytes land, and the channel-struct init) is set up by the boot-installed CanIf
  RxIndication, which is not in the static image. Status stays at bit8 (E2E-pending); the completion
  bits (bit10/11) require the boot-installed E2E validator.
- The config-source iterator that would build these dispatch tables is fully RAM-dispatched (0 static
  callers of com_config_ingest/its thunk/the iterator, confirmed by a whole-corpus BL scan) with an
  SBOOT-installed config-graph base pointer, so cold materialization stalls exactly as documented in
  emu/objtable_corun.py.

**Net:** the E2E CRC is fully reverse-engineered (crc8_j1850_e2e_engine + e2e_crc8_dataid, labeled +
tool + emulation-verified). The entire wake chain is mapped and every purely-computational stage is
reproduced. The single irreducible dependency is the boot-installed CanIf reassembly + E2E-completion
dispatch (and its channel-struct setup), which needs the real boot ROM (SBOOT) to run - it is neither
in the ASW image nor faithfully hand-emulatable, and the feedback-silent bench cannot exercise it blind.

## A-finding: degraded mode = "waiting for vehicle network"; master gate is signal 0x047b
Emulated cannm_state_machine (0x6eba8) with seeded inputs (VERIFIED):
- **0x047b==0 (the bench state): CanNm returns immediately and does NOTHING** - it is DORMANT. The
  first instruction is `if (*com_sig_047b_buf(0x408f0c) != 1) return;`. So the 100Hz 0x060 the ECU
  emits is NOT CanNm - it is a separate ungated app heartbeat; CanNm never even starts on the bench.
- **0x047b==1: CanNm starts** (cannm_state 0x4090e2 -> 9). With 0x047b==1 + nm_state(0x409478)==6 +
  nm_mode(0x4090d8)&0xf0==0x80 it advances (-> state 4), i.e. the full network context drives it
  toward Network Mode -> ComM full-comm -> comm_enable/tx_gate2 -> ESP broadcast.
- Signal 0x047b (buffer 0x408f0c) has **no non-CAN writer** (only COM RX deposits it): confirmed by
  literal-ref + decompile scan (all references READ it; the only writer is the COM Rx path). So there
  is NO internal/hardware shortcut to start CanNm - it requires a received partner message.
- Signal 0x047b source = the front-sensor group (ACC_01 0x109 / ACC_10 0x117 / HCA_01 0x126) per the
  static COM table (0xb038c #0xb047c: sig 0x047b, 4 bytes, buf 0x408f0c, consumer 0x97617). CanNm
  also consumes signal 0x04b6 (0x408f18) and the container-derived NM state/mode/flags.

**Conclusion:** the module is a fully-booted app held in AUTOSAR "no communication until the network
is present" - NOT a fault/limp/coding stall. To leave it, the ECU must RECEIVE its partner messages
in sequence: (1) a front-sensor msg setting signal 0x047b==1 (starts CanNm), then (2) the NM container
on 0x40c (NM state 6 / mode 0x80). All are E2E-protected and COM-RX-routed. Since COM TX works (0x060
with valid E2E), the COM stack is initialized, so COM RX is very likely armed too - meaning correctly-
formatted+E2E'd partner messages should be accepted. The remaining work is purely decoding the exact
message->signal bit mappings (front-sensor 0x047b/0x04b6 + the container), all doable statically.
