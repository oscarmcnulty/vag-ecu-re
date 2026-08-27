#!/usr/bin/env python3
# Sweep the decel demand into the ANB builder to find the activation threshold and the
# output transfer. Answers: does a modest (openpilot-level) request produce ANB output, or
# only an emergency-level demand?
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def run_at(decel_mag, jerk_in, cycles=5):
    e = Emu()
    e.call(0x872cc, args=(0x10,))
    try: e.call(0x7e2d8)
    except Exception: pass
    for _ in range(cycles):
        e.wr(0x405cac,0x10,1); e.wr(0x40553b,0x08,1)
        e.wr(0x4066e0,decel_mag,2); e.wr(0x4055b4,0x40,2); e.wr(0x4055e4,0,2)
        e.wr(0x405abe,0,1); e.wr(0x407c29,0,1); e.wr(0x405473,0,1)
        e.wr(0x407906,jerk_in,2); e.wr(0x403dac+0x12,0,2); e.wr(0x403dac+0x72,0,2)
        e.call(0x4bf3c)
    return e.rds(0x407be2,2), e.rd(0x407bf0,4)

print("decel_mag(0x4066e0) | out(0x407be2) | statusword")
for dm in (0x100, 0x400, 0x460, 0x461, 0x500, 0x600, 0x800, 0x1000):
    out, sw = run_at(dm, 0x2000)
    gate = "" if dm >= 0x461 else "(< 0x461 gate)"
    print(f"  0x{dm:04x} {gate:14s} | {out:6d}      | 0x{sw:08x}")
print("\nfreigabe OFF (0x40553b bit3 clear) at decel 0x600:")
e=Emu(); e.call(0x872cc,args=(0x10,))
try: e.call(0x7e2d8)
except Exception: pass
for _ in range(5):
    e.wr(0x405cac,0x10,1); e.wr(0x40553b,0x00,1)  # freigabe OFF
    e.wr(0x4066e0,0x600,2); e.wr(0x4055b4,0x40,2); e.wr(0x407906,0x2000,2)
    e.call(0x4bf3c)
print(f"  out(0x407be2) = {e.rds(0x407be2,2)}  (freigabe gates the request)")
