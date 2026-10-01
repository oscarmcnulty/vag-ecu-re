# Handoff — reverse-engineer UDS access + firmware dump (ESP8 8R0907379BG)

**All module knowledge lives in `analysis/symbols_merged.csv` (function/variable labels) — the source
of truth. Document new findings as CSV labels, not markdown (this prompt excepted).**

## *** BREAKTHROUGH 2026-10-01: diagnostics are TP2.0 + KWP2000, NOT UDS ***
The reason every UDS/ISO-TP probe (0x6b4/0x713/…) was silent: **this B8 ABS does diagnostics over VAG
TP2.0 + KWP2000**, not UDS. Working, reproducible session entry (`bench/tp20_kwp.py`, ignition ON):
- Channel setup: send `03 C0 00 10 00 03 01` to **0x200** → ECU replies on **0x203**: `00 d0 00 03 a3 04 01`.
- **Channel direction (important):** we **TX→0x4a3**, we **RX←0x300**. (The module *receives* on 0x4a3 —
  it's in the firmware RX filter, handler 0xa43f5 — and *transmits* the channel on 0x300. This is the
  reverse of the generic jazdw labeling, so parse: we_RX = resp bytes2-3 = 0x300, we_TX = bytes4-5 = 0x4a3.)
- Params: send `A0 0F 8A FF 32 FF` the INSTANT the first 0xD0 arrives (channel drops in ~1s otherwise;
  resend A0 on each 0xD0 retransmit) → ECU `A1 0f 8a ff 4a ff`.
- KWP data PDU `[op<<4|seq, len_hi, len_lo, kwp…]`; op 0x1=last+ACK, 0xB=ACK, 0xA3=channel-test keepalive.
- **`10 89` (StartDiagnosticSession) → `50 89` POSITIVE — diagnostic session ENTERED.** Two-way KWP
  confirmed (1A/18 services return 7F, i.e. processed but unsupported-subfn).
- NEXT (flash dump, now the KWP2000 way): find the right session for programming, KWP SecurityAccess
  (0x27) seed/key, then ReadMemoryByAddress (0x23) / upload. The 0x6b4/0x6b8 "UDS diag server" labels
  were the wrong protocol; the real diag path is TP2.0 on 0x200/0x203 ↔ 0x4a3/0x300.

## Status / established facts
- **The module is OPERATIONAL.** On **FlexCAN module B** (`0xfff7ea00`) = the Antriebs/ESP-CAN,
  physical **SM2-Pro / T38a pins 26 = CAN-H, 14 = CAN-L, 500 kbps**, it broadcasts **ESP_01 0x100 /
  ESP_02 0x101 / ESP_05 0x106 / ESP_08 0x11e** + 0x103/0x08a/0x308/0x392/0x632/0x64a/0x6c3 with live
  counters and valid E2E (bench-verified 2026-09-30). Data bytes are `ff` (no sensors on a bench) =
  healthy idle.
- **Module A** (`0xfff7e800`, pins 37/24) is the private sensor bus: only `0x060` heartbeat is visible
  on a bare bench; no UDS server there. The old multi-session "degraded/CanNm-wake/0x40c container"
  work was looking at module A — it is **not** the module's state and not the path to anything here.
- **Static RE (other agent) found the UDS diag server at `0x6b4` (req) / `0x6b8` (resp), RxIndication
  handler `0x127ed`** (see `flexcan_module_b` label + `decode/rx_filter_table.py`).
- **Bench result (2026-09-30): UDS is SILENT.** With the bus awake and the module operational, there
  was NO response to TesterPresent / `10 03` / `22 F1 87` on **0x6b4/0x6b8**, and a scan of **all**
  req ids 0x600–0x7FF found **no UDS responder at all** (watching for any `7E`/`7F` reply). So the Dcm
  silence is a **PRECONDITION gate, not an addressing problem** — this is the #1 thing to crack.
- **Bus sleeps when idle** — hold it awake with ≥5 Hz traffic (periodic frame) or the module stops
  transmitting.

## Update 2026-10-01 — RX dispatch mapped; static + cold-emu both walled (why)
- **Two separate RX dispatch paths, confirmed from code:** (1) the **COM path** `can_rx_isr`
  (0x8f708) -> `rx_mailbox_resolver`(0x501d4) -> `*(0xb6a50 + idx*0x18)`; (2) the **diag path**
  = the rx-filter table `0xaea38` handler `0x127ed`. The COM ISR **drops** any mailbox that is not
  a COM signal-group (resolver returns 0xff -> `can_rx_isr` early-returns). The diag mailbox
  `0xfff7e600` (0x6b4/0x6b8) is not a COM group, so **the COM ISR is NOT the UDS path** — diag goes
  only through `0x127ed`.
- **`0x127ed` is a register-indexed jump table** (head at 0x127ec: repeating `ldr r2,[sp]; movs rX,r0;
  b <case>` stubs). It has no prologue; back-scan lands on neighbor 0x12590. Its branch target is
  selected from the live ISR index, so it is **not statically decompilable in isolation** and not
  callable in emulation without the exact ISR context.
- **Root wall (same one, now proven RX-side):** the dispatch tables are **boot-materialized**. The
  flash `com_sig_group_table` template @0xb6a44 has **0/62** records with a FlexCAN-mailbox pointer at
  +8; the live table is expanded into RAM **0x40a1a8** at boot (SBOOT-installed config source, see
  `com_config_source_thunk`). Cold emulation therefore resolves **nothing** — `emu/exp_diag_rx.py`
  shows known COM mailboxes (0x117/0x104/0x100) all return idx=0xff cold. So the Dcm precondition
  **cannot be reached from the cold ASW image** by static RE or cold emulation alone.
- **CSV corrected:** the old "Dcm is not comm-gated / a request gets a response" note was overstated
  (it only covered the seg2 response-builders) — softened on `diag_resp_buf` / `diag_rxindication`.
- **=> The unlock is the bench (or a fuller dump).** Two concrete next moves: (a) **bench-read the live
  RAM dispatch state** — the materialized object table at `0x40a1a8` and the live diag RxIndication
  pointer — to see the real diag handler + its precondition checks; (b) the corrected single-channel
  keep-awake UDS probe below. A full flash dump incl SBOOT would also recover the boot init that builds
  these tables.

## Goal
Find and satisfy the Dcm precondition so the UDS server answers; then enter a programming/extended
session and **dump the complete flash** via RequestUpload (0x35)/TransferData (0x36)/TransferExit
(0x37), or ReadMemoryByAddress (0x23). A full dump would also capture the SBOOT region absent from the
ASW image we hold.

## Investigation lines

### Static (firmware RE) — label everything in the CSV
1. **Why is Dcm silent? (highest priority)** Trace the RxIndication handler `0x127ed` for the 0x6b4
   diag PDU → the Dcm SID dispatch, and find the gate that drops/ignores requests. Candidates:
   Dcm `DcmComMControl` / ComM "diagnostic active" grant for module B; a required
   `CommunicationControl`; an EcuM/BswM run-state; or a needed network wake (gateway TesterPresent on
   a routing id). Establish the exact condition that makes the Dcm answer, and whether it is
   satisfiable without the gateway.
2. **Diagnostic addressing confirm.** Re-verify 0x6b4/0x6b8 vs any functional/routing id the Dcm also
   accepts; check for extended/mixed ISO-TP addressing (an address byte) that the bench test above did
   not use (it sent normal 11-bit SF). If the Dcm expects extended addressing or a different N_PDU,
   that alone would explain the silence.
3. **Session control (0x10)** handler: supported sub-functions + preconditions for programming (0x02).
4. **SecurityAccess (0x27)** seed→key: the seed generator and the key transform/constants, so a
   `key_from_seed(seed)` can be written for `core/uds/uds_client.py security_access()`. Needed for
   programming + upload.
5. **Memory services** 0x35/0x36/0x37 and 0x23: dataFormatId, addressAndLengthFormatId, allowed
   ranges, required security level, `maxNumberOfBlockLength`.
6. Reuse the already-labelled Dcm pieces: `diag_did_table` (0xb44e4; coding DIDs 0x0405–0x0408,
   identity DIDs), `did_0601_handler` (0xbc574), `diag_resp_buf` (0x401854).

### Bench (SM2 Pro, module B = pins 26 H / 14 L, 500k, KEEP BUS AWAKE)
- **LIVE RESULT 2026-10-01 (uds_discover.py, module confirmed operational):** with the bus held awake
  and the module broadcasting (sniff: 0x100/101/103/106/11e + 0x08a/308/392/632/64a/6c3, valid E2E),
  UDS is **silent on EVERY mode** — physical 0x6b4/0x6b8 AND 0x713/0x77D, functional 0x7DF, extended
  addressing, and the full 0x600–0x7ff req sweep. => the addressing-discrepancy theory is DISPROVEN;
  the Dcm is gated BEFORE addressing. Don't re-chase ids/pairs. The open question is the precondition
  STIMULUS (network-management / full-comm state, or an ignition/enable frame) the module needs before
  it services diagnostics — test by establishing that state, THEN probing on the same awake channel.
- **DEFINITIVE (2026-10-01, module provably awake + TX confirmed received):** after a power cycle the
  module was woken via NM stimulus (broadcasting all ESP ids, liveness-guard confirmed) and held awake,
  and TX was proven to REACH it — writes to 0x6b4 complete in ~1ms (the module ACKs them; 50ms = no
  ACK). With all that true, UDS is STILL silent on 0x6b4/0x6b8, 0x713/0x77D, functional 0x7DF,
  extended addressing, and the full 0x600–0x7ff sweep. => the module RECEIVES the diag request and
  emits NO response: the gate is in the CanTp/Dcm SOFTWARE layer (consistent with the static finding
  that the diag dispatch 0x127ed is boot-materialized / register-indexed). Not wiring, addressing,
  sleep, or NM state.
- **VW_Flash-style session entry tried, still silent (2026-10-01, bench/uds_session.py):** replicated
  the Simos18 flasher sequence (3E00 -> 10 03 -> 3E -> 31 01 0203 -> 10 02 -> 27 11) over a PROPER
  ISO-TP client (SF/FF/FC/CF, responsePending-aware) with the NM wake held throughout, on both
  0x6b4/0x6b8 and 0x713/0x77D. Module awake+operational the whole time; EVERY step silent (not even
  10 03 answers). So the gate is not ISO-TP mechanics or the session sequence. Working hypothesis
  (matches the user's note that module B is the gateway-connected diag bus): the ABS only activates
  its UDS server with the GATEWAY/vehicle context present — e.g. a gateway-provided diagnostics-enable
  / terminal-15(KL15)-over-CAN / routing-active indication that a standalone module+adapter never
  supplies. Next: inject candidate enable/status frames (KL15/gateway-status) then re-probe, or put a
  gateway in the loop.
- **Vehicle-context feed does NOT open the Dcm (bench/vehicle_context.py, 2026-10-01):** continuously
  transmitting the full module-B expected RX set (22 partner ids: 0x019/062/085/086/08b/09f/102/104/
  105/110/114/117/11d/203/394/4a3/641/6c0/6c7/6d0/6ff/7e0) with counter+CRC, plus NM wake, then
  probing UDS -> still silent, no new broadcasts. NOTE: frames carried ZERO data (counter/CRC only), so
  a specific ENABLE-BIT value in a partner frame would not have been set (needs the platform DBC to
  target). Remaining suspects: (1) hardware TERM-15 (KL15/ignition) input — BENCH_HANDOFF wires term15
  on pins 35/32 and says 'tool drives VCC (term15) to wake'; confirm it is actually energized in the
  current module-B setup (ESP app runs on term30, Dcm may need term15); (2) the real gateway's
  diagnostics-enable/routing-active frame; (3) a specific partner-frame signal value.
- **IGNITION / term-15 found (2026-10-01):** the Scanmatik bench pigtail has a 3-pos "ignition" switch
  (on/off/auto) driving the +12V/VCC+ = module term-15. Switch ON = solid term-15 -> the module runs
  AUTONOMOUSLY (broadcasts ~50Hz, ACKs at 1ms, does NOT sleep, no NM wake needed). So term-15 controls
  the run/sleep state. HOWEVER, with ignition solidly ON and the module fully operational, UDS is STILL
  silent on the full 0x600-0x7ff sweep + functional + extended -> ignition is NOT the Dcm gate either.
  (AUTO position = device-controlled term-15; the FEPS pins {8,9,11,12,13} are NOT it — pin 12 = BOOT
  lead; +12V is not on any safely-drivable FEPS pin, likely the L-line/auto logic. For now use ON.)
  !! Recovery note: do NOT SetProgrammingVoltage(VOLTAGE_OFF) blindly — if the pigtail is in AUTO it can
  drop term-15 and kill the module; set the switch to ON for stable bench work.
- **TP2.0 LEAD (2026-10-01):** module B RX filter includes **0x203 = 0x200 + 0x03** (0x03 = VAG ABS
  logical address), handler 0xa43f5 — the hallmark of **VAG TP2.0 + KWP2000** diagnostics, not UDS.
  This would explain the total UDS silence (wrong protocol). NEXT: attempt a TP2.0 channel-setup on
  0x203 (opcode 0xC0) and speak KWP2000 over the negotiated channel. (8R0 B8 is TP2.0-era.)
- **WAKE PROCEDURE (works, 2026-10-01):** the module boots DORMANT (silent). Driving the 0x40c wake
  container (0x600 sub-PDU byte1 bit5, node-ids 0x4a/5f/98/99/9a/d4) + direct NM frames at ~50Hz brings
  it operational within ~1-2s (bench/nm_uds_probe.py, and uds_discover.py --wake). Must be fed
  CONTINUOUSLY; it re-sleeps within seconds of the stimulus stopping.
- **SLEEP BEHAVIOR (critical, 2026-10-01):** the module sleeps within a few SECONDS of bus inactivity
  — when asleep it stops broadcasting AND stops ACKing, so every TX times out (50ms/write) and RX is
  empty. Crucially, replaying CAN traffic (incl. 20Hz frames + NM stimulus) did NOT re-wake it once
  asleep → a **power cycle** is likely required to bring it back, after which the bus must be kept
  >5Hz CONTINUOUSLY with no gaps. The uds_discover / nm_uds_probe tools now have a LIVENESS GUARD
  (via can_raw.module_alive): they abort/flag if the module is not broadcasting, so a "silent" result
  can never be a sleep artifact. The UDS-silent result above WAS captured with the module awake (a
  passive sniff immediately after showed healthy broadcasts), but re-confirm it in one clean
  liveness-guarded run after a power cycle.
- **NM stimulus does NOT open the Dcm (bench/nm_uds_probe.py, 2026-10-01):** driving the 0x40c wake
  container + direct NM frames (node-ids 0x4a/5f/98/99/9a/d4) at 50Hz while probing UDS produced no
  reply and no new broadcasts — network-management state is NOT the gate (consistent with the module
  already being operational). Next levers: a different physical diag bus (module A pins 37/24), 29-bit
  ISO-TP addressing, or confirming TX reaches the module while it is provably awake.
- **START HERE: `bench/uds_discover.py`** (added 2026-10-01) — raw-CAN, single never-closed channel,
  continuous keep-awake, sweeps addressing modes (physical 0x6b4/0x6b8 AND 0x713/0x77D, functional
  0x7DF, extended/mixed, and a full 0x600–0x7ff req sweep watching ALL rx). A single 7E/7F reply
  gives the live pair + whether the service is precondition-gated vs. absent. `--secs 20` for a full
  sweep; `--pair 0x6b4:0x6b8 --probe 1003` to focus.
  - **NB addressing discrepancy:** firmware RX filter = **0x6b4/0x6b8** (decode/rx_filter_map.txt),
    but `confirm_comms.py` + the old `read_ram.py` defaulted to **0x713/0x77D** (never confirmed for
    this module). The earlier "silent" result may partly be wrong-pair; uds_discover settles it.
- Then **`bench/read_ram.py`** (now defaults 0x6b4/0x6b8; pass the pair uds_discover confirmed) to
  dump the boot-materialized live RAM the cold image lacks: objtable 0x40a1a8, the RX-dispatch state
  (0x406cd0 mailbox→group map, CAN status 0x406dc8/dd0), transport struct 0x407990, and the NM/comm
  precondition regions → `emu/ramdump_*.bin` to seed `harness.py`. Needs UDS answering first (0x23 is
  often gated → a clean NRC is still the answer).
- Other tools: `core/uds/j2534_transport.py` (ISO-TP), `core/uds/uds_client.py`, `bench/confirm_comms.py`,
  `bench/can_raw.py` (sniff/wake). 32-bit Python embed needed for smj2534.dll (re-download python.org
  `python-3.11.9-embed-win32.zip` if the scratchpad was cleaned). Do the whole UDS exchange on ONE
  channel with continuous wake frames — closing/reopening lets the bus sleep (that silenced the first
  attempt).
- Once static line 1/2 gives the precondition or correct N_PDU: TesterPresent → `10 03` → `10 02` →
  `27` (RE'd key) → `35` RequestUpload + loop `36` → `37`; concatenate blocks to `firmware/`
  (gitignored). Fall back to `23` ReadMemoryByAddress sweeping the flash if upload is gated.

## Scripted bench power / term-15 control (Scanmatik 2 Pro, verified 2026-10-01)
- The switchable +12V is driven by the standard J2534 call `PassThruSetProgrammingVoltage(dev, pin,
  mV)` (FEPS generator, 5000-24000 mV; `0xFFFFFFFF`=VOLTAGE_OFF, `0xFFFFFFFE`=SHORT_TO_GROUND). Battery
  (term30) is hardwired always-on; this controls the switchable lead for power-cycling / term-15.
- Accepted pins on this device: **6, 8, 9, 11, 12, 13, 14** (pin 25/AUX = ERR_PIN_INVALID). **OBD pin
  6 = CAN-H, 14 = CAN-L — NEVER energize them.** Use a spare FEPS pin {8,9,11,12,13} wired to the
  target lead; identify which pigtail lead it is with `bench/power.py probe --pin N` + a DMM.
- Helper: `bench/power.py {on|off|cycle|probe} --pin N [--mv 12000]` (refuses 6/14). Importable as
  `from power import Power` for scripted power-cycling inside a test (e.g. power-cycle then wake+probe).

## Conventions
- The module is the user's own spare — legitimate recovery/RE.
- Firmware images/decompiles stay gitignored; commit only metadata. Document findings as CSV labels.
- Keep the CAN bus awake during all bench work. Emulation harness `emu/harness.py` (ARM BE32, seg2
  VMA=file+3); E2E CRC engines reversed in `bench/e2e_crc.py`.
