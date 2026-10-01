# Handoff — reverse-engineer UDS access + firmware dump (ESP8 8R0907379BG)

**All module knowledge lives in `analysis/symbols_merged.csv` (function/variable labels) — the source
of truth. Document new findings as CSV labels, not markdown (this prompt excepted).**

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

## Conventions
- The module is the user's own spare — legitimate recovery/RE.
- Firmware images/decompiles stay gitignored; commit only metadata. Document findings as CSV labels.
- Keep the CAN bus awake during all bench work. Emulation harness `emu/harness.py` (ARM BE32, seg2
  VMA=file+3); E2E CRC engines reversed in `bench/e2e_crc.py`.
