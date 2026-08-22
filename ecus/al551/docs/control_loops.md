# AL551 TCU — key control loops & tuning levers (8R0927158AM SW1003)

Addresses in `8R_full_flash.bin` (Q5). Decompile corpus: `analysis/decompiles_r/` (10408 fns,
99.9% of live bytes accounted). CAN architecture: `../../analysis/al551_can_arch.md`.

## Decompilation status
- 10408 functions, 99.0% clean decompile (0 bogus/fail after pruning), 99.9% of non-erased
  bytes accounted for, **0 code-candidate gaps** (no undefined bytes look like code).
- RX/COM layer is a function-pointer-driven RTE: frames land in databufs `0xfff91ae8+`, then
  per-signal accessor functions read them; main dispatch is indirect via `PTR_FUN_*` RAM
  pointers. Static traces reach the accessors; the full loop needs dispatch resolution.

## 1. Shift points  (primary lever)
- **Upshift RPM-ceiling map pack: `0x1d3000`–`0x1e1200`** (~55 KB). Each map is **0x18C bytes**
  (a per-gear throttle→shift curve); maps are grouped into **drive-program sets** with a
  `0x4a4`-byte gap between sets. The recurring internal rpm axis is `[1340 2015 3000 3770 4885
  6300 7500]` and the curve outputs top out at the **stock 6300 / 7500 rpm ceiling**.
- To raise the shift RPM (as 034/IE do, 6300→~7200), raise the `6300`/`7500` output cells.
  6300 appears ~900× across `0x1d3000`–`0x1e1200`; lower-ceiling variants use `6250/6200/6367`.
- Accessed by the shift engine via base+offset (maps are not individually pointer-referenced).

## 2. Max torque  (input-torque limit)
- **Torque-limit map family: `~0x1b0c50`–`0x1b1900`.** Gear/condition-indexed 8-point curves in
  **Nm**, e.g. `[750 750 700 650 600 600 600 600]` (high limit), `[650 600 500 400 300 250 250
  250]`, `[550 550 500 450 400 350 350 300]` (protection). These clamp the input torque the box
  accepts and drive the engine-torque-reduction request (Getriebe_01.GE_MMom_Soll path,
  packed by `can_tx_pack_Getriebe_01` @0x073774, frame `0xfff91c88`). Raising these lifts the
  torque the TCU will hold in gear / not cut.

## 3. CHARISMA (drive program)  → selects the map set
- CHARISMA = Audi drive-select program; arrives on `Charisma_01` (CAN 0x385, RX). The TCU
  echoes `GE_Charisma_FahrPr/Status/Umschaltung` in `Getriebe_04`.
- Mechanism: the drive program is an **index into the shift-map pack** (§1) — each program
  (Comfort/Auto/Dynamic/Efficiency/manual) points the shift engine at a different set (the
  `0x4a4`-separated blocks), so the same throttle→RPM lookup yields earlier/later shifts per
  mode. The torque-limit selection (§2) is likewise condition-indexed. So CHARISMA does not
  change the maps — it **chooses which set of shift/pressure maps is active**; tuning a mode
  means editing that mode's set.

## Reproduce / labels
`ecus/al551/reproduce.sh` (SuperH:BE:32:SH-2A). Confirmed names in
`analysis/symbols_merged.csv` (CAN layer + these map regions), applied via ApplySymbols.
Open items: resolve the RTE dispatch (PTR_FUN_* tables) to bind each RX signal to its
consumer, and pin the exact per-program set count / gear index of the shift & torque packs.

## Update — precise structure + dispatch resolution (2026-08-21)
- **Shift-curve record = 0x1C bytes** (7-pt input axis + 7-pt output), sharing the rpm axis
  `[1340 2015 3000 3770 4885 6300 7500]`. Curves are grouped into blocks (stride 0x18C ≈ 14
  curves) across `0x1d3000`–`0x1e1200`, and located via the **shift-map registry** `0x05c778`
  (114 pointers, stride 0x18C) inside the descriptor region `0x05bff0`–`0x05c9xx`.
- **RTE dispatch is statically resolvable** (not runtime/emulation): the `PTR_FUN_*` call
  targets are flash-resident pointers. `analysis/dispatch_resolved.csv` resolves **12,930
  pointer sites → 6,613 target functions** (PTR_FUN_00xxxxxx → u32[0xxxxxxx]). This makes the
  full CAN-RX→shift/torque call graph traceable statically — the remaining work is walking
  those edges to bind each RX signal and pin each map cell's gear/program coordinate.

## Calibration access tree + honest tracing boundary (2026-08-21)
- The whole calibration is a generated descriptor tree. **Master group table `0x5fcac`** (37
  groups) → each group is a pointer table (e.g. `0x5b7a0` = 1884 ptrs) → cal objects (scalars,
  axes, maps). The shift-map registry `0x05c778` and the shift/torque map data hang off this tree.
- RAM base pointers (e.g. `0xfff91a68`) are set at init from **flash config structs passed by
  the caller** (`rte_slot_manager_init` @0x71428: `_DAT_fff91a68 = param_1`). So the chain is
  statically resolvable caller-by-caller (no boot emulation needed) — but it is a deep,
  generated tree and several framework functions decompile with unrecovered register-arg
  conventions, so exhaustive per-cell labeling is a large graph-walk.

### What is directly tuning-actionable NOW (addresses in the 8R image)
| lever | where | how to tune |
|-------|-------|-------------|
| Upshift RPM ceiling | `0x1d3000`–`0x1e1200`, `6300`/`7500` cells (~900×) | raise to ~7200 to lift shift RPM |
| Shift curves | `0x1C`-byte records (7-pt in / 7-pt out), rpm axis `[1340..7500]` | reshape per-gear shift thresholds |
| Input-torque limit | `0x1b0c50`–`0x1b1900` (Nm curves) | raise to hold more torque in gear |
| Drive-program (CHARISMA) | descriptor-group / registry index | selects which shift/pressure set is active |

### Remaining (bounded graph-walk, enabled by dispatch_resolved.csv)
Bind each of the 40 RX signals to its consumer; pin the exact drive-program RAM variable that
indexes the registry; label each shift/torque cell's gear+program coordinate. Statically
tractable via the corpus + `dispatch_resolved.csv` + resolving RAM bases from caller configs.

## CORRECTION + verified shift architecture (agent trace, 2026-08-21)
**IMPORTANT axis correction:** in each `0x1C`-byte shift record, `u16[0..6]` is the **input
X-axis** and `u16[7..13]` is the **output column**. The tuple `[1340 2015 3000 3770 4885 6300
7500]` is the *input axis* (byte-identical across all 318 records, stride 0x18C) — so **6300/
7500 are the top input-axis breakpoints, NOT the tunable output cells.** The value the map
commands is the **paired output column** (e.g. input `7500`→output `~7250/6000/1580` depending
on the map). To change shift behaviour you edit the **output column** of the relevant record;
the "rpm ceiling" is where a curve saturates at the 7500 input breakpoint. (Supersedes the
earlier "raise the 6300 cells" note above.)

**Verified shift control structure** (read from decompiled C):
- Periodic **scheduler task table `0x141700`–`0x141838`**: `(RAM ctx_ptr, handler_fn)` u32 pairs;
  each handler is a per-cycle state machine on its own RAM context.
- `gear_ratio_monitor_step` `FUN_0012fe7e` (ctx `0xfff954e4`): ratio = `out*3000/(in<<2)` over 6
  gear speeds. Inputs: output-shaft speed `0xfff95524`, six input/turbine speeds
  `0xfff95518..0xfff95522`. Reset/recompute: `FUN_0012fcc4`.
- `gear_detect_plausibility` `FUN_00133aee` (ctx `0xfff8e578`): actual-gear detection via ratio
  vs tolerance bands; ASIL `~`-complement redundant speed copies.
- `gear_to_shift_element` `FUN_0012e1b2`: gear 1..5 → shift-element bitmask.
- Registry `0x5c778` (+ parallel copy `0x189504`); master `0x5fcac` (37 groups). **RAM bases are
  const-installed by init stubs** (e.g. `FUN_00115848: *0xfff84a00 = 0x5b7a0`) — so the RAM
  function-pointer/base indirection IS statically resolvable by reading those stubs.

**Still open (needs the init-stub resolution):** the generic curve interpolator, the current-gear
/ pedal-load / target-gear RAM globals, and the shift-command function.

## Corrected shift-RPM tuning target (data-verified)
318 shift curves share the input axis `[1340 2015 3000 3770 4885 6300 7500]`; the **output
column** is the commanded value. Output-max distribution: **7250 rpm (174 curves)** = the
high-throttle shift threshold (the real "shift up at ~7250" lever), 6000 (42), 1580/1350
(62, low-throttle/eco early shifts). To raise shift RPM you edit the **7250 output cells**
(full inventory: `analysis/shift_curves.csv`), NOT the 6300/7500 input-axis breakpoints.

## Max-torque loop — TRACED (agent, verified)
**Input-torque-limit Kennfelder: `0x1b0cc0`+, 204-byte records (stride `0xcc`).** Layout: hdr
`[0,8]` → row axis s16 `[0 10 22 38 63 88 113 141 172 203 -60 -18]` → **col axis u16
`[0 48 102 198 300 402 498 600]` = engine input torque (Nm, max 600 = 8HP55 rating)** → 10×8 Nm
grid. Inventory: `analysis/torque_maps.csv`.
- **Selected by gear × mode/state**: dispatchers `cal_registry_select_by_gear` `FUN_000b69d4`,
  `tqmap_select_dispatch` `FUN_0010ca26`, `..dispatch2` `FUN_000deb16` index `*(PTR + gear*4 +
  state*8)`. Pointer registries `0x051d34`–`0x051e38` (+ parallel `0x18532c`).
- **Full request chain**: gear/state → registry select → torque Kennfeld interp (axis = engine
  torque) → result RAM `0xfff8c814/81c/824` → generic TX struct (`_DAT_fff91a68 + msgidx*0x28`,
  msgidx=1) → source buf `0xfff91c90+2..3` → mirror packer `FUN_00073774` → frame `0xfff91c88`
  → **CAN 0x082 Getriebe_01.GE_MMom_Soll**.
- To raise held torque: raise the grid cells in the relevant gear×mode Kennfeld(en).
- Open: the exact store into `0xfff91c90+2` (reached via `_DAT_fff91a68`-based struct, not
  greppable) and the engine-torque input databuf (Motor_01 0x080 RX, undecoded).

## CHARISMA — TRACED, and a correction (agent, verified)
**Full path verified:** CAN `0x385` Charisma_01 → COM engine → decoded byte `0xfff89454`
(`rx_get_charisma_fahrpr` `FUN_0009fe28`) → periodic gather `FUN_00141b9c` writes ctx
`0xfff95172` → scheduler handler `FUN_0012e1b2` latches `0xfff95175` → `FUN_0012e164` →
`can_tx_setsig_getriebe_04` `FUN_0008ba62` packs **Getriebe_04.GE_Charisma_FahrPr (0x441 bit24)**.

**CORRECTION (supersedes §3 "CHARISMA selects the map set"):** exhaustive pool-reference
enumeration shows the drive-program variable's ONLY consumers are this echo path. **No verified
code indexes the shift-map tree (`0x5fcac`/`0x5c778`) by the drive-program variable** on this
image. Shift/torque map selection is **condition-indexed (gear × throttle × temp/state)** via the
descriptor tree, not a direct CHARISMA-program index. So on this SW the drive-program is
received/latched/echoed but is NOT a shift-program set selector. (Plausible: the sport shift
program on this torque-converter auto is chosen by the **gear-lever D/S position (Waehlhebel)**,
a separate input — not yet confirmed.) Earlier §3 was an inference, not borne out by dataflow.
