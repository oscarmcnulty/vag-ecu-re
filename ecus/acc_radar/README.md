# ACC radar — diagnostic connection (B8 Q5, address 13)

Goal: a diagnostic connection to the factory ACC radar so we can read raw radar
values. This pack currently documents **how to connect**; value extraction comes
after the module answers and we enumerate its DIDs.

## Module identity
- VAG name: **AdaptCruisContr** (adaptive cruise / distance regulation), VCDS **address 13**, component **J428**.
- The B8 Q5 factory ACC is a single front radar (see repo memory `b8-acc-radar-hardware`).

## Diagnostic connection (confirmed)
| Parameter | Value |
|-----------|-------|
| Transport | ISO15765 / ISO-TP, 500 kbps, 11-bit |
| Request ID (TX) | **0x757** |
| Response ID (RX) | **0x7C1** |
| Rule | VW diag range: `resp = req + 0x6A` |
| Path | OBD-II pins 6/14 → gateway routes addr 13 (same as VCDS/ODIS) |

The `0x757`/`0x7C1` pair is corroborated four ways:
1. ODIS CAN-ID table `simos-suite/data/can_ids.properties` → `LL_AdaptCruisContrUDS = 757 / 7C1`.
2. opendbc VW config: `(Ecu.fwdRadar, 0x757, None)` with `VOLKSWAGEN_RX_OFFSET = 0x6a`.
3. The repo's own ABS anchor (addr 03 = `0x713`/`0x77D`, same `+0x6A` rule).
4. VW convention (ACC = address 13).

## Evidence the radar is present and live on THIS car
From the car's own rlogs (`AUDI_Q5_MK1` fingerprint):
- `ACC_01` (0x109), `ACC_02` (0x30C), `ACC_05` (0x10D), `HCA_01` (0x126) are all broadcasting.
- So the factory radar exists and is active — there is a module to talk to.

Caveat worth knowing before the first on-car run:
- openpilot's firmware fingerprint on this car captured engine/trans/EPS/airbag but
  **no 0x757 radar response**. That is most likely the comma harness's bus routing /
  OBD-multiplexing, not the radar. A Tactrix in the OBD-II port goes through the
  gateway like VCDS, which is the path that does reach address 13. If `0x757` is
  still silent, use `--find` to probe the sibling assist modules and locate it.

## How to run (read-only, Linux + Openport/Tactrix)
Reuses the proven Openport J2534 path (`/usr/local/lib/j2534.so`, same as the EPS
probe). Script lives beside the other `op_*` scripts in the VW_Flash tool:

```bash
cd ~/tools/VW_Flash
python3 op_acc_probe.py            # TesterPresent + identity DIDs (safest)
python3 op_acc_probe.py --find     # if 0x757 silent: probe sibling assist modules
python3 op_acc_probe.py --did-sweep  # read-only 0x22 discovery → find raw-value DIDs
```

Ignition on, engine off, battery charger on. The script only uses 0x3E / 0x10
(default+extended) / 0x22 — no security, no write, no routine — and restores the
default session on exit.

## Raw radar values — next step after connecting
The broadcast `ACC_01/02/04/05` messages carry controller *outputs* (desired accel,
target speed, distance index), **not** per-object radar tracks (range / range-rate /
azimuth). Raw object data, if exposed at all, lives behind UDS on the radar:
- `--did-sweep` enumerates which `0x22` DIDs answer (VW measurement band ~0x0200..0x02FF
  by default; widen with `--sweep-range`). That is how we find the raw-value DIDs
  empirically, since we have no radar ODX/label file.
- If no useful measurement DID exists, the fallback is reading the radar's internal
  object CAN on the bench, or RE of the radar firmware (not started here).

## On-car result (2026-10-15, Openport over OBD-II)
Ran `op_acc_probe.py --find` and `op_diag_sweep.py` (read-only). The Openport +
gateway path is healthy — **6 modules answered UDS in 37 s**:

| Req | Module | Part | System |
|-----|--------|------|--------|
| 0x7E0 | Engine (Simos 8.5) | 8R0907551F | 3.0l V6 TFSI |
| 0x7E1 | Transmission | 8R0927158AM | 0BK 30TFSIUSA |
| 0x715 | Airbag | 8R0959655F | AirbagVW-AU10 |
| 0x752 | Parking brake (EPB) | 8K0907801M | EPB-4 |
| 0x712 | Steering (EPS) | 8R0909144F | RCEPS |
| 0x74E | Side-assist radar | 8T0907566B | SWA Master |

**The front ACC radar at 0x757 did NOT answer** (nor the front camera 0x74F). Both
the Openport path and openpilot's harness FW query (in the rlogs) fail to reach 0x757.

A front radar IS functionally present: rlog `ACC_01` (0x109) carries a live longitudinal
demand (`ACC_Sollbeschleunigung` −3.00…+0.12 m/s², 161 distinct values, status regulating),
so a radar is feeding the engine's ACC controller — it just isn't exposing a UDS endpoint
at 0x757 over the routed diagnostic bus in the probed state.

### Leading explanations (ranked) and next steps
1. **Radar asleep.** Convenience-domain modules (side radar) wake on ignition; the front
   ACC radar may only boot/answer with the **engine running** (or in a drive state).
   → Re-run `op_diag_sweep.py` with the engine running. Cheapest test, do first.
2. **Not ISO-TP / not at 0x757 on this B8.** The B8 ESP8 ABS uses TP2.0/KWP2000, not plain
   ISO-TP (repo `esp8-odis-flash-capture`). The front radar could likewise be a TP2.0 module
   or sit on a private radar↔engine CAN not bridged to OBD diagnostics. → If (1) fails, add a
   TP2.0/KWP2000 probe (channel setup to ECU address 0x13) and/or check gateway OBD-multiplex routing.
3. **Raw values aren't in diagnostics anyway.** Broadcast `ACC_01/02` are controller OUTPUTS,
   not per-object tracks. True raw radar objects live on the radar↔engine link → bench tap or
   firmware RE. For openpilot longitudinal, `ACC_01` (already live on the bus) is the usable signal.

## VERDICT (2026-10-15): no ACC radar module on this car
Three independent methods agree the ACC radar is not a reachable module here:
1. **UDS/ISO-TP full sweep** (0x700–0x795 + 0x7E0–0x7EF): 6 modules, no radar/camera.
2. **TP2.0/KWP2000 full scan** (addr 0x01–0xFF, `op_tp20_scan.py`, validated by the ABS
   positive control returning the exact ODIS-capture IDs ecuTX=0x300/testerTX=0x4A3):
   21 modules answer channel-setup, but **addr 0x13 (ACC) and 0xA5 (front camera) do NOT**.
   The gateway has no route/installation for 0x13.
3. **rlog provenance**: `ACC_01/ACC_02/ACC_05/HCA_01` are in openpilot's `sendcan` — comma
   is *transmitting* them. There is no factory-radar broadcast being received; the live
   accel values are openpilot's longitudinal command, not radar output.

Conclusion: this vehicle has no factory ACC radar, so there is nothing to connect to at
address 13 and no raw radar values to read on-car. `HCA_01` is openpilot's steering TX.

### If raw radar values are still the goal
- Retrofit a factory front radar (donor — see repo memory `mlb-stopgo-donor`). Once coded
  into the gateway it appears at addr 0x13 and this probe (`op_acc_probe.py`) will reach it.
- If the real goal is just openpilot longitudinal, the `ACC_01` TX path openpilot already
  uses is the mechanism; no radar read is required.

## Tooling delivered (read-only, Linux Openport via /usr/local/lib/j2534.so)
- `~/tools/VW_Flash/op_acc_probe.py`  — UDS identity probe of ACC 0x757/0x7C1 (+ siblings, DID sweep)
- `~/tools/VW_Flash/op_diag_sweep.py` — UDS ISO-TP module sweep (ODIS list or `--full` range)
- `~/tools/VW_Flash/op_tp20_scan.py`  — VW TP2.0 channel-setup presence scan (raw CAN)

## UPDATE 2 (2026-10-15): VCDS reaches addr 13; Openport blind-probe cannot
User confirms VCDS communicates with address 13, so the radar IS present. Exhaustive
read-only probing from the Openport on OBD pins 6/14 still cannot reach it:

| Approach | Tool | Result |
|---|---|---|
| UDS ISO-TP 0x757/0x7C1 | op_acc_probe.py | silent |
| UDS full range 0x700-0x795 (resp=req+0x6A) | op_diag_sweep.py --full | 6 modules, no radar |
| UDS raw-CAN wide 0x600-0x7FF (reply on ANY id) | op_uds_widescan.py | no radar |
| UDS 29-bit normal-fixed (0x18DAxxF1) | op_29bit.py | silent |
| UDS functional broadcast 0x700 | op_poke/patient | 6 modules reply, no radar |
| TP2.0 setup addr 0x13 (clean, 3 addr variants) | op_tp20_clean.py | no D0 channel |
| TP2.0 full scan 0x01-0xFF | op_tp20_scan.py | 21 modules, not 0x13 |
| Patient 30s hammer 0x757 + 0x13 | inline | silent |
| Gateway 0x19 (TP2.0) / 0x710,0x773 (UDS) | inline | unreachable |

**Structural findings**
- The OBD port here is an isolated **diagnostic CAN**: with no tester active it is
  completely idle (op_sniff.py logs 0 frames). All modules are reached via gateway routing.
- 27 modules answer: 6 via UDS ISO-TP (engine 0x7E0, trans 0x7E1, airbag 0x715, EPB 0x752,
  EPS 0x712, side-radar SWA 0x74E) and 21 via TP2.0 channel-setup proxied by the gateway
  (all share ecuTX=0x300, testerTX≈0x4A0+addr) incl. ABS 0x03, AWD 0x22, suspension, doors,
  MMI, tuner, roof, parking brake.
- The **gateway itself answers no direct diagnostics** (0x19/0x710/0x773 all silent) yet
  proxies the TP2.0 setups — so its routing/installation list is the key, and it has no
  entry that my probes hit for address 13.

Conclusion: the radar is not presented on this diagnostic CAN by any standard transport I
can drive blind. VCDS reaches it via gateway routing / an init sequence that blind probing
can't reproduce. The decisive step is to OBSERVE VCDS.

### Capture plan (the authoritative way to get the exact approach)
`op_sniff.py` is a passive CAN logger (confirmed working). With an OBD-II Y-splitter, run
both the Openport and the Ross-Tech HEX in the port:
```bash
cd ~/tools/VW_Flash && python3 op_sniff.py --out /tmp/vcds_acc.log
# then in VCDS: Select -> 13 (Auto Dist. Reg.) -> read faults / measuring values -> close
```
Share `/tmp/vcds_acc.log`; the diagnostic-range frames (0x200-0x2FF TP2.0, 0x600-0x7FF
UDS/KWP) reveal the exact request/response IDs + protocol the radar uses. No splitter?
Enable VCDS debug logging (Options -> Debug) and share that log instead — it records the
TX/RX frames. Either one lets us replicate the connection exactly.

## Tooling (all read-only, Linux Openport /usr/local/lib/j2534.so)
op_acc_probe.py · op_diag_sweep.py · op_uds_widescan.py · op_29bit.py ·
op_tp20_scan.py · op_tp20_clean.py · op_tp20_ident.py · op_sniff.py

## UPDATE 3 (2026-10-15): radar identified; VCDS transport = gateway-routed TP2.0
VCDS (Windows VM, Ross-Tech HEX-USB 0403:fa24) DOES reach address 13:
- **Part 8R0 907 561 A, component "ACC3 H11 0100", J428, Bosch (RB8-658), built 2013-06-26.**
- Fault seen: 01314 Engine Control Module / implausible signal (freeze frame present).

USB capture of the HEX (via `usb.sh capture`, QEMU pcap): the HEX **encrypts its diagnostic
payload** (Ross-Tech anti-clone), so live CAN bytes are NOT readable from it (unlike the
ODIS/SM2 ABS capture, which was plaintext J2534). What IS readable is the unencrypted HEX
interface config (`53 LEN .. CKSUM` frames): the `b4 <slot> <id16>` commands program CAN
RX-filter IDs, decoded as `id16>>5`. During the address-13 session VCDS filtered on
**0x300 (TP2.0 data channel, = gateway ecuTX), 0x77A (gateway UDS resp), + a 0x2xx setup id**.
So VCDS reaches the radar via **gateway-routed TP2.0**, data on 0x300 — the same transport
my scan saw the gateway proxy for 21 modules. (My direct TP2.0 setup to 0x13 still got no
channel, so HOW VCDS makes the gateway open 0x13 is the one remaining unknown; it is inside
the encrypted payload.)

Decoded the OLD plaintext ABS capture (SM2 Pro 20a2:0001) for the on-wire frame format:
- USB carrier record: `[len u32 LE][can_id u32 LE][data]`.
- TP2.0 channel setup: CAN 0x200, data `<dest> C0 00 10 00 03 01`; resp on 0x200+dest
  `00 D0 <ecuRX16LE> <ecuTX16LE> 01` (e.g. ecuRX=0x300, ecuTX=0x4A3).
- TP2.0 **data frame = `[0x2X opcode][2-byte BE length][UDS payload]`** (NOT 0x1X). UDS 0x22
  ReadDataByID works; response `2X 00 LL 62 F1 87 <ascii "8R0907561A"…>`. Multiple DIDs can be
  batched. This corrects the op_tp20_ident app layer (it used opcode 0x10 → acked but ignored).

### State / recovery
- Openport (0403:cc4d) is currently NOT on Linux USB (swapped out for the HEX to run VCDS);
  the op_* J2534 tools need it back + ChromeOS USB share.
- The capture left a stray device on QEMU usb port 4; the HEX auto-reattach fails. Recover
  by SPICE-redirecting the HEX in virt-manager, or restart the VM.

### Cleanest next step to get the exact address-13 open sequence
Run **ODIS over the SM2 Pro / Openport** (plaintext J2534) to address 13 while capturing with
`usb.sh capture start <vid:pid>` — decodes fully like the ABS capture → exact setup + routing.
Or Openport + OBD Y-splitter running op_sniff while VCDS talks to 13 (raw CAN, trivial decode).

## SOLVED (2026-10-15): ACC radar reachable over OBD — it's TP2.0 logical 0x0B
VCDS "address 13" = VW **TP2.0 logical address 0x0B** on the wire (the gateway install
list maps display-addr 13 -> logical 0x0B). Direct TP2.0 setup to 0x13 gets no channel;
**0x0B is the radar**. Confirmed live via the Linux Openport on the OBD port:

```
part (F187): '8R0907561A'   name (F197): 'ACC3'   sw (F189): '0100'   hw (F191): '8R0907561A'
DTC (18 02 FF 00): 58 01 0522 28  -> DTC 0x0522 = 1314 = "Engine Control Module implausible" (matches VCDS)
measuring blocks 21 01..: blocks 1,2,7,8,10,12 return live data (raw radar values path)
```

### Working recipe (READ-ONLY, Linux Openport /usr/local/lib/j2534.so, raw CAN)
1. TP2.0 setup:   TX CAN `0x200` = `0B C0 00 10 00 03 01`
2. setup resp:    RX CAN `0x20B` = `00 D0 00 03 ab 04 01`  -> recv on **0x300**, send on **0x4AB**
3. channel params: TX `0x4AB` = `A0 0F 8A FF 32 FF` ; ECU RX `0x300` = `A1 0F 8A FF 4A FF`
4. data frame:    TX `0x4AB` = `[0x1X|seq][len_hi len_lo][service...]` (single/last = nibble 0x1)
5. response:      RX `0x300` consecutive `0x2X` + last `0x1X`; ACK each last with `0xB{seq+1}`
   first response frame carries the 2-byte BE length after its opcode.
6. services: `10 89` StartDiagSession, `3E` TesterPresent, `22 F1xx` ReadDataByID,
   `18 02 FF 00` readDTCByStatus (KWP; UDS `19` is NOT supported), `21 xx` readMeasuringBlock.

Why earlier scans missed it: every UDS probe (0x757 etc.) and every direct TP2.0 setup to
0x13 failed because the radar is at logical 0x0B, not 0x13, and it speaks KWP-over-TP2.0 (not
UDS-on-11-bit). The breadcrumb was the VCDS HEX capture: during the address-13 session the
interface filtered CAN `0x20B` (= setup-response of logical 0x0B) alongside the `0x300` TP2.0
data channel. The HEX payload is encrypted, but that unencrypted filter pointed straight here.

Tool: `~/tools/VW_Flash/op_acc.py` (connect 0x0B, read id/DTC/measuring blocks).
Next: decode the measuring blocks into physical radar values (needs the block scaling /
label file, or reverse from the firmware image) -- that is the remaining step for raw targets.

## Measuring-block map (2026-10-15, decoded live, stationary/no-target)
Blocks read via KWP `21 <group>` on the 0x0B channel; 3-byte `[formula][a][b]` fields.
Formula bytes are VAG's self-describing scaling (table from AndrOBD/KLineKWP1281Lib):
`0x06`=a*b*0.001 V, `0x1a`=b-a degC, `0x70`=(b-128)*a*0.001 deg, `0x77`=a*b*0.01 %,
`0x4b`/`0x59`/`0xa1`/`0x25`=16-bit (a*256+b, 0xffff=invalid). Decoder: `op_acc_blocks.py`.

| Grp | Fields (decoded) | Interpretation |
|-----|------------------|----------------|
| 001 | 65535,65535,65535 (0x4b) | object slots — 0xffff = NO TARGET (stationary) |
| 002 | -0.040, +0.032, +0.416 deg (0x70) | **angles** — radar azimuth / alignment |
| 007 | 13.06 V, 135(text), 0%, 24 degC | supply voltage (LIVE), status, %, internal temp (LIVE) |
| 008 | 2,3,2,4 (0x4b) | small counts / per-object status |
| 010 | 16,0,8,0 (0xa1) | bitfield/status |
| 012 | 129,0 (0xa1) | bitfield/status |
| 013 | 0, 685, 284, 452 (0x4b) | 16-bit values present (candidate object range/signal) |
| 014 | 65535×4 (0x4b) | object slots — NO TARGET |
| 015 | 4032, 368, 25, 7979 | counters / operating values |
| 048 | 80-byte raw block | detailed object list (structured, needs field spec) |
| 049 | 28-byte raw block | detailed object list (structured) |

Scaling/labels note: `0x70`(angle), `0x06`(V), `0x1a`(temp) are physically exact. The object
16-bit fields (`0x4b`) are raw — exact units (m, m/s) + names need the radar's label/ODX, which
is unavailable (VCDS `.clb` is encrypted, ODIS-E not installed, no firmware). Confirm them
behaviorally: log groups 001/013/014/048/049 while driving toward a lead vehicle — the 0xffff
slots populate and the values that track range/closing-speed identify the object fields.
Tools: `op_acc.py` (id/DTC/all blocks), `op_acc_blocks.py` (decoded live blocks).

## ODIS-E data dig (2026-10-15)
ODIS-E at `C:\Program Files\OE`; diagnostic data at `C:\ProgramData\OE\MCD-Projects-E\VWMCD\<project>`.
B8 Q5 project = **AU48X**. The radar's ODX base variant is present:
`0.0.0@BV_AdaptCruisContrKWP2000CAN20.bv.{db,key}` — confirms the radar is **KWP2000 over CAN TP2.0**
(matches the live connection). BUT the data is a compiled **"Peter's B Tree" (PBL) key/value cache**
(`.key` = B-tree index, `.db` = blobs); the `.xml` files are only file indexes (rt_index.xml etc.)
and the original ODX source (PDX/odx-f) is NOT retained on disk. `AStringData.data.gz` is a readable
but project-wide 68 MB string table of abbreviated English object names (the radar's measuring-value
names are not plainly isolable without resolving the BV's B-tree references). So measuring-block
LABELS + exact scaling are locked in the PBL cache (and VCDS `.clb` is encrypted). Values+units are
already obtained from the self-describing KWP formulas; only the human labels remain.

### Options to get the labels (ranked)
1. **ODIS-E GUI live read** (fastest): connect ODIS-E to addr 13 (needs an SM2/VAS VCI, which has a
   Windows J2534 driver), open the measured-values screen -> labeled values. Pair those labels with
   the group/field map here.
2. **Behavioral correlation** (no labels needed): run `op_acc_blocks.py` in a loop while driving toward
   a lead vehicle; the 0xffff object slots (grp 001/013/014/048/049) populate, and the fields that track
   range and closing-speed identify the object channels and confirm units.
3. **Parse the ODIS PBL B-tree cache** (high effort): PBL (Peter Graf) format is documented; the MCD
   object serialization on top is proprietary. Would yield all labels+scaling for every module.

---

## Session findings (2026-10) — see `docs/`

- **`docs/diagnostic_access_model.md`** — complete bus-observable access surface (sessions
  0x89/0x86/0x85 only; SecurityAccess level 0x03 only; `22` = identification DIDs only; live
  measuring-block capture) and the proof that **no diagnostic state yields live radar objects**
  (holding any session suppresses detection; stock ACC won't engage with a session open).
- **`docs/dash_lead_signals.md`** — the stock lead-distance display is **ACC_02 (0x30c)**:
  `Relevantes_Objekt` + `Abstandsindex` (`dist[m] ≈ 81.7 − 0.0885·idx`, r=−0.88), emitted
  **only while stock ACC is engaged**; openpilot's ACC_02 spoof vs stock diff; and the unknown
  bus-2 messages (`0x311` = speed not objects, `0x5a0` = RLS_01, `0x63a/c/d`, etc.) with a
  no-firmware method to identify their transmitters.

Reproduction scripts in `scripts/` (on-car `op_acc_*` probes via the Linux Openport; offline
rlog analysis). Route logs are gitignored (`*.zst`).
