# EPB SWC / runnable dispatch — the "function mapping" wall, resolved

EPB 8K0907801N (Freescale/NXP HCS12X, S12X, big-endian, 16 KB PPAGE banking; imported in
Ghidra at global `0x780000` = DB_4). Companion: `RE_findings.md`, `can_rx_matrix.csv`,
`analysis/swc_dispatch_table.csv`.

## Headline — the EPB has NO runtime dispatch wall

Unlike the ESP8 ABS (whose COM object table materialises its `DEST_PTR`s at boot and reads as
zero in flash — see `ecus/esp8/.../verf_guard_and_dtc.md`), the EPB's SWC/runnable "function
mapping" is a **static, fully in-image, table-driven cooperative scheduler**. Every edge is
either a static `CALL addr16,page` (opcode `0x4a`) far-call or a scheduler table lookup against
a flash table. There is nothing boot-materialised to read on a bench; the mapping is recoverable
from the image we have. This directly confirms the working hypothesis ("the mapping almost
certainly lives in the ASW part of the image").

The earlier appearance of a "wall" was an artifact of Ghidra failing to cross-reference `0x4a`
far-calls across PPAGE banks, plus the decompiler rendering paged calls as
`(*(code *)((uint3)PPAGE << 0xe | 0x400XXX))()`. Decoding the raw bytes dissolves it:
`4a 8d 37 e3` = `CALL 0x8d37,0xe3` → global `0x78cd37` (`global = 0x780000 + (page-0xe0)*0x4000
+ (addr16-0x8000)`).

## The scheduler — `FUN_7e236a(runnable_id)` (PROVEN)

The cooperative tick. For `runnable_id < 0xdc` (220):

- Looks up a per-runnable **descriptor** in a flash table at `BYTE_ARRAY_7f4800 + 0x2390`
  (`≈ 0x7f6b90`), **GPAGE-global addressed** (`GPAGE=(descr>>8); *CONCAT12(GPAGE,addr)`).
- Tracks per-runnable **state** in a RAM control-block array at **`0x1fbf`/`0x1fc0`** (stride 4):
  ready/enable bits (`0x20`, `0x08`, `0x02`, `0x40`) and a period counter compared against the
  descriptor's reload (`if (*period <= counter)` → elapsed → invoke).
- When a runnable is due, invokes it and latches its boolean result into the CB array
  (`0x1fc0 + id*4`, bit 0), which the caller reads back.

So "schedule/run event `id`, then read whether it succeeded" is `FUN_7e236a(id)` + test of
`*(0x1fc0 + id*4) & 1`. The control runnables call it with `id = ctx->field_0x10 + <offset>`.

## The static runnable table — `0x7f5000–0x7f8000` (172 entries)

Enumerated in `analysis/swc_dispatch_table.csv`: 172 `{addr16,page}` records, each resolved to a
concrete function, spanning pages e2/e3/e4/e6/f8/f9/fa/fb/fc. This is the SWC→runnable map. Spot
checks: apply runnable `FUN_7e88c1` is entry `@7f561b {88c1,fa}`; the `0x240` monitor
`FUN_7ec0ab` is `@7f6180 {80ab,fb}`.

## Actuation chain (byte-verified end to end)

```
CAN RX  ──► esp05_epb_decode @7e4f7f  ─ writes signal image 0x283d/3e/3f
                                        (esp_epb_req / esp_flags / valid)
        ──► [snapshot task]  ─ copies signal image → RTE snapshot
                                0x1288 (ESP_Anforderung_EPB), 0x1289 (esp_flags/Autohold),
                                0x128a (valid), 0x1251.. (ACC), 0x1286 (pressure)
        ──► Rte_Read getters (read ONLY by these; invoked via PPAGE-indirect, unref'd in Ghidra):
                788efe = ESP_Anforderung_EPB     788f21 = Autohold_aktiv
                788ead = ACC_Betaetigung_EPB     788eb9 = ACC EPB field
                788d75 = pressure (LDD)          788b8f = ESP↔EPB consistency qualifier
        ──► [decision sub-runnable, scheduler-dispatched via FUN_7e236a + the 0x7f5000 table]
ARBITRATION (page-fb control cluster, two channels + combined):
        7ed041 (ch0)  7ed292 (ch1)  7ed657 (combined)  7ed7b8  7edec3  7ee001  7ee054
        7ee085  7ee2e2
          ·  schedule decision sub-runnable: FUN_7e236a(ctx->0x10 + 0xc); read result @0x1fc0+id*4
          ·  issue apply/release: FUN_7ecc02(ctx, cmd)   [cmd 100='d' = apply, 0 = release]
                 → sets/clears command register DAT_000240:  bit4 = ch0 apply, bit5 = ch1 apply
          ·  speed gate: Rte_Read FUN_79058c  compared < 0x4b1 (1201)
          ·  clamp-force ramp: ctx->0x31 bitfield 0x7c, +4 per cycle  (⇒ empirical Spann 2→17)
COMMAND REGISTER  DAT_000240  (arbitration OUTPUT)
          ·  consumed by monitors/reporters (NOT the driver):
                FUN_7eec4c  = EPB_01 TX packer (motor status onto CAN)
                FUN_799eaa  = status/measurement encoder (buffer 0xef3/0xef4)
                FUN_7ec0ab  = periodic force/current measurement filter (20-tick ring buffer)
APPLY RUNNABLES   78972d / 7e88c1 / 7eec4c
          ·  7e88c1: read enable-flag getter 78cd37; if set read apply-value getter 78cd33
             → actuator driver FUN_7e81f6(B = command)   [B=2 apply/close, B=1 release/open]
ACTUATOR  FUN_7e81f6  (CALL 0x81f6,0xfa)  → motor H-bridge channel enable
```

## What this confirms for the integration (no new control, just provenance)

- The two external clamp/hold request channels remain exactly as in `RE_findings.md` §11/§24:
  **ESP_05 `ESP_Anforderung_EPB`** and **ACC_05 `ACC_Betaetigung_EPB`** (ACC path qualified by
  `ACC_Status_ACC`, not by ESP consistency). These land at snapshot `0x1288`/`0x1251` and are
  read by getters `788efe`/`788ead`.
- `Anforderung_EPB=2` = apply/close, `=1` = release/open — matching the actuator `B=2`/`B=1`
  convention at `FUN_7e81f6` and the `CLAMP_CMD→2` fix in memory `epb-engage-jerk-and-standstill`.
- The firmware's own stock clamp is a **speed-gated, force-ramped** sequence (gate `0x4b1`≈ the
  low-speed region; force field ramps +4/cycle), which is the firmware-side counterpart of the
  empirically measured stock handoff (Spann 2→17 over ~0.4 s). The clamp force resolution is the
  `0x7c` (5-bit) field — consistent with the 0–31 Spannkraft range on EPB_01.

## Method notes (reproducible)

- Resolve a far-call: bytes `4a hi lo pg` ⇒ `CALL 0x<hi><lo>,0x<pg>` ⇒ global per the formula
  above. The decompiler's `(uint3)PPAGE<<0xe | 0x400XXX` equals that global once PPAGE is the
  real page (`0x400XXX` carries only `addr16 & 0x3fff | 0x400000`; the page is the `0x4a`
  immediate, so the literal alone is page-ambiguous — read the `0x4a` byte).
- Getters `788efe` etc. have **zero** static xrefs (no `0x4a`, no same-page `0x16`, no
  `{addr16,page}` or 24-bit-global pointer-table entry). They are invoked only through
  PPAGE-register-indirect calls the decompiler leaves as unresolved `(*(code*)…)()`, which create
  no Ghidra reference — hence the "no caller" illusion. The snapshot-RAM byte scan
  (`0x1288/89/8a/1251/1286`) is what pins each getter to its signal.
- Scripts: `scratchpad/gs/EpbWall13..22.java` (snapshot-RAM byte scan, far-call/table-entry
  scans, dispatch-table enumeration, targeted decompiles). The dispatch table itself is
  `analysis/swc_dispatch_table.csv`.
