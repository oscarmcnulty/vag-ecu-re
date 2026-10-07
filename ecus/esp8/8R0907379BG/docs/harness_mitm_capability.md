# Can an integrated comma 3X panda + harness relay MITM a second CAN bus (for EPB_01 rewrite)?

Short answer: **No.** Two independent blockers — only one intercept relay, and that relay is on
the wrong bus (ADAS/camera CAN, not the powertrain/chassis CAN where EPB_01↔ESP live). Sourced from
commaai/panda (board `cuatro` = C3X) and commaai/opendbc (VW/MLB port).

## Panda hardware (cuatro / C3X), verified from source
- **3 CAN transceivers:** `board/can.h` → `#define PANDA_CAN_CNT 3U` (buses 0/1/2).
- **Exactly ONE intercept relay:** `harness_t` tracks a single `relay_driven`; `set_intercept_relay()`
  drives one SBU relay; every board (`red`/`tres`/`cuatro`) has one `pin_relay_SBU1/SBU2` pair. No
  second relay exists on the integrated unit. (`board/drivers/harness.h`, `board/boards/cuatro.h`.)

## Why MITM needs a relay (not just a transceiver)
"MITM-rewrite" = block the genuine sender's frame and substitute your own. On a multi-drop CAN bus
you cannot selectively suppress one node's frames by transceiver alone — you must physically **split**
the bus into two segments and bridge them, so the relay is what lets the panda sit *in series*. One
relay ⇒ one bus can be split ⇒ one MITM. A spare transceiver only gives shared read/write (injection),
not interposition.

## VW/MLB bus topology (opendbc `volkswagen/values.py` CanBus)
With the J533 gateway harness (`NetworkLocation.gateway`), all three panda buses are already used:
- **bus 0 = pt** — "ADAS/Extended CAN, **gateway side of the relay**"
- **bus 2 = cam** — "ADAS/Extended CAN, **camera side of the relay**"
- **bus 1 = alt** — "**powertrain CAN**" (a plain tap)

So the single relay splits the **ADAS/Extended CAN** (bus0↔bus2); openpilot bridges/rewrites there
(steering HCA, and on MLB it sends ACC_05/ACC_02 to `pt`). The powertrain/chassis CAN is bus1 — a
shared **tap only**, not split.

## Consequences for the EPB_01 rewrite
1. **All 3 transceivers are allocated** (ADAS split ×2 + powertrain tap ×1) and **the one relay is on
   the ADAS bus** — there is nothing left to split a second bus.
2. **The relay isn't even on the right bus.** EPB_01 (EPB_D4 → ESP) and the ESP both sit on the
   powertrain/chassis CAN (the ESP receives 0x104 on its controller 0xfff7ea00). That bus is the
   panda's bus1 *tap* — openpilot can read it and transmit onto it, but **cannot block the EPB ECU's
   genuine EPB_01**. Injection alone collides the EPB_01 BZ counter → E2E fault (per
   `epb_intercept_feasibility.md`). No rewrite is possible from the integrated hardware.

## What a real EPB-01 MITM would require (added hardware, invasive)
- A dedicated interposer **in series on the powertrain CAN, between the EPB ECU and the ESP**: its own
  **relay/switch to split that bus** + **two transceivers** for the two halves + firmware to forward
  every frame and rewrite EPB_01 (fix CHK, keep BZ). i.e. a **second panda** (each = 1 relay + 3 buses)
  or a purpose-built CAN-bridge/firewall MCU, plus splicing the powertrain CAN.
- Note the powertrain/chassis CAN carries ABS/ESP/airbag-critical traffic; cutting it to insert a
  bridge is invasive and must be bench-validated. This is strictly more hardware and risk than the
  camera-bus intercept openpilot already does.

## Takeaway
The integrated C3X panda+relay is a **one-bus interceptor**, and that bus is the ADAS/camera CAN. The
EPB_01-rewrite path needs a **separate interposer on the powertrain CAN** — it is not achievable with
the stock comma harness alone. (This does not change the firmware findings; it bounds the deployment
option.)

Refs: commaai/panda `board/can.h`, `board/drivers/harness.h`, `board/boards/cuatro.h`;
commaai/opendbc `opendbc/car/volkswagen/values.py` (CanBus), `mlbcan.py`.

## Addendum — exact citations + second-panda integration (verified)

### Exact source for "1 relay + 3 transceivers" (commaai/panda)
- Bus count: `board/can.h:3` → `#define PANDA_CAN_CNT 3U` (buses 0/1/2).
- Transceiver enables: `board/boards/cuatro.h:9` `cuatro_enable_can_transceiver()` has cases 1U-4U;
  the 4th is the CAN2↔OBD mux (`tres_set_can_mode`, `CAN_MODE_OBD_CAN2`), not a 4th simultaneous bus.
- One relay: `board/drivers/drivers.h:122` `struct harness_t { … bool relay_driven; … }` (single flag);
  `board/drivers/harness.h:8` `set_intercept_relay()` drives one SBU relay; `board/boards/cuatro.h:106-107`
  has exactly one `pin_relay_SBU1/SBU2` pair (same shape in `red.h`, `tres.h`).

### Stock openpilot drives exactly ONE panda, over SPI (commaai/openpilot)
- `selfdrive/pandad/panda.cc:16` → `handle = std::make_unique<PandaSpiHandle>(serial)` (SPI only; no USB
  handle in the runtime path). `Panda::list()` = `PandaSpiHandle::list()` (panda.cc:35-37).
- `selfdrive/pandad/pandad.py:94-97` → `panda_serials = Panda.list(); assert len(panda_serials) == 1`.
- ⇒ The C3X's integrated panda is on SPI; a second (USB) panda is NOT enumerated or driven by stock
  openpilot. Using one requires either patching pandad/boardd (re-add a USB handle + multi-panda), or
  running the second panda INDEPENDENTLY of openpilot.

### Recommended second-panda architecture for the EPB rewrite
Use the spare panda as a **standalone in-line CAN bridge/firewall on the powertrain CAN**, not as a
second openpilot panda:
- Splice the powertrain CAN in series: EPB-ECU-side → bridge CAN-A, ESP-side → bridge CAN-B. Custom
  firmware forwards every frame A↔B and rewrites EPB_01 toward the ESP (fix CHK seed 0x05, keep BZ).
- The panda's one SBU relay is actually useful here as a **fail-safe**: wire the two bus halves through
  it so that if the bridge loses power/crashes, the relay de-energizes and reconnects the bus → stock
  EPB behavior restored. (This is the same fail-safe comma uses on the camera bus.)
- Command path (what decel to request): cleanest is openpilot transmitting a custom frame on a CAN bus
  the bridge also listens to — avoids any USB link to the C3X. (A USB link would need the C3X to expose
  a spare host port AND custom host software; the CAN command path sidesteps both.)
- SAFETY: an in-line node on the ABS/ESP/airbag powertrain CAN is high-stakes — added latency or a
  dropped frame affects safety-critical traffic. The relay covers total failure, not partial
  misbehavior. Bench-validate extensively before any on-car use.

Refs: commaai/panda `board/can.h`, `board/drivers/harness.h`, `board/drivers/drivers.h`,
`board/boards/cuatro.h`; commaai/openpilot `selfdrive/pandad/panda.cc`, `selfdrive/pandad/pandad.py`.

## CONFIRMED by comma's own harness docs (commaai/hardware) — 1 relay, 1 intercept bus
Checked against the VW J533 harness schematic + build guide (resolves "is two-bus MITM possible?"):
- `harness/README.md`: "An integrated relay ensures that you can remove the c3x... Internally, the
  camera's can bus is separated from the rest of the car." → ONE relay, and it separates exactly the
  camera/ADAS bus.
- `harness/BUILD_HARNESS.md`: "CAN2 and CAN0 are physically connected when the relay in the harness
  box is closed. [When] the relay [opens], control messages from the camera on CAN2 are blocked and
  messages from openpilot are sent on CAN0." → the single relay splits ONE bus: **CAN2 = camera side,
  CAN0 = car/gateway side**. That is the only interceptable (MITM) bus.
- `harness/BUILD_HARNESS.md`: "an additional CAN bus... called CAN1... **We cannot intercept this CAN
  bus**, but we can read and write messages... Typically connected to the radar. The harness box has
  two connections for CAN1, the wires are passed through." → **CAN1 is tap-only** (passive
  pass-through, no relay), confirming it cannot be MITM'd.
- The relay lives in the **harness box** (the adapter between car-harness and the C3X), driven by the
  panda's single SBU control; the panda provides the 3 transceivers (CAN0/1/2, `PANDA_CAN_CNT=3`).

So the J533 harness does physically connect to TWO gateway buses (the camera bus + CAN1/radar), which
can look like "two-bus MITM" on the wiring diagram — but only the camera bus (CAN0/CAN2) is
relay-split/interceptable; CAN1 is read/write tap-only. Net count: **3 CAN transceivers (panda) + 1
relay (harness box) = exactly one MITM-capable bus.** The EPB/powertrain bus is neither the camera bus
nor interceptable via CAN1, so an EPB_01 rewrite still needs a separate in-line interposer (second
relay + its own two transceiver halves) as described above.

Refs: commaai/hardware `harness/README.md`, `harness/BUILD_HARNESS.md`, `harness/v3/VW_J533_Harness.pdf`.
