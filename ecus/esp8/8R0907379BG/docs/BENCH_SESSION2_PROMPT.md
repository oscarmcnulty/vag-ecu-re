# ESP8 bench — session 2 continuation prompt

> **SESSION 2 PROGRESS (2026-09-19):** step 1 (operational gate) is largely SOLVED and step 2's
> CRC is reversed — see **`docs/operational_gate_trace.md`**. The `0x40944c=1` writer is
> `FUN_0006a71c` (ComM/Nm main; `FUN_6a9d4` is its disable sibling); the gate reduces to the
> AUTOSAR Nm network-state (netmode `0x409230` via `FUN_0008f5a4`, PDU/status word `0x408f10`).
> The 0x060 heartbeat CRC = CRC-8/SAE-J1850 (`bench/nm_crc.py`, verified vs all 8 samples).
> Remaining: the exact NM CAN-id (object-table-routed) — needs the bench NM-wake sweep below.
> Note: bench hardware was NOT exercised this session (DLL present, but the 32-bit Python embed
> was gone from the reset scratchpad — re-download per the toolchain section to run the scripts).


Paste the block below as the first message in a new session (Windows PC, repo at
`C:\Users\om\vag-ecu-re`). It hands off the bench state, the wall we hit, and the freshly
pulled COM/UDS RE material to build on.

---

You are continuing on-bench reverse-engineering of a spare **Bosch ESP8 quattro ABS,
8R0907379BG** (B8 Q5), on a Windows PC, talked to over a **Scanmatik SM2 Pro** via J2534.
Read `ecus/esp8/8R0907379BG/docs/` (esp. `com_init_objtable.md`, `objtable_emulation.md`,
`second_code_segment.md`, `uds_read_primitive.md`, `bench_harness_pinout.md`,
`acc10_read_path.md`) and `CLAUDE.md` first. Latest remote is pulled (HEAD `168a283`).

## Toolchain that already works (do NOT re-derive)
- **SM2 on Windows works ONLY with Scanmatik software ≥ v1.0.0.124** (`smj2534.dll` dated
  2025-02-04). The older 1.0.0.87 build's detection fails with "no USB hardware support" —
  that was a version-mismatch rabbit hole, already solved.
- `smj2534.dll` is **32-bit**, so it needs a **32-bit Python**: an embeddable one is at
  `C:\Users\om\AppData\Local\Temp\claude\<session>\scratchpad\py311x86\python.exe`
  (python.org 3.11.9 embed-win32; re-download if the scratchpad is gone). 64-bit Python
  can't load the DLL.
- Reusable, DLL-agnostic **J2534 ISO-TP transport**: `core/uds/j2534_transport.py`
  (classes `J2534`, `J2534IsoTpTransport`). ESP8 probe: `ecus/esp8/8R0907379BG/bench/confirm_comms.py`.
  These two are **new/uncommitted** — commit them early.
- DLL path: `C:\Program Files (x86)\Scanmatik\smj2534.dll`. `PassThruOpen` → STATUS_NOERROR.
- Handy raw-CAN scripts were built in scratchpad (sniffer, id scanner, network replay) — re-create as needed.

## Bench wiring (T38a, per `bench_harness_pinout.md`)
term30 B+ = pins 1/7/25; term15 = pins 32/35; GND = 13/38; **CAN-H = 37, CAN-L = 24, 500 kbps**.
The harness has a **physical ignition switch (off/on/auto)** — set it to **ON** to power VCC+/term15.
The SM2's J2534 programming-voltage output **cannot** drive term15 (current-limited) — don't try.
Single CAN controller (mailboxes `0xfff7e400–e700`, ctrl `0xfff7e800/ea00`). CAN wiring is
confirmed correct (frames get ACKed).

## THE WALL (what to solve)
The ECU is powered and alive but **pre-operational**:
- It broadcasts **only CAN `0x060`** — a low-level counter+CRC heartbeat (`00 00 00 00 00 08 CTR
  CRC`, TX mailbox `0xfff7e5f0`), NOT its normal messages (ESP_01=0x100, ESP_02=0x101, ESP_08=0x11e).
- It **answers no diagnostics**: tried every 11-bit ID (physical+functional, session-control +
  tester-present + DID reads), the firmware-confirmed native diag mailbox **`0x6b4/0x6b8`**
  (= mailbox `0xfff7e600`), and TP2.0 channel setup. All silent. `0x713/0x77D` is
  **gateway-translated** (ABS never answers it directly; no gateway on the bench).
- Root cause (from Ghidra RE, firmware extracted locally): the COM TX scheduler `can_tx_scheduler`
  (0x5bfc) hard-gates on operational flags **`*0x40944c==1 && *0x409438!=0`**; they're clear.
  `FUN_6a9d4` is the comm-DISABLE path (sets `0x40944c=0`, logs DTC 0x169) and has **no direct
  caller** — it's a ComM/Nm **function-pointer callback** in the runtime object table, so the
  enable/disable trigger is not statically resolvable by xref.
- Empirically ruled out: bus-ACK-present-at-startup, power-cycle on a live/ACKed bus, full replay
  of the 33 expected partner RX IDs (incl NM-range `0x441`) at 20 Hz, all power pins connected
  (1/7/25 + 32/35 + pump assembly). None make it go operational.

**Hypothesis to pursue:** the ABS needs *full communication* (AUTOSAR ComM) — normally requested
by NM / the live vehicle network / the gateway — before its Dcm answers. On a bare bench that
never happens. Goal: find the exact minimal trigger for `0x40944c=1`/`0x409438!=0` (a specific NM
or partner message, an internal state, or a config gate) so it can be **simulated on the bench**;
or prove it's unreachable without a gateway.

## Fresh RE material to exploit (pulled in `168a283`)
The COM object-table build is now mapped (`docs/com_init_objtable.md`):
- Object table **`0x40a1a8`** (`*0x4069b4`); dispatcher **`FUN_0008df52`** switches on command byte
  **`0x4069a8`**; walker **`com_config_walker` 0x49f38**; allocator **`com_objtable_alloc` 0x8e3d0**;
  phase **`0x406aa4`** (→1 via `FUN_000931e8` when `0x4069e4==1`). Cold emulation stalls because the
  one-time config-source startup never runs (see `objtable_emulation.md`, `emu/exp_objtable_*`,
  `exp_cominit_drive.py`, `exp_region_table.py`, `capture_ram_bases.py`).
- UDS side: `diag_did_table` 0xb44e4 (F187=8R0907379BG, F189=0030, F197="ESP8 quattro"),
  `did_0601_handler` 0xbc574, `diag_resp_buf` 0x401854. New Ghidra scripts:
  `EspFindDispatch/EspFindRMBA/EspFindALFID/EspSeg2Probe/EspDecompAt/EspMkFnAt` in
  `ecus/esp8/ghidra_scripts/`.

## Reproduce the RE environment
- `.env.sh` (gitignored): `GHIDRA_HOME=/c/Users/om/ghidra_11.4.2_PUBLIC`,
  `JAVA_HOME="/c/Program Files/Eclipse Adoptium/jdk-21.0.8.9-hotspot"`. reproduce.sh runs fine on
  Ghidra 11.4.2 despite the 12.1.2 note.
- Firmware (gitignored): extract with
  `py ecus/dynsteer/extract_sgo.py "C:/Users/om/Downloads/8R0907379BG_0030.sgo" -o ecus/esp8/8R0907379BG/firmware/8R0907379BG_0030.bin`.
  SA2 seed/key script recovered: **`93 97 4C58AB 4A0787 FEDCBA98 6B05 8798765432 680B82 494C`**
  (contains 0x974C58AB / 0x98765432).
- `source .env.sh && ecus/esp8/8R0907379BG/reproduce.sh` → labeled project + decompiles in
  `analysis/decompiles_r/` (~4471 fns).

## Concrete next steps (pick up here)
1. **Trace the operational gate.** Find writers of `0x40944c=1` and `0x409438!=0` (they weren't in
   the 6/13 literal-ref functions except the disable path). Try the new `EspFindDispatch` +
   emulation harnesses to drive ComM/Nm init and watch which callback sets them. Resolve what
   `FUN_49940`'s early gate needs (`*0x408f10` bit26, `*0x40944c`, `*0x40418e==0`, `*0x407263`,
   `*0x407fee&3`) and its enable inputs (`*0x4072f6 || *0x4072f5 || *0x4059e0`).
2. **Identify/participate in NM.** Determine the chassis-CAN NM message(s) the ECU expects (RX
   mailbox `0x441` is NM-range); is `0x060` its own NM tx? If so, craft valid NM RX to push ComM to
   full communication. Needs the E2E-CRC (likely CRC-8/0x2F + per-message data-id) — reverse it
   from `0x060`'s counter/CRC samples (CTR 0→7 give CRC 50,4d,6a,77,24,39,1e,03).
3. If operational state is reached, the diag path is `0x6b4` (req) / `0x6b8` (resp) — retry UDS,
   then the SBOOT-leak / 0x23 investigation per `uds_read_primitive.md` using the new RMBA scripts.
4. Fallback the human already ruled out: no gateway J533 available, PCMflash doesn't list this part.

Confirm the ECU state first (`sniff` the bus: expect only `0x060`), then proceed. Commit
`j2534_transport.py` + `bench/confirm_comms.py` + a docs update before deep work.
