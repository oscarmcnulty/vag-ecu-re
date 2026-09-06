# EPB dynamic braking — does the ESP read EPB_01, and how does "hold the lever" brake the car?

Target: Bosch **ESP8 quattro** `8R0907379BG_0030` (B8 Q5). Question: does this ABS/ESP module
receive the EPB (electronic parking brake) messages, and by what path does *pulling and holding the
EPB lever while moving* produce real hydraulic braking?

Short answer:
1. **Yes — the ESP receives `EPB_01` (CAN `0x104`).** It is entry #8 in the RX id-array `0xafae0`
   (`@0xafb00`). `EPB_01` is sent by the EPB ECU (`EPB_D4`), so for the ESP this is a *received*
   message (the ESP itself transmits only `ESP_01/02/03/05`).
2. **Holding the lever does not clamp the rear calipers while moving.** Instead the EPB ECU converts
   the held-switch into a **deceleration request** it puts on CAN, and the ESP executes it with the
   **hydraulic ESC pump/valves** — the same brake-pressure machinery ACC and AEB use. This is the
   regulatory "Notbremsfunktion" (parking-brake emergency stop). At standstill control hands over to
   the EPB motor clamp.

Everything below that is a *code fact* is marked so. The one link that is **inference, not
byte-proof** (which CAN frame feeds which internal decel source) is called out explicitly — it sits
behind the same runtime-COM routing wall documented in `com_routing_heuristics.md` / `rx_map_VERIFIED.txt`.

---

## 1. The EPB_01 payload — what the EPB ECU sends (from vw_mlb.dbc, DBC-verified)

`BO_ 260 EPB_01: 8 EPB_D4` — the brake-relevant signals:

| signal | bits | scale / unit | meaning |
|---|---|---|---|
| **`EPB_Verzoeg_Anf`** | 16–23 (byte 2) | 0.048, −7.968 m/s² | **EPB deceleration request** — the decel the ESP should apply |
| **`EPB_Freig_Verzoeg_Anf`** | 15 | bit | **release/enable** of that decel request |
| `EPB_Schalterposition` | 52–53 | 0–3 | lever/switch position |
| `EPB_QBit_Schalterpos` | 54 | bit | switch-position quality bit |
| `EPB_Status` / `EPB_Fehlerstatus` | 61–62 / 50–51 | — | EPB state / fault |
| `EPB_Spannkraft` | 56–60 | kN | clamp force (static hold feedback) |
| `EPB_Anfahrwunsch_erkannt` | 48 | bit | drive-away wish detected (release trigger) |

So the "hold the lever" command reaches the ESP as **`EPB_Verzoeg_Anf` (a m/s² decel value) +
`EPB_Freig_Verzoeg_Anf` (enable)**. The EPB firmware (`8K0907801N`, HCS12X — see `[[epb-b8-firmware]]`)
is what turns a held switch above a speed threshold into this decel request; the ESP is the executor.

## 2. The ESP receives EPB_01 (CODE FACT)

RX id-array `can_id_array @0xafae0`, u32 big-endian, first cluster is the `0x100–0x116` core group:
```
0xafb00: 0x00000104   <-- EPB_01, index 8
```
No other EPB id appears (only `EPB_01` exists on this bus). Reception of the `0x100–0x116` cluster is
AUTOSAR-COM, index-driven — the raw frame lands at a runtime-computed buffer (the documented wall),
exactly as for `ESP_05`, `ACC_05`, `TSK_*`.

## 3. Where a CAN decel request goes inside the ESP (CODE FACT)

The ESP arbitrates **four external deceleration-request sources**, each a 16-bit value gated by
`status byte == 0x10` **and** `enable bit 0x80` **and** `value > 0`
(`decel_req_assemble_types` @0x86798, `decel_req_preprocess_srcs` @0x7f4ec):

| type | source buf | producer | nature | executor / gating |
|---|---|---|---|---|
| type2 | `decel_src_comfort` 0x403a40 | `decel_src_comfort_calc` 0x88a88 | **internal** calc from COM inputs | comfort ramp, **speed-gated <15 km/h** |
| type4 | `decel_src_type4` 0x407bb4 | `anb_decel_request_build` 0x4bf3c | **internal** AEB state machine | flat step, **ungated** (works to 0) |
| type1 | `decel_src_type1` 0x403fac | `FUN_00043228` / `FUN_0002b568` | **internal** builder (reads ANB/brake-assist RAM 0x40774x/0x407f9x) | fixed sub-profiles |
| ~~type5~~ | `decel_src_type5` 0x403d76 | **none — RESERVED/UNUSED** (§4) | **never written; value always 0** | never wins |

Pipeline (all stages code-verified, see `decel_paths.md`):
```
COM deposit -> staging -> com_decel_double_buffer(0x64ce4) -> decel_src_typeN
   -> decel_req_preprocess(0x7f4ec) -> decel_req_assemble(0x86798) [tags type 1/2/4/5]
   -> decel_req_arbitrate(0x94a70)  MAX-decel-wins; winning type -> ecd_mode(0x405aba)
   -> ecd_state_machine(0x633fc) -> ecd pressure executors -> 6 wheel setpoints 0x403d94
   -> ecd_actuation_pipeline(0x9f190) -> pump/valve drivers (hydraulic service brake)
```
The winning request's **type == the executor mode**, and arbitration is **largest deceleration
wins** (no fixed source priority). The output is genuine **hydraulic service-brake pressure**, not
the EPB rear-caliper motors.

## 4. Which source is EPB? — NONE. (Earlier "type5 = EPB" is RETRACTED.)

An earlier version of this doc inferred that EPB fed decel source **type5**. That is **disproven** by
a bin-wide static parse of the flash COM config (`decode/parse_pb_config.py`, `com_routing_decoded.md`):

- **type5 (`0x403d76`) is RESERVED/UNUSED in this variant.** All type5 addresses — current `0x403d76`,
  staging `0x403d6e`, commit-dest `0x403d66`, enable `0x403d7d` — occur **only in code** (the
  double-buffer, preprocess, assemble, hold-manager), and **nowhere in the flash COM config** (≥0xa2000)
  across the whole 1.2 MB image. Staging `0x403d6e` has **no writer of any kind**; if a COM descriptor
  targeted it, `0x403d66` would appear as a flash literal, and it does not. So type5's value is
  permanently 0 and can never win arbitration. No CAN signal reaches it.
- **The other three sources are front-sensor, not EPB.** type1's COM input (`0x403fa2`) and type4's
  input (`0x407ce8`) **do** appear in the flash config; the PDU feeding type1 is a **17-signal
  front-camera/radar group** with bit-lengths `{6,4,4,10,2,2,12,2,2,6,2,2,4,8,8,8,8}`, which does **not**
  match EPB_01's DBC layout `{8,4,1,1,1,1,8,8,8,1,1,2,2,1,1,5,2,1}`. type2 is ACC/comfort; type4 is ANB.

⇒ **None of the four ECD decel-arbitration sources is EPB.** EPB dynamic braking does **not** enter the
type1/2/4/5 arbitration at all. It is therefore very likely a **separate, dedicated hydraulic-request
path** inside the ESP, distinct from the ACC/ANB decel machinery. EPB_01's own signals are in the
runtime (bump-allocated) object-table RX set, so `EPB_Verzoeg_Anf`'s buffer is not a flash literal and
was not positively located statically — that positive bind still needs the seeded config-init emulation
(materialise the object table) or finding EPB_01's dedicated handler via its `state_ram`.

## 5. Braking down to a stop, then the hold hand-off (CODE FACT + prior finding)

Two properties make the lever-hold brake all the way to standstill and then latch:

- **Below 15 km/h still brakes.** The 15 km/h floor (`ecd_speed_gate` 0x844fc, `cmp #0x78`) clears
  `flag_ecd_speed_avail`, and **only the comfort executor (type2) reads that flag**. The non-comfort
  emergency path (type4/ANB) is **not** speed-gated, so a non-comfort decel keeps building pressure
  below 15 km/h (`decel_paths.md` §3). A separate EPB hydraulic-request path would similarly need to be
  ungated to brake to a stop. NOTE: these gating facts are about the ECD/ACC arbitration, which §4 shows
  EPB does **not** use — they describe the machinery, not a proven EPB route.
- **Hold escalation.** `decel_hold_escalation_mgr` (0x42a5c) runs post-arbitration, reads the four
  type status bytes (type1 `0x403fb3`, type2 `0x403a37`, type4 `0x407bbb`, type5 `0x403d7d` — the last
  is dead, see §4) with `&4/&2` masks and, when a request is holding at target, **escalates it to a
  "type 3" hold state** (rate-limited `0x2d/0x7f`, clamped `0x500/0x80/0x3ffe`). This is the standstill
  hold for whichever ACC/ANB decel is active; whether the EPB path reuses it is not established.
- **Static clamp at 0.** Once stopped, the ESP requests the EPB motor clamp back over CAN
  (`ESP_05` request bit, per `ECD_path.md` §note and `[[epb-b8-firmware]]`), handing the static hold
  to the rear calipers so the hydraulic pump can release. `EPB_Spannkraft` reports the clamp force.

## 6. End-to-end mechanism (answer to the question)

```
driver holds EPB lever, car moving
      │  (EPB ECU 8K0907801N)
      ▼
EPB_01 (0x104): EPB_Verzoeg_Anf = requested decel,  EPB_Freig_Verzoeg_Anf = 1
      │  CAN
      ▼
ESP receives 0x104 (id-array idx 8)  ──COM──▶ EPB_Verzoeg_Anf buffer (runtime-allocated; NOT located)
      ▼
[dedicated EPB hydraulic-request handler — NOT the type1/2/4/5 ECD arbitration]  ← channel UNPROVEN
      ▼
ESC pump + wheel valves ⇒ hydraulic service-brake deceleration
      ▼  as v→0
static hold ──▶ ESP_05 request ⇒ EPB motor static clamp (hydraulics release; EPB_Spannkraft feedback)
```

**Bottom line.** What is PROVEN: the ESP reads `EPB_01`, and holding the lever is a **CAN deceleration
request** (`EPB_Verzoeg_Anf` + `EPB_Freig_Verzoeg_Anf`) that the ESP executes as real **hydraulic
service-brake** pressure (not the rear-caliper motors), then hands the standstill hold to the EPB
motors via `ESP_05`. What is now DISPROVEN: that it flows through the type1/2/4/5 ECD decel
arbitration — it does not (type5 is unused; the other three are front-sensor/ACC/ANB, §4). So the exact
internal channel is a **separate dedicated hydraulic-request path that has not been located**. Positively
binding it needs the seeded config-init emulation (to materialise `EPB_Verzoeg_Anf`'s runtime buffer) or
finding EPB_01's dedicated handler via its `state_ram` — both software-only, in-bin.

## 7. To locate the EPB channel (all software-only, in-bin — no bench needed)
The COM config is entirely in our flash (`com_routing_decoded.md`), so a SBOOT/BDM dump is NOT
required. Two in-bin routes:
- **Seeded config-init emulation** → run the ESP's own config-init/bump-allocator (`FUN_000892a0`/
  `FUN_0006b936`) with the object-table root pointers seeded from the flash PB-config, materialise
  `EPB_Verzoeg_Anf`'s runtime buffer, then trace its readers to find the dedicated EPB handler.
- **Find EPB_01's dedicated handler statically** → EPB_01 (`0x104`) deposits its frame in a per-message
  `state_ram`; locate that slot and the code that reads `EPB_Verzoeg_Anf`/`EPB_Freig_Verzoeg_Anf` out of
  it — that reader is the EPB hydraulic-request path (independent of the type1/2/4/5 ECD arbitration).
- **On-car capture (optional confirmation, not required):** log `EPB_01` while briefly holding the lever
  at low speed off public road and watch `ESP_05` (`ECD_Bremslicht`/`ESP_Status_Bremsdruck`) + wheel
  decel; a clean `EPB_Verzoeg_Anf`↔braking correlation confirms the mechanism empirically.


## GROUND-TRUTH CORRECTION (2026-09-03) — H1 CONFIRMED on the real car
The vehicle owner confirms: **holding the EPB lever DOES apply ESP emergency (hydraulic) braking.**
So `EPB_Verzoeg_Anf` IS consumed by the ESP as a brake demand (H1). The earlier lean toward "H2 /
maybe not a feature" is RETRACTED — it rested on EPB being absent from the *static-buffer* consumed
set, but bulk-RX signals (EPB included) are consumed through the *runtime-routed* (bump-allocated)
path, which a static-xref sweep can't see. The mechanism in sections 1-6 stands: EPB_01
EPB_Verzoeg_Anf (+ EPB_Freig_Verzoeg_Anf enable) -> ESP -> hydraulic service-brake deceleration. Since
EPB is proven NOT in the ECD decel arbitration (type1/2/4/5) and works at all speeds, the executor is
the base ABS/ESC active-pressure controller (not ECD), reached via the runtime object-table buffer.
STILL OPEN (in-bin, converging): the exact buffer address + handler. Registrar FOUND
(`FUN_00089f90` alloc + `FUN_0008e298` populate, dispatcher cases 0xd4/0xe0; build objtable @0x40a1a8
from a per-message `.rodata` PB-config via staging 0x4069a6). Remaining: decode the `.rodata` config
driver/format -> replicate the bump layout -> EPB's buffer -> its reader (the Notbremsfunktion handler).
