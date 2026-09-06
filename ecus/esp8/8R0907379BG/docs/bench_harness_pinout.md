# ESP8 8R0907379BG — T38a connector pinout + bench harness

Source: Audi Q5 (8R) ELSA current-flow diagram **№122**, "Anti-lock braking system (ABS)
with electronic stability program (ESP)", from 05.2012. Module = **J104** (ABS control unit),
connector **T38a** (38-pin). Pin functions read wire-by-wire off diagram pages 122/1–122/5.
Cavity numbers are molded on the connector housing (photo: 1 top-right, 25 top-left, 13
bottom-right, 38 bottom-left).

## Confirmed pins (16 of 38 populated)

| Pin | Wire (col / mm²) | Function | Bench role |
|----:|------------------|----------|-----------|
| 1  | rt/sw 4.0  | **B+ (term 30)** main / valve+pump supply | +12 V (fused) |
| 25 | rt/br 2.5  | **B+ (term 30)** supply | +12 V (fused) |
| 7  | rt/gr 1.0 *(*2 gauge varies)* | **B+ (term 30)** supply | +12 V (fused) |
| 35 | gn/sw 0.35 | **Terminal 15** ignition positive (→B273) | +12 V (ignition) |
| 32 | rt 0.35    | **Terminal 15a** ignition (→B135) | +12 V (ignition) |
| 13 | br 4.0     | **Ground** (→671) | bench GND |
| 38 | br 2.5     | **Ground** (→671) | bench GND |
| 37 | or/ws 0.35 | **CAN High** (chassis/sensor CAN, →B663) | Openport CAN-H |
| 24 | or/br 0.35 | **CAN Low**  (chassis/sensor CAN, →B664) | Openport CAN-L |
| 28 | ws/bl 0.35 | Speed signal output (→B464) | leave open |
| 8  | ws/sw 0.35 | AUTO HOLD button (E540) | leave open |
| 36 | ws/vi 0.35 | AUTO HOLD button lamp (E540) | leave open |
| 4  | sw/bl 0.35 | ASR/ESP-off button (E256) | leave open |
| 11 | ws/vi 0.35 | Hill-descent / parking-assist button | leave open |
| 29 | ge/vi 0.35 | button input | leave open |
| 5  | br 0.35    | Roof-crossbar sensor gnd (G625) | leave open |

Remaining cavities unused on this variant.

## KEY FINDING — single CAN, and it is the chassis/sensor CAN

T38a carries **exactly one CAN pair**: pin 37 (H) / pin 24 (L), labelled in ELSA as
"CAN bus – chassis sensors" (B663/B664). There is **no powertrain-CAN pair on the
connector**. J104 is the master of this private chassis/sensor CAN (ESP sensor cluster
G419, sensor block 2 G536, active steering J792, AWD J492, roof sensor G625); the
**gateway J533 bridges it for diagnostics**.

This is why on-car the ABS never answered UDS `0x713` directly on the OBD powertrain bus
(memory `abs-sa2-key`): it lives behind the gateway on the chassis CAN, on a transport we
never captured. **On the bench you wire straight to pins 37/24, so there is no gateway and
the ABS is addressed directly** — the routing problem disappears.

## Minimal bench harness

- **+12 V (fused ~7.5 A):** pins **1, 7, 25** (term 30) + **32, 35** (term 15). Jumper 30/15
  together to one +12 rail on the bench.
- **Ground:** pins **13, 38** to the same bench ground.
- **CAN:** pin **37 → CAN-H**, pin **24 → CAN-L** to the Openport. Try **500 kbps** first.
  120 Ω term across H/L (the ABS provides one end; add one at the tool end).
- Everything else open.

Expect stored faults for the absent sensor cluster / steering / wheel-speed inputs. Normal
on a bare bench; does not block a programming session.

## Comms bring-up

1. 500 kbps, physical request `0x713` / response `0x77D`, `0x10 0x01`.
2. If silent: scan `0x700–0x7FF` with tester-present, and retry at 100 kbps.
3. Confirm with `0x22` of a known DID.

Then follow `bench_flash_procedure.md` (SA2 key in memory `abs-sa2-key`; identity-write the
stock block first). SBOOT is not on this bus — hardware read of the opened unit (see prior
guidance).
