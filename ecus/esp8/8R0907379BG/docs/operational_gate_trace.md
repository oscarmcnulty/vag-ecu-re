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
