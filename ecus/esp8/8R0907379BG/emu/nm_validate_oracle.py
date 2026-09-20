#!/usr/bin/env python3
"""NM-payload validation oracle for ESP8 (8R0907379BG) — session-2 result.

Runs the NM message processor FUN_00040950 (Thumb) under Unicorn with event=1
(NM-message-received) over candidate 4-byte NM payloads, and detects which reach
the SUCCESS path (writes the payload word to the NM status word 0x408f10 and sets
the network-active flags 0x408f20/0x408f21). This directly recovers the NM *content*
the ECU accepts, without needing the (object-table-routed) container CAN-id.

VERIFIED RESULT (this environment, ARM BE32, ram_bases.csv seeded):
- The NM data's SOURCE NODE-ID lives in payload byte 2 (matched against the node
  table at 0xbd83c via FUN_00040710). Accepted node-ids that pass validation:
      0x4a, 0x5f, 0x98, 0x99, 0x9a, 0xd4
- The control/byte0 that pass (with node in byte2, bytes1/3=0): 0x00, 0x02, 0x40, 0x42.
- Minimal passing payload: bytes  [00 00 <node> 00].

Container framing (from FUN_000689e4, the transport RX handler): the NM word is a
sub-PDU tagged 0x600 inside a reassembled transport payload; the 4 NM bytes are a
SCRAMBLED map of the payload bytes:
    NM_word = (buf[0x10e]<<24)|(buf[0x10d]<<16)|(buf[0x10c]<<8)|buf[0x10f]
  where buf = channel+0x108 (the reassembled payload). Thus, in payload terms:
    node   = payload byte4   (=buf[0x10c])
    ctrl   = payload byte6   (=buf[0x10e])
    sub-id = payload bytes[2:3] = 06 00
  => candidate single-frame container = [LL 00 06 00 NODE 00 CTRL 00].

BENCH STATUS (see bench/ sweeps): raw single-frame injection of the above framing
(and several variants, ISO-TP-style included) across all 225 accepted CAN-ids did
NOT wake the ECU. The container CAN-id and exact transport framing are RAM-wired
(object-table-routed) and not reproducible by blind injection. The node-ids here are
still the correct CONTENT to validate against a real captured partner/sensor-cluster
frame, or to use once the container id is recovered (object-table emulation / capture).

Run:  python nm_validate_oracle.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE

HERE = os.path.dirname(os.path.abspath(__file__))
RAM_BASES = os.path.join(HERE, "..", "analysis", "ram_bases.csv")
NM = 0x40950          # FUN_00040950, Thumb
DATA = 0x4f0000       # scratch for the 4-byte NM payload


def load_bases(e):
    for line in open(RAM_BASES):
        line = line.strip()
        if not line or line[0] in "#r":
            continue
        a, v = line.split(",")[:2]
        try:
            e.wr(int(a, 16), int(v, 16), 4)
        except Exception:
            pass


def trial(payload4):
    e = Emu()
    e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])   # seg2 (holds the node table/masks)
    load_bases(e)
    for a in range(0x408f00, 0x408f30):
        e.wr(a, 0, 1)
    e.uc.mem_write(DATA, bytes(payload4))
    wr = {}
    e.uc.hook_add(UC_HOOK_MEM_WRITE,
                  lambda uc, ac, a, sz, v, u: wr.__setitem__(a, v) if 0x408f00 <= a < 0x408f30 else None)
    e.call(NM, args=(DATA, 1, 0), thumb=True, maxinsn=200000)
    return (0x408f10 in wr), wr.get(0x408f10)


def main():
    print("NM node-id sweep (payload = [00 00 <b2> 00], event=1):")
    good = []
    for b2 in range(256):
        ok, val = trial([0, 0, b2, 0])
        if ok:
            good.append(b2)
    print("  accepted node-ids (byte2):", [hex(x) for x in good])
    if good:
        node = good[0]
        print(f"\ncontrol-byte (byte0) sweep with node=0x{node:02x}:")
        c0 = [b0 for b0 in range(256) if trial([b0, 0, node, 0])[0]]
        print("  accepted byte0 values:", [hex(x) for x in c0])


if __name__ == "__main__":
    main()
