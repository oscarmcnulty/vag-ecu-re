#!/usr/bin/env python3
"""ESP8 (8R0907379BG) NM-wake bench probe — uses the emulator-verified NM content.

The NM message processor FUN_00040950 accepts these SOURCE NODE-IDs (recovered by
emu/nm_validate_oracle.py): 0x4a, 0x5f, 0x98, 0x99, 0x9a, 0xd4, with control byte
in {0x00, 0x02, 0x40, 0x42}. The NM word is a sub-PDU tagged 0x600 inside a
transport container; candidate single-frame layout: [LL 00 06 00 NODE 00 CTRL 00].

This probe sweeps each of the ECU's 225 accepted CAN-ids ONE AT A TIME (non-
saturating, ~100 Hz) cycling the framing hypotheses, and watches for the ECU to
react (any tx id other than the 0x060 heartbeat, or the 0x060 stream stalling).

STATUS: as of session 2 this produced NO reaction — the container CAN-id and exact
transport framing are object-table-routed (RAM-wired) and not reproducible blind.
Kept as the ready harness to re-run once (a) the container id is recovered via
object-table emulation, or (b) a real private-CAN capture gives the true frame, or
to validate a captured partner frame's node-id against the accepted set above.

Run with 32-bit Python:
  <py311x86>\\python.exe nm_probe.py            # framing sweep, node 0x5f
  <py311x86>\\python.exe nm_probe.py --node 0x9a --secs 0.4
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, ACCEPTED_IDS, HEARTBEAT_ID  # noqa: E402

NODES = [0x4a, 0x5f, 0x98, 0x99, 0x9a, 0xd4]
CTRLS = [0x00, 0x42]


def framings(node, ctrl):
    return [
        bytes([0x07, 0x00, 0x06, 0x00, node, 0x00, ctrl, 0x00]),  # container, node@4
        bytes([0x06, 0x06, 0x00, node, 0x00, ctrl, 0x00, 0x00]),  # ISO-TP SF wrap
        bytes([0x06, 0x00, node, 0x00, 0x00, 0x00, 0x00, 0x00]),  # sub-id@0, node@2
        bytes([node, ctrl, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00]),  # node@0
        bytes([0x00, 0x00, 0x06, 0x00, node, 0x00, ctrl, 0x00]),  # container, LL=0
    ]


def sweep(node, secs):
    c = RawCAN()
    fr = [f for ctrl in CTRLS for f in framings(node, ctrl)]
    print(f"NM probe: {len(ACCEPTED_IDS)} ids x {len(fr)} framings, node=0x{node:02x}, "
          f"{secs}s/id")
    react = []
    for cid in ACCEPTED_IDS:
        s060 = 0
        other = []
        t0 = time.time()
        k = 0
        last = 0.0
        while time.time() - t0 < secs:
            now = time.time()
            if now - last >= 0.008:
                last = now
                c.write(cid, fr[k % len(fr)])
                k += 1
            r = c.read(1)
            if r:
                rid, pl = r
                if rid == HEARTBEAT_ID:
                    s060 += 1
                else:
                    other.append((hex(rid), pl.hex()))
        if other:
            react.append(cid)
            print(f"  id 0x{cid:03x}: REACTION {other[:4]}")
    print("reactions:", [hex(x) for x in react] or "NONE")
    c.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--node", type=lambda s: int(s, 0), default=0x5f)
    ap.add_argument("--secs", type=float, default=0.3)
    a = ap.parse_args()
    sweep(a.node, a.secs)


if __name__ == "__main__":
    main()
