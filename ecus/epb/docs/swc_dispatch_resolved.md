# EPB SWC / runnable dispatch — the "function mapping" wall, resolved

EPB 8K0907801N (Freescale/NXP HCS12X, S12X, big-endian, 16 KB PPAGE banking; imported in
Ghidra at global `0x780000` = DB_4). Companion: `RE_findings.md` §25, `can_rx_matrix.csv`,
`analysis/swc_dispatch_table.csv`.

> **Per-function detail lives in the symbols, not here.** Every function/label named below is
> carried with a byte-verified plate comment in `analysis/symbols.csv` (applied into the Ghidra
> project by `reproduce.sh`), so it surfaces in the decompile. This doc keeps only what a
> per-function comment cannot: the end-to-end flow and the reproduction method.

## Headline — the EPB has NO runtime dispatch wall

Unlike the ESP8 ABS (whose COM object table materialises its `DEST_PTR`s at boot and reads as
zero in flash), the EPB's SWC/runnable "function mapping" is a **static, fully in-image,
table-driven cooperative scheduler**. Every edge is either a static `CALL addr16,page` (opcode
`0x4a`) far-call or a scheduler-table lookup against a flash table. There is nothing
boot-materialised to read on a bench; the mapping is fully recoverable from the image we have.
This supersedes the earlier "arbitration SWC is runtime-only" conclusion (`RE_findings.md`
§13/§16/§19/§22).

The scheduler is `rte_sched_run_runnable` (`7e236a`); the 172-entry runnable table is
`0x7f5000–0x7f8000` (enumerated in `analysis/swc_dispatch_table.csv`). See those symbols for the
descriptor-table / CB-array mechanics.

## Actuation chain (byte-verified end to end)

The one artifact no single symbol comment captures — the full CAN-RX → actuator flow:

```
CAN RX  ──► esp05_epb_decode @7e4f7f  ─ writes signal image 0x283d/3e/3f
        ──► [snapshot task]  ─ copies signal image → RTE snapshot
                                0x1288 (ESP_Anforderung_EPB), 0x1289 (esp_flags/Autohold),
                                0x128a (valid), 0x1251.. (ACC), 0x1286 (pressure)
        ──► RTE getters (read ONLY by these; PPAGE-indirect, unref'd in Ghidra):
                rte_get_esp_anforderung_epb 788efe   rte_get_esp_autohold      788f21
                (ACC_Betaetigung 788ead)             (ACC field 788eb9)
                rte_get_esp_pressure       788d75    rte_get_esp_epb_consistency 788b8f
                epb_map_acc_req_to_cmd     788b1a
        ──► [decision sub-runnable, scheduler-dispatched via rte_sched_run_runnable + 0x7f5000 table]
ARBITRATION (page-fb control cluster, two channels + combined):
        epb_arb_apply_ch0 7ed041   epb_arb_apply_ch1 7ed292   epb_arb_apply_combined 7ed657
        epb_arb_apply_alt 7ed7b8   7edec3  7ee001  7ee054  7ee085  7ee2e2
          · gated by coding_ext_clamp_enable (0xfe074.0) AND coding_ext_clamp_enable2 (0xfe07c.0)
            — the master external-clamp enable, shared by BOTH the ESP and ACC routes
            (epb_ext_clamp_available 78c87f)
          · issue apply/release: epb_cmd_set_applybits 7ecc02 → epb_apply_cmd_reg DAT_000240
            (bit4 = ch0 apply, bit5 = ch1 apply)
          · speed gate: Rte_Read rte_read_vehicle_speed 79058c  compared < 0x4b1 (1201)
          · clamp-force ramp: ctx->0x31 bitfield 0x7c, +4 per cycle  (⇒ empirical Spann 2→17)
COMMAND REGISTER  epb_apply_cmd_reg DAT_000240  (arbitration OUTPUT)
          · consumed by monitors/reporters only: epb01_tx_status_pack 7eec4c,
            epb_status_measure_enc 799eaa, epb_force_current_filter 7ec0ab
APPLY RUNNABLE   epb_apply_runnable 7e88c1
          · read enable-getter 78cd37; if set read apply-value getter 78cd33
             → epb_apply_cmd_write 7e81f6(B)   [B=2 apply/close, B=1 release/open]
```

Both external clamp/hold request channels — **ESP_05 `ESP_Anforderung_EPB`** and **ACC_05
`ACC_Betaetigung_EPB`** — funnel to the same internal cmd 6 and share the arbiter, so ACC is
**not** a workaround for a cleared coding bit: `coding_ext_clamp_enable` (0xfe074.0) gates both.
That coding datum is EEPROM-sourced (dealer long-coding) with no static writer in the flash
image → its live value needs a UDS 0x22 coding read on-car, not a bench dump.

## Method notes (reproducible)

- Resolve a far-call: bytes `4a hi lo pg` ⇒ `CALL 0x<hi><lo>,0x<pg>` ⇒
  `global = 0x780000 + (pg-0xe0)*0x4000 + (addr16-0x8000)`. The decompiler's
  `(*(code*)((uint3)PPAGE<<0xe | 0x400XXX))()` equals that global once PPAGE is the real page
  (`0x400XXX` carries only `addr16 & 0x3fff | 0x400000`; the page is the `0x4a` immediate, so the
  literal alone is page-ambiguous — read the `0x4a` byte).
- The getters (`788efe` etc.) have **zero** static xrefs — invoked only through
  PPAGE-register-indirect calls the decompiler leaves as `(*(code*)…)()`, which create no Ghidra
  reference (the "no caller" illusion). The snapshot-RAM byte scan
  (`0x1288/89/8a/1251/1286`) is what pins each getter to its signal.
- Scripts: `scratchpad/gs/EpbWall13..25.java` (snapshot-RAM byte scan, far-call/table-entry
  scans, dispatch-table enumeration, targeted decompiles). The dispatch table itself is
  `analysis/swc_dispatch_table.csv`.
