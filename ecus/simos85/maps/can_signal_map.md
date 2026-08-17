# CAN signal / handler map (8R0907551F)

Wire-level bindings: which CAN IDs the engine accepts, which have real handlers, and how the generated
AUTOSAR-Com stack moves signals between frames and RAM. The functional interpretation of the ACC
longitudinal frames is in `acc_flow.md`.

## E2E protection — the MLB seed rule

`seed = (id >> 8) ^ (id & 0xff)`. Verified against this firmware: 0x109→0x08, 0x10D→0x0C, 0x106→0x07,
0x10C→0x0D, 0x104→0x05, 0x10E→0x0F (ESP_01 0x100→0x01 and ESP_02 0x101→0xAB/0xAA are the documented
magic exceptions — see memory `vw-mlb-checksums`).

Each **dedicated RX decoder** validates `(b0 ^ b1 ^ … ^ b7) == seed` plus the rolling counter in byte1's
low nibble, and **discards** bad frames. That makes the rule an identification tool: any decoder's frame
can be back-solved from the XOR constant it checks. The generic Com layer does **not** do this — the
per-message Com CHKSUM/COUNTER hooks (`0x801d0360` / `0x801d0364`) are stubs, so E2E on periodic traffic
is enforced only by the dedicated decoders.

## Master acceptance dispatch @ `0x80082f18`

104-entry `{id_word, descriptor}` table, `id_word = flag<<16 | CAN_ID`. Only **13 message objects have a
dedicated hardware-mailbox handler** (descriptor 3rd word `d2 != 0` → a 24-byte record
`{0x800aa024, buf, HANDLER, …}`). The other 91 accepted IDs are filter/participation entries —
generic-Com/gateway-relayed or accepted-and-dropped — **including 0x117 ACC_10/AEB, which has a null
handler: the engine does not process AEB.**

Accepted-ID set: `0x100-0x11b`, `0x125-0x135`, `0x138-0x13f`, `0x142-0x154`, `0x158-0x174`, `0x17b-0x17f`
(`0x100-0x104` alias the `0x105/107/108/109` descriptors — a second acceptance filter over the same
mailboxes).

### The 13 dedicated handlers

| CAN ID | name | dir | handler | mechanism / RAM |
|---|---|---|---|---|
| 0x105 | Motor_03 | TX | `0x800a7c48` (body `800a7c4c`) | engine status out (sender Motor_EDC17_D4) |
| 0x107 | Motor_04 | TX | `0x8011e94a` | pops TX queue head `d000d3fc`, node+8..+0xf → mailbox |
| 0x108 | id108 | TX | `0x8011e98c` | pops TX queue head `d000d400` |
| **0x109** | **ACC_01** | **RX** | `0x8011e8f8` | stages the raw 8 B → `d000d40a`, flag `d000d408 = 1` (sender Gateway_B8) |
| 0x10a | TSK_01 | TX | `0x801d2968` | `com_process_ipdu(6)` |
| 0x10b | LS_01 | RX | `0x801d2962` | `com_process_ipdu(5)` (sender Gateway_D4C7) |
| **0x10c** | **TSK_02** | **TX** | `0x801d2956` | `com_process_ipdu(3)` — carries `TSK_Verzoeg_Anf` (decel out) |
| **0x10d** | **ACC_05** | **RX** | `0x801d296e` | `handle_ecu_command_800afcd2(0)` (sender Gateway_D4C7) |
| **0x10e** | **TSK_04** | **TX** | `0x8011e9ce` | pops TX queue head `d000d404`; `TSK_Status_GRA_ACC_02` = node+0xf |
| 0x10f | id10f | ? | `0x801d295c` | `com_process_ipdu(4)` |
| 0x112 | id112 | ? | `0x801d2950` | `com_process_ipdu(2)` |
| 0x115 | id115 | ? | `0x801d2974` | `handle_ecu_command_800afcd2(1)` |

`com_process_ipdu@0x800af8bc` and `handle_ecu_command@0x800afcd2` are both ISO-TP/transport-style state
machines over config root `d0000cd0 = 0x800906fc` (computed-pointer dispatch); neither statically writes
the `d5c0-d6ff` signal mirrors. No further canmo handlers exist among the recovered functions — the
handler set is exactly these 13.

## The ACC-longitudinal ingress decoders

Separate from the mailbox handlers above: the RX poll loop `80108cc4` runs three dedicated decoders —
`801383e8` (handle 0x240, seed 0x08) = **ACC_01/0x109**, `801383fc` (0x8a0, seed 0x0C) =
**ACC_05/0x10D**, `80106db8` (0x600, seed 0x07) = **ESP_05/0x106**. Signal-by-signal breakdown in
`acc_flow.md` §1.

**GAP:** the mailbox-handle ↔ CAN-ID binding (0x240 / 0x8a0 / 0x600) lives in external HAL/COM config.
It is established to high confidence by E2E seed + FR + opendbc triangulation, not by a decoded config
line.

## Where the ACC accel command lives

`ACC_Sollbeschleunigung` in **ACC_01 (0x109)** is a single signed acceleration field whose negative half
is the decel command; it is decoded to `d0007bac` by `801383e8`, and that is the value the −3.0 clamp
acts on. There is **no separate brake/target-decel RX message** in the engine's accepted set (ACC_05
goes to transport; ACC_10/0x117 is not processed). On-car, the outgoing `TSK_Verzoeg_Anf` tracks the
ACC_01 signed accel down to −3.000 and then hard-caps, which is the same conclusion from the other side.

The `d000d5c0-d000d6ff` block is an **internal mirror**, written by `801dec08` from engine state (e.g.
`d000d606 = Ramd000740c`, `d000d644 = clamp(d5618·32/25)` = ego speed) — it is not a CAN-decode target.
A byte-granular reader sweep over it lands entirely in the torque/enable/status cluster; nothing there
computes deceleration or touches the −3.0 cal:

- `d5c8/d5ca/d5cc/d5ce` (4 × s16) → `801e9b86` **and** `update_engine_control_parameters@801f0204`
  (clamps each to `max(0,x)` → the positive-torque vector `d000da4a-da50`)
- `d606` (s16, 0.005 m/s²/bit), `d644` (u16 speed), `d656-658` (status) → `801e9b86` only
- `d611/d612`, `d628/d62d`, `d67c` → `update_control_flags@801e6d54` (→ torque out `d000e2be/e2bf`)
- `d671` (mode 2/3/5) → `update_status_flags@801eecfc` (cal-demux → `d0005c3x`, `d000e22a`)

## AUTOSAR-Com RX/TX signal-buffer architecture

Com init `FUN_801ceff4(0)` wires three roots: `DAT_d0000cd0 = 0x800906fc` (flash config),
`DAT_d0000cd4 = 0xc0002798` (runtime-state array, 0x14 B per connection), `DAT_d0000cd8 = 0xd0000626`.

- Config root `0x800906fc`: `{count = 6, PDU_desc@+4 = 0x80090654 (0x1c/desc), handle_tbl@+8 = 0x80090710,
  runtime_state@+0xc = 0xc0002798, buf_desc_array@+0x10 = 0xc0002810}`.
- Per-connection runtime state `0xc0002798 + conn*0x14`: `+0x10` = buffer-descriptor pointer =
  `0xc0002810 + conn*8`.
- `initialize_ecu_state_800af81c`: the buffer descriptor is `{u32 data_ptr@0, u16 len@4, u8@6}`;
  `data_ptr` is 0 until a frame or TX cycle populates it.
- **6 connections:** c0 = ACC_05 (0x10d RX), c1 = id115, c2 = id112, **c3 = TSK_02 (0x10c TX, decel
  out)**, c4 = id10f/LS_01, c5 = TSK_01 (0x10a TX). Buffer descriptors at
  `0xc0002810/18/20/`**`28`**`/30/38`.
- **Com signal API** (`0x80124xxx` layer): `801cf11a` = `Com_SendSignal` (`*(dataptr) = value`), called
  only by `801240a0`; `801cf0aa` = status read via `80124090`/`801240dc`. All are dispatched indirectly
  through the runtime Com context `_DAT_c03fc37c` (ctx+0x10 = buffer array, ctx+0x1c = descriptor), and
  the PDU pack callbacks (`pdu_assemble_TSK_02_0x10c@0x80123f10` and siblings) reach
  `PTR_com_ipdu_process_step_80020134` through that same context.

**Consequence for static analysis:** the signal↔address binding is built at boot into the C-RAM Com
context, so the decel flow's last hop —
`coordinator → shadow → generic Com per-signal pack → 801240a0 → 801cf11a → buffer 0xc0002828` — reads
the shadow through a computed pointer. Emulation (`core/ghidra/EmulComWatch.java`) confirms Com init
materializes all 6 states and descriptors at the predicted addresses, but `com_process_ipdu(3)` invoked
cold is RX/frame-oriented and returns early, so the TSK_02 pack only runs on the cyclic path that a
partial-boot emulation does not execute. **This is the runtime-context ceiling on static binding**: it is
why the accel→torque converter must be resolved on the bench rather than in the image.
