#!/usr/bin/env python3
# Can the request input alone (0x4054c4, from ACC_10 conditioning) drive the recomputed decel
# 0x4066e0 to the 0x461 arm threshold, with zeroed wheels? Emulate anb_decel_from_wheels (0x7c1d4).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def decel_out(req):
    e = Emu(); e.call(0x872cc, args=(0x10,))
    # request source + the two clamp bounds the function reads (0x4054c4 = DAT_0007c418)
    for _ in range(5):
        e.wr(0x4054c4, req & 0xffff, 2)       # DAT_0007c418 (request)
        e.wr(0x4085ce, req & 0xffff, 2)       # DAT_0007c424 (second request input)
        e.call(0x7c1d4)
    return e.rds(0x4066e0, 2), e.rds(0x4065e4, 2)

print("request(0x4054c4) | recomputed decel(0x4066e0) | armed? (>=0x461)")
for req in (0x100, 0x400, 0x800, 0x1000, 0x2000, 0x4000, 0x7fff):
    d, d2 = decel_out(req)
    print(f"  0x{req:04x}           | {d:6d} (0x{d&0xffff:x})            | {'YES' if d>=0x461 else 'no'}")
