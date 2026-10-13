# ESP8 bare-die JTAG pad identification

Goal: locate the JTAG TAP pads on the decapped MCU die so the SBOOT/CBOOT can be dumped
(see `SECURITY_ACCESS.md` avenue 3). The MCU is the TMS470R1x / SM470R1B1M-family die (the
left/center die in the teardown; the right die is a companion driver ASIC — `RE_findings.md`).

**Key fact: the datasheet already gives the die pinout.** The SM470R1B1M-HT datasheet (SPNS155I)
Table 4-1 maps every bond pad number to a signal name, and §5 (Pin Functions) gives each pad's
I/O type and internal pull. So the JTAG pads are known *by name and position*; the only unknowns
are (a) the die's rotation/mirror in our photos and (b) whether this Bosch-custom mask keeps the
stock pad ring. Both are resolved below — first by anchoring to physically-identifiable nets, then
confirmed electrically (which does not depend on the pad ring matching).

## The JTAG pads (datasheet Table 4-1 + §5, page 22)

| signal | die pad | side / location | internal pull | I/O |
|---|---|---|---|---|
| **TCK**  | 79  | TOP edge, 4th pad in from the top-RIGHT corner | pull-DOWN (IPD 20 µA) | in |
| **TDO**  | 78  | TOP edge, 3rd in from top-RIGHT corner | pull-DOWN (IPD 20 µA) | out, 8 mA |
| **TDI**  | 77  | TOP edge, 2nd in from top-RIGHT corner | pull-UP (IPU 20 µA) | in, 8 mA |
| **TMS**  | 18  | BOTTOM edge, middle (pad 18 of 39) | pull-UP (IPU 20 µA) | in, 8 mA |
| **TMS2** | 17  | BOTTOM edge, middle (next to TMS) | pull-UP (IPU 20 µA) | in, 8 mA (2nd TAP) |
| **TRST** | 151 | LEFT edge, very bottom (bottom-LEFT corner) | pull-DOWN (IPD 20 µA) | in |
| TEST     | 127 | LEFT edge | pull-DOWN (IPD 20 µA) | internal-use; tie GND |

The minimal debug/programming set is **TCK, TMS, TDI, TDO, TRST + GND + a VCCIO (3.3 V) reference**.
TMS2 is the second TAP (boundary scan) — not needed for debug; the datasheet says tie it high to
VCCIO. There is **no RTCK** on this device.

The distinctive, findable signature: **TCK/TDO/TDI are a tight run of 3 adjacent pads right at one
corner (pads 77-78-79, ~124 µm pitch), on the top edge next to the top-right corner.**

## Die-photo cross-check (2026-10-11, left_die.jpg)

I deskewed the MCU-die photo (~0.6°) and counted pads per edge from enhanced per-edge crops.
Image quality (handheld macro, motion blur, vertical foreshortening, bond wires over pads) limits
precision, so these are ranges, but the result is decisive at the level that matters:

| edge (as photographed) | counted | datasheet B1M |
|---|---|---|
| left  | ~40 | 40 |
| right | ~36–38 | 36 |
| top   | ~37–43 | 37 |
| bottom | not countable (on-die striped blocks reach the edge) | 39 |

- **The per-edge counts match the stock SM470R1B1M pad ring.** So the die is the B1M (or a mask-
  compatible derivative with the same pad ring) — the earlier "spacings don't match the overlay" was
  an overlay scale/orientation problem, not a different die.
- **Orientation looks like the datasheet convention (pad 1 bottom-left, not mirrored).** Two reasons:
  (a) left=40 ≠ right=36 breaks the left/right symmetry — the 40-pad edge is datasheet-left, ruling
  out a plain horizontal mirror; (b) the **right-edge bonded pattern matches the pinout**: the lower
  right edge (pads 40–54 = I2C5/I2C4/SCI2 and GIO) shows a long **unbonded** run of unused serial
  pins, and the **bonded** cluster sits where VSS/VCC/CAN2 (pads 55–58) and VCCIO/VSSIO (71–72) are —
  CAN2 must be bonded (it's the diag bus, bench-confirmed operational). That bottom-serials-unbonded /
  mid-power-CAN-bonded reading is only correct in datasheet orientation, ruling out the 180°+mirror
  alternative. Confidence ~moderate (counts are within error bars); confirm with the crystal anchor.
- **Consequence for JTAG:** in datasheet orientation the **JTAG triple TCK/TDO/TDI is on the TOP edge,
  the 2nd–4th pads in from the TOP-RIGHT corner**; the crystal (OSCIN/OSCOUT) is on the bottom edge
  near the bottom-RIGHT corner; TMS/TMS2 are mid-bottom-edge; TRST is the bottom-LEFT corner pad.

## Orientation anchoring (do this first)

Fix the die's rotation/mirror from nets you can identify on the PCB. In the datasheet face-up
convention (pad 1 at bottom-left, numbering CCW), the right-hand side of the die is the comms/debug
edge:

| anchor | pads | where on the die | how to find it on the board |
|---|---|---|---|
| **Crystal** (15 MHz) | OSCIN 36 / OSCOUT 35 | BOTTOM edge, ~4-5 pads from bottom-RIGHT corner | the 2-pin resonator can; its two bond wires land here |
| **JTAG triple** | TCK/TDO/TDI 79/78/77 | TOP edge, next to top-RIGHT corner | diagonally up the same (right) edge from the crystal |
| **CAN2** | 57 / 58 | RIGHT edge, middle | trace from the vehicle/diag CAN transceiver |
| **CAN1** | 86 / 87 | TOP edge, ~11 pads from top-right corner | trace from the sensor/chassis CAN transceiver |
| **Reset** | RST 124 / PORRST 121 | LEFT edge, upper area | the reset supervisor IC net |
| **AWD** | 39 | bottom-RIGHT corner pad | analog watchdog external RC network |

Procedure:
1. Find the **crystal** and follow its two bond wires to the die. Those pads are OSCIN/OSCOUT,
   which sit ~4-5 pads from one corner on one edge. That single anchor fixes both rotation and
   mirror (it tells you which corner is "bottom-right" and which way the numbering runs).
2. Confirm with a **CAN transceiver**: CAN1 is on a different edge than CAN2, so matching one of
   them disambiguates a face-up vs mirrored image. Use the two mirror/rotation overlay sets below.
3. Now the **JTAG triple** is the 3 pads just in from the corner at the *top-right* of the die
   (the far end of the same edge the crystal corner is on, one edge over). **TMS/TMS2** are the
   adjacent pair near the middle of the crystal's edge; **TRST** is the corner pad farthest from
   the crystal (bottom-left).

Caveat: if this custom mask moved pads, the *grouping* (an OSC pair at one corner, a 3-wide JTAG
run at the adjacent corner, a TMS pair mid-edge) is pad-ring IP and usually survives even when exact
spacing does not — but treat the positions as a strong prior, not proof. Confirm electrically.

## Electrical confirmation (definitive — independent of the pad ring)

The internal pulls give each JTAG pad a DC signature. With the board **unpowered**, measure
resistance from a candidate net to GND and to the 3.3 V (VCCIO) rail; or **powered and idle** (TAP
not being driven), measure the DC level. The 20 µA internal pull ≈ 165 kΩ to the rail, so a bare
pad reads weakly toward its rail; a board pull resistor reads as a discrete value.

| idles / pulls | candidates |
|---|---|
| **HIGH** (pull-UP to VCCIO) | TDI, TMS, TMS2 |
| **LOW** (pull-DOWN to GND) | TCK, TDO, TRST, TEST |

Discriminators:
- **TRST** is the pull-DOWN pin the datasheet says to add an *external* pull-down to — look for a
  resistor to GND on a pad at the bottom-left corner.
- **TMS2** is the pull-UP the datasheet says to tie/pull to VCCIO — often strapped high if unused.
- **TDO** is the only *output* in the set (8 mA): while the TAP is clocked it will toggle; the
  others are inputs and stay at their pull level unless driven by a programmer.
- **TEST** (internal-use) and **FLTP2** (pad 135, must be left NC) are not JTAG — do not drive them.

## Important: are the JTAG pads even bonded out?

Many pads in our die photos are **unbonded**, and board-level JTAG access is **not a given on this
module** — temper expectations:
- Bosch's own field reflash of this ECU is over **CAN/UDS** (the ODIS/`10 85` programming-session
  path the whole `SECURITY_ACCESS.md` bench effort targets), **not** JTAG. JTAG is *our* desired path
  to dump SBOOT/CBOOT (which is not in the CAN-reachable image), not a production programming route.
- Aftermarket tools (CarProTool's "TMS470 Programmer" and similar) do access TMS470-family parts
  over JTAG via PCB test points on *some* boards, but their published pinouts are for **packaged**
  parts, not this bare-die hybrid. Whether *this* potted 8R0907379BG board exposes reachable JTAG
  test points is **unverified**.
- Our own teardown assessment (`SECURITY_ACCESS.md` avenue 5) is that this is a **potted bare-die
  hybrid where chip-off and JTAG-pad access are likely blocked**, which is exactly why voltage/clock
  glitching is logged there as the primary hardware avenue.

So: *look* for an unpopulated header or test-pad/via cluster near the MCU and buzz it out against the
die pads using the signatures above — but do not assume it exists. If the TAP pads are unbonded and
no test points are broken out, board-level JTAG is unavailable and the realistic paths are direct
die micro-probing (through the potting) or the glitching avenue.

## Overlay tooling

`docs/die_pad_overlay.py` renders the datasheet pad map with the JTAG + anchor pads highlighted.
A `--mirror` flag was added so you can match a flipped image; combine with `--rotate` for all 8
orientations. Generated references:
- `docs/b1m_jtag_anchors_quad.svg` — all 4 rotations, JTAG/OSC/reset/CAN highlighted.
- `docs/b1m_jtag_anchors_quad_mirror.svg` — same, mirrored.

Regenerate, e.g. a single orientation once the crystal anchor is known:
```
python docs/die_pad_overlay.py --highlight jtag,osc,can,reset --rotate 90           # face-up
python docs/die_pad_overlay.py --highlight jtag,osc,can,reset --rotate 90 --mirror  # flipped
```
Overlay these on the MCU-die photo, aligned so the OSC pads land on the crystal bond wires; the
rotation/mirror that also lands CAN on the transceiver nets is the correct orientation, and the
JTAG triple then points at the pads to probe.
