# Handoff — waking the ESP8 (8R0907379BG) from degraded mode

**Goal:** get this bench ABS/ESP module out of its degraded/pre-operational state so it broadcasts
its normal CAN messages (ESP_01=0x100, ESP_02=0x101, ESP_08=0x11e) instead of only the 0x060
heartbeat, and answers UDS.

**All detailed module knowledge is in `analysis/symbols_merged.csv` (function/variable labels).**
This file is the only prose. Read the labels for: `cannm_state_machine`, `can_tx_scheduler`,
`comm_enable_flag`, `tx_gate2`, `comm_netmode_write`, `comm_mode_map`, `comm_nm_main`,
`nm_msg_process`, `com_sig_047b_buf`, `com_sig_046f_buf`, `transport_rx_process`,
`transport_tx_segment`, `crc8_j1850_e2e_engine`, `e2e_crc8_dataid`, `com_rx_commit_all`,
`com_signal_commit_record`, `heartbeat_060_composer`, `can_rx_isr`, `mailbox_rxindication_table`.
**Keep documenting in CSV labels only — do not add markdown docs (this handoff excepted).**

## State of understanding (verified this session)

- The module is a **fully-booted application** held in AUTOSAR "no communication until the network is
  present" — **not** a fault, coding, or boot stall. Emu-verified via `cannm_state_machine` (0x6eba8).
- **Master gate = signal 0x047b** (`com_sig_047b_buf` 0x408f0c). CanNm returns immediately unless
  `byte0==1`, so on the bench (0x047b==0) CanNm is **dormant** and never starts the network. The 0x060
  heartbeat is a separate ungated app message (`heartbeat_060_composer` 0x90db2), not CanNm.
- Enable chain (all in CSV): `sig 0x047b==1` → CanNm starts → +NM state(0x409478)==6 & mode
  (0x4090d8)&0xf0==0x80 (from the 0x40c container) → Network Mode → ComM full-comm → `comm_netmode`
  → `comm_enable_flag`; and `tx_gate2` = bit21 of signal 0x046f (`com_sig_046f_buf` 0x408f10) = the
  4-byte sub-PDU 0x600 byte1 bit5, delivered in the 0x40c container.
- **COM RX is unconditional** (`com_rx_commit_all` runs every cycle, no ComM gate) and the runtime
  tables are populated (COM TX / 0x060 works), so partner messages ARE processed in no-comm. The
  earlier bench inertness was wrong content (id/bit/E2E), **not** a dead pipeline.
- **E2E CRC fully reversed** and in `bench/e2e_crc.py`: `crc8_j1850` (app msgs incl 0x060, VERIFIED)
  and `e2e_crc8_dataid(buf,data_id,poly)` (byte0-CRC with data-id fold; 0x600 uses data-id 0x12).
- **Irreducible unknowns (boot-installed, SBOOT not dumpable):** the CanIf multi-frame reassembly
  dispatch + E2E-completion setter (`mailbox_rxindication_table` 0xb6a50 holds boot-patched RAM
  pointers), and the object-table-routed PDU→signal *bit positions* for the front-sensor signals.

## Constraints
- No SBOOT/boot-ROM access (die-level photo confirms no non-destructive bond-out). Do not pursue
  SBOOT dumping.
- Bench (Scanmatik SM2 Pro / J2534, CAN 500k) intermittently available; treat as feedback-silent
  until proven otherwise. Tools: `bench/*.py` (32-bit Python needed for smj2534.dll).
- Emulation: `emu/harness.py` (Unicorn, ARM BE32). Firmware is BE32; seg2 VMA=file+3.

## Next investigation lines (priority order)

### 1. Static — decode signal 0x047b's exact source message + bit (highest value)
Candidates: ACC_01 0x109 / ACC_10 0x117 / HCA_01 0x126. The signal→buffer is static
(`com_signal_table_full` 0xb038c), but the PDU→signal *bit* is object-table-routed. Try to recover
it from the flash COM config `.rodata` (0xb0000–0xb7800) and the group table `com_sig_group_table`
(0xb6a44) — find the record whose dest is 0x408f0c and trace back its RxIndication staging source.
Also decode signal `0x04b6` (0x408f18, second CanNm input). Deliverable: exact CAN-id + byte/bit +
E2E data-id for 0x047b. Label everything in the CSV.

### 2. Emulation — confirm CanNm-start produces observable NM TX (the feedback lever)
Seed `com_sig_047b_buf`(0x408f0c) byte0=1 and run the periodic task path that includes
`cannm_state_machine` + the NM TX runnable; confirm the module would begin transmitting NM frames.
If yes, step 1 alone gives a **bench feedback signal** (new tx id) — turning the wake search into a
closed loop. Identify the NM-TX message id/format so the next bench session knows what to watch for.

### 3. Emulation — map the ComM/BusSM link CanNm→netmode
The jump from CanNm Network Mode to `comm_netmode`(0x409230)=full is RAM-dispatched
(`comm_netmode_write` has no static caller). Find the ComM arbitration runnable and confirm which
CanNm state drives netmode to {0x30/0x40/0x80}. Establishes the complete minimal RAM state for
`comm_enable_flag`=1 + `tx_gate2`!=0.

### 4. Emulation — end-to-end COM-deposit of signal 0x046f
`com_rx_commit_all`(0x76468)/`com_signal_commit_record`(0x50090) are unconditional and use
`com_sig_group_table_ptr`. Seed the group table from flash 0xb6a44 and a staged 0x600 sub-PDU, run
the commit, and verify bit21→0x408f10→`tx_gate2`. Confirms the exact container bytes without SBOOT.

### 5. Bench (when available) — informed, now-with-feedback tests
- Send ACC_01/ACC_10/HCA_01 (0x109/0x117/0x126) sweeping candidate byte/bit with valid E2E
  (`bench/e2e_crc.py`), watching for the ECU to **start NM transmission** (feedback from line 2).
- Once 0x047b==1 is achieved, send the 0x40c container (`bench/wake_container.py`, updated with the
  correct E2E) to drive Network Mode → full broadcast.
- Also worth trying: the VAG gateway startup set (Klemmen/terminal-status messages) in case an
  additional ComM user gates on ignition/terminal state.

### 6. Static — rule out a parallel non-network gate
Confirm there is no BswM/EcuM run-state or safety-companion (watchdog SPI) gate that ALSO holds the
module degraded. Search for the SPI watchdog handshake driver and any EcuM RUN-state check; label
findings. (Current evidence says the only gate is the network/CanNm path, but verify.)

## Working style reminders
- Document every finding as a CSV label (function or variable), not prose.
- Firmware-derived artifacts stay gitignored; only metadata (addresses/names/scripts) is committed.
- Emulation is BE32; watch the seg2 VMA=file+3 offset and Thumb-vs-ARM mode (function_entries.txt).
