# Simos8.5 engine ECU — CAN signal / handler map (8R0907551F)

Decoded from the master acceptance-dispatch table @0x80082f18 (104-entry `{id_word, descriptor}`;
`id_word = flag<<16 | CAN_ID`). Only **13 message-objects have a dedicated hardware-mailbox handler**
(descriptor 3rd word `d2` != 0 -> 24-byte record `{0x800aa024, buf, HANDLER, ...}`). The other 91
accepted IDs are filter/participation entries (generic-Com/gateway-relayed or accepted-and-dropped) —
**including 0x117 ACC_10/AEB, confirming the engine does not process AEB**.

Accepted-ID set: 0x100-0x11b, 0x125-0x135, 0x138-0x13f, 0x142-0x154, 0x158-0x174, 0x17b-0x17f
(0x100-0x104 alias the 0x105/107/108/109 descriptors = a 2nd acceptance filter for the same mailboxes).

## The 13 dedicated handlers
| CAN ID | name | dir | handler | mechanism / RAM |
|---|---|---|---|---|
| 0x105 | Motor_03 | TX | 0x800a7c48 (body 800a7c4c) | engine status out (sender Motor_EDC17_D4) |
| 0x107 | Motor_04 | TX | 0x8011e94a | pops TX queue head `d000d3fc`, node+8..+0xf -> mailbox |
| 0x108 | id108 | TX | 0x8011e98c | pops TX queue head `d000d400` |
| **0x109** | **ACC_01** | **RX** | 0x8011e8f8 | stages raw 8B -> `d000d40a`, flag `d000d408=1`, enqueue `halt_baddata_d40016f8` (sender Gateway_B8) |
| 0x10a | TSK_01 | TX | 0x801d2968 | com_process_ipdu(6) |
| 0x10b | LS_01 | RX | 0x801d2962 | com_process_ipdu(5) (sender Gateway_D4C7) |
| **0x10c** | **TSK_02** | **TX** | 0x801d2956 | com_process_ipdu(3) — carries `TSK_Verzoeg_Anf` (decel request OUT) |
| **0x10d** | **ACC_05** | **RX** | 0x801d296e | handle_ecu_command_800afcd2(0) (sender Gateway_D4C7) |
| **0x10e** | **TSK_04** | **TX** | 0x8011e9ce | pops TX queue head `d000d404`; status `TSK_Status_GRA_ACC_02` = node+0xf |
| 0x10f | id10f | ? | 0x801d295c | com_process_ipdu(4) |
| 0x112 | id112 | ? | 0x801d2950 | com_process_ipdu(2) |
| 0x115 | id115 | ? | 0x801d2974 | handle_ecu_command_800afcd2(1) |

`com_process_ipdu@0x800af8bc` and `handle_ecu_command@0x800afcd2` are BOTH ISO-TP/transport-style state
machines over config root `d0000cd0=0x800906fc` (computed-pointer dispatch); they do NOT statically write
the `d5c0-d6ff` signal mirrors. No new canmo handlers exist among the +683/+2396 recovered functions —
the handler set is exactly these 13.

## ACC input-mirror reader sweep `d000d5c0-d000d6ff` (byte-granular FindRefsTo)
Non-`801e9b86` readers highlighted; ALL resolve into the **torque/enable/status** cluster, none computes
deceleration or touches the -3.0 cal:
- `d5c8/d5ca/d5cc/d5ce` (4x s16) -> 801e9b86 AND **update_engine_control_parameters@801f0204** (clamps each to max(0,x) -> positive-torque vector `d000da4a-da50`)
- `d606` (ACC accel s16, 0.005 m/s2/bit), `d644` (speed u16), `d656-658` (status) -> **801e9b86 ONLY**
- `d611/d612`, `d628/d62d`, `d67c` -> **update_control_flags@801e6d54** (-> torque out `d000e2be/e2bf`)
- `d671` (mode 2/3/5) -> **update_status_flags@801eecfc** (cal-demux -> `d0005c3x`, `d000e22a`)

## Where the decel command lives
It is **`ACC_Sollbeschleunigung` in ACC_01 (0x109)** — a single SIGNED acceleration field whose negative
half IS the decel command — decoded into mirror `d000d606` (s16, 0.005 m/s2/bit). There is **no separate
brake/target-decel RX message** in the engine's accepted set (ACC_05 goes to transport; ACC_10/0x117 not
processed). On-car, the outgoing `TSK_Verzoeg_Anf` tracks the ACC_01 signed accel down to -3.000 then
hard-caps -> the clamped quantity IS the ACC_01 accel. The decel coordinator reads `d606` + the -3.0 curve
through runtime-computed pointers (only 801e9b86 statically reads d606; d606/d644/d656 have NO static
writers either — the Com decoder writes them via computed pointers) -> same runtime-context ceiling.

## AUTOSAR-Com RX/TX signal-buffer architecture (from the +4000 recovered functions)
Com init `FUN_801ceff4(0)` wires three roots: `DAT_d0000cd0=0x800906fc` (flash config),
`DAT_d0000cd4=0xc0002798` (runtime-state array, 0x14 B/conn), `DAT_d0000cd8=0xd0000626`.
- Config root `0x800906fc`: {count=6, PDU_desc@+4=0x80090654 (0x1c/desc), handle_tbl@+8=0x80090710,
  runtime_state@+0xc=0xc0002798, buf_desc_array@+0x10=0xc0002810}.
- Per-conn runtime state `0xc0002798+conn*0x14`: +0x10 = buffer descriptor ptr = `0xc0002810+conn*8`.
- `initialize_ecu_state_800af81c`: buffer descriptor = `0xc0002810+conn*8` = {u32 data_ptr@0, u16 len@4,
  u8@6}; data_ptr is 0 until a frame/TX cycle populates it.
- **6 connections:** c0=ACC_05(0x10d RX), c1=id115(0x115), c2=id112(0x112), **c3=TSK_02(0x10c TX, decel
  out)**, c4=id10f/LS_01, c5=TSK_01(0x10a TX). Buffer descriptors at 0xc0002810/18/20/**28**/30/38.
- **Com signal API** (`0x80124xxx` layer): `801cf11a`=Com_SendSignal (`*(dataptr)=value`) called only by
  `801240a0`; `801cf0aa`=status read via `80124090`/`801240dc`. All are dispatched indirectly through the
  runtime Com context `_DAT_c03fc37c` (ctx+0x10=buffer array, ctx+0x1c=descriptor), and the PDU pack
  callbacks (`pdu_assemble_TSK_02_0x10c@0x80123f10` etc.) call `PTR_com_ipdu_process_step_80020134`
  through that same context.
- **Verified by emulation** (`core/ghidra/EmulComWatch.java`): Com init materializes all 6 states/descriptors
  at the predicted addresses; but `com_process_ipdu(3)` cold-invoked is RX/frame-oriented and returns early
  (2 reads), so the TSK_02 TX pack runs only via the generic Com main + runtime context (the cyclic path
  that does not execute in partial-boot emulation). Decel flow end-to-end:
  `coordinator -> shadow -> generic Com per-signal pack -> 801240a0 -> 801cf11a -> buf 0xc0002828`,
  the pack reading the shadow through `_DAT_c03fc37c` (computed) = the runtime-context ceiling, re-confirmed.
