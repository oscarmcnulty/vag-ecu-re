# Task: trace the ACC-hold signal end-to-end, radar → engine ECU → ESP

You are continuing a reverse-engineering effort on an Audi B8 Q5 **Simos 8.5** engine ECU
(`8R0907551F`), the goal being openpilot longitudinal control **to a standstill hold**. The
question for this task: **follow the standstill/brake command signal all the way from the ACC
radar's message, through the engine ECU, to what leaves the ECU toward the ESP (brake) module —
and identify exactly what an external controller (openpilot) must put on the bus to make the ECU
relay a standstill-hold request.**

Work from the repo root. Primary references:
`ecus/simos85/maps/RESULTS.md` (read UPDATES 57–63), `ecus/simos85/maps/acc_flow.md`,
and `ecus/simos85/analysis/symbols_merged.csv`.

## What is already VERIFIED (do not re-derive; build on it)

The middle of the chain is pinned from firmware reads. Every hop below is confirmed:

```
DCC_1 (received CAN, ACC command frame)
  byte7·bit1 = ACC_Anhalten (stop/hold request)
    │  801383e8  (DCC_1 receive+decode handler; E2E XOR-checksum + rolling-counter gated)
    │            :94  DAT_d000a7ae = (param_1[7]>>1)&1     ← also decodes ACC_Dynamik (byte7[3:2]=d000b06a),
    │                                                         setpoint d0007bac=(byte4&7)<<8|byte3, etc.
    ▼
  d000a7ae  (= ACC_Anhalten in RAM)
    │  8013ef46 = acc_brake_setpoint_statemachine (CRUC_MG005)  [decompile now exists in decompiles_r]
    │            @8013ff7e–ff98 / decompile lines ~936–979:
    │              a58d = a7ae   WHEN (d9 != 0) AND ([a10+0x18] byte != 0)   [ACC active + coded gate]
    │              a58d = 0      otherwise
    │            (same fn also produces the decel path: a58c = decel-enable, d0007cae→cb8 = decel value)
    ▼
  d000a58d  (= TSK_Anhalten source)
    │  80137a00  (TSK_02 packer)
    │            :49  cVar7 = UNK_d000a58d   (gated by TSK-valid: ad7a/a852)
    │            :94  byte2 = ... | cVar7<<4
    ▼
  TSK_02 (CAN id 0x10C, "DT_MNG_2")  byte2·bit4 = TSK_Anhalten  →  gateway  →  ESP
```

Key facts already established:
- `801a6134` is `reset_flags_and_values` (init/timeout reset of the whole `d000b060` DCC block),
  NOT an operative writer. An earlier pass mistook it for the sole writer of `a7ae` and wrongly
  concluded TSK_Anhalten was hardcoded 0 — retracted in RESULTS UPDATE 63.
- TSK_Anhalten reads 0 on a STOCK car only because the single-radar B8 ACC never asserts
  ACC_Anhalten (30 km/h floor — see memory `b8-acc-radar-hardware`). The firmware path is intact.
- Other TSK_02 fields: byte8 = TSK_Verzoeg_Anf (decel request, `Ramd0007cb8`, clamp [0x6db1,0x89b6]),
  byte7·7 = TSK_Freig_Verzoeg_Anf (decel enable, `a58c`), byte7·6 = TSK_Zwangszusch_ESP (`a58f`),
  byte7·5 = TSK_Codierung_ACC (`a79f`). Constant 0: TSK_Radbremsmom (byte6/7), TSK_Standby_Anf_ESP.
- TSK_04 = 0x10E (builder `801e3f26`); TSK_01 = 0x10A. Cruise state = `b28e` / STATE_CRU_CTL_CAN.
- **Caveat (RESULTS line ~2515):** the engine reads GATEWAY-REPACKED frames (handler mentions
  handles 0x8a0/0x600), so the exact wire-bit ↔ RAM-var mapping for 1–2-bit control signals is
  FR-authoritative, not fully provable from the image. This is the weakest link — see Q1.

## OPEN QUESTIONS — what to actually investigate (ranked)

**Q1 (upstream — highest value). Nail the radar→engine ingress.** Which physical CAN ID(s) does the
engine receive that carry DCC_1 / the ACC command, and how does the gateway repack map wire bytes to
the buffer `801383e8` decodes? Find `801383e8`'s caller(s) and the receive/COM-stack path (Com IPDU
dispatch, e.g. `com_process_ipdu`, `801d*`/`801f*` runtime layer). Determine: the received CAN id,
the message-buffer source, and whether `param_1` is a raw wire frame or a gateway-repacked one. Cross-
check the signal names/positions against the Funktionsrahmen (see FR access below) and against
opendbc MLB dbcs for the B8/Q5. Goal: a concrete "to assert ACC_Anhalten, set bit X of byte Y of CAN
id 0xNNN" statement, with confidence level and the gateway caveat resolved as far as the image allows.

**Q2 (the gate — what openpilot must satisfy).** In `8013ef46`, pin the exact predicate behind
`d9` and `[a10+0x18]` (the "ACC active + coded" gate on `a58d = a7ae`). Tie them back to concrete
conditions: cruise state `b28e ∈ {1,5}`, ACC coding `a757` (LV_DCC_ENA), and anything else. Produce a
precise list of runtime conditions under which the ECU forwards ACC_Anhalten vs. forces 0. Same for
the decel-enable `a58c` gate (already partially described in RESULTS UPDATE 61) so the whole brake
path's arming conditions are documented together.

**Q3 (downstream — engine→ESP).** TSK_02 (0x10C) is built by `80137a00`; trace how it is transmitted
and whether/how it is gatewayed onto the ESP/chassis bus. Identify which ESP-facing message carries
TSK_Anhalten and the decel request. (The ESP's *reaction* is a different module/ECU and may be out of
image scope — if so, say so and pin the routing/CAN-id boundary precisely, and note what the opendbc
MLB dbc calls the corresponding ESP message.)

**Q4 (completeness).** Are there OTHER standstill/hold-relevant outputs beside TSK_Anhalten? Check
TSK_Zwangszusch_ESP (`a58f`, "forced ESP intervention"), TSK_Standby_Anf_ESP, and any EPB/hold vector.
Confirm whether any are live and how they gate. Reconcile with `vw-mlb-checksums` memory (ACC_05/EPB
inject topology).

## ENVIRONMENT & TOOLING

Ghidra project is at `ecus/simos85/ghidra_proj` (Simos85), TriCore LE, base `0x80000000`
(file offset = addr − 0x80000000). Env:

```bash
source .env.sh                 # sets GHIDRA_HOME (Ghidra 12.1.2), JAVA_HOME (JDK 21)
HL="$GHIDRA_HOME/support/analyzeHeadless"
```

- **Decompiles** live in `ecus/simos85/analysis/decompiles_r/<addr>.c` (now COMPLETE — 8013ef46.c is
  present). A per-function outcome table is `analysis/decompiles_r.manifest.csv`
  (addr,name,bytes,status,elapsed_ms,reason; status ok|degraded|fail|absent). `degraded` fns have
  gutted C — read their disasm in `analysis/disasm_r/<addr>.asm` instead.
- **Disassemble a function** (symbol-annotated), e.g. to read `8013ef46` or a caller:
  ```bash
  cd ecus/simos85
  printf '801383e8\n8013ef46\n' > /tmp/fns.txt
  "$HL" ghidra_proj Simos85 -process 8R0907551F_Original.bin -noanalysis \
    -scriptPath core/ghidra \
    -postScript DumpDisasmFns.java /tmp/fns.txt /tmp/disasm_out
  ```
  RAM addresses appear as `a0`-relative: `a0 = 0xd0008000`, so `lea aX,[a0]0xNNNN` targets
  `0xd0008000+0xNNNN` (e.g. `0x258d` = `d000a58d`). `a1 = 0x80048000` (cal), `a8 = 0x80088800`.
  Addresses in Ghidra `toString()` have NO `0x` prefix.
- **Find all writers/readers of a RAM symbol**: `core/ghidra/FindRefsTo.java`. Also just
  `grep -rn "d000a7ae" ecus/simos85/analysis/decompiles_r/` — the decompile set is complete now, so a
  grep is reliable for finding every C-level reader/writer (this is how UPDATE 63 found the missed
  writer that a stale set had hidden).
- Other useful scripts in `core/ghidra/`: `ExportCallgraph.java`, `DecompileAddrs.java`,
  `TraceMapCalls.java`. Cal reads: `analysis/cal_reads.csv`.
- **Funktionsrahmen (FR)** function-spec text: `ecus/simos85/analysis/fr/fr_full.txt` /
  `fr_pages.jsonl` (regenerable from the PDF in `core/pdf`/`docs`); grep it for signal names like
  `ACC_Anhalten`, `LV_CAN_VEH_STOP_REQ_DCC`, `TSK_Anhalten`, `DCC_1`, `CRUC_MG005`, `Zwangszusch`.

## METHOD / RIGOR (important — the last pass got a verdict wrong)

- **Verify every hop from the firmware** (disasm or the now-complete decompile). Do not trust a prior
  RESULTS conclusion without re-checking its writer/reader sets — UPDATE 61 was wrong precisely
  because it relied on a stale decompile set that hid a CAN-decode writer.
- Establish writer/reader sets with FindRefsTo AND a grep over the complete `decompiles_r/`. If a
  function of interest is `degraded`/`fail` in the manifest, read its `disasm_r` instead of trusting
  empty C.
- State confidence per claim and carry the gateway-repack caveat explicitly where wire-bit mapping
  isn't provable from the image (mark those FR-authoritative).
- Prefer disassembly ground-truth over decompiler sugar for the 1-bit control-signal packing/unpacking.

## DELIVERABLES

1. A new `RESULTS.md` UPDATE (next number after 63) documenting the full radar→engine→ESP chain: the
   ingress CAN id + gateway mapping (Q1), the exact forward/zero gate conditions (Q2), the egress
   routing to ESP (Q3), and any additional hold vectors (Q4) — each hop with its function/address and
   confidence.
2. Update `acc_flow.md` (the TSK tables + the standstill/hold narrative) to match.
3. Update/добавить memory files if the openpilot-actionable conclusion changes (what bus message +
   bits + coding/state openpilot must drive to command standstill hold).
4. A crisp bottom line: the precise CAN message(s)/bits and ECU state openpilot must produce for the
   engine to relay a standstill-hold (and decel) request to ESP — or the specific unknown that blocks
   stating it, with the experiment (bus capture / bench) that would resolve it.

Do not commit unless asked. Keep derived artifacts (decompiles, disasm, manifests) out of git — they
are gitignored and regenerated by `ecus/simos85/reproduce.sh`.
