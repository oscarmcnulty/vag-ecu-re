#!/usr/bin/env python3
# Emulate the ANB arm-gate estimator FUN_00090520: map per-wheel decel values -> 0x4066e0,
# find what wheel/braking state reaches arm threshold 0x461.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

FLAGS = [0x400ad0, 0x4016b8, 0x401cac, 0x4010c4]   # per-corner sign flags
VALS  = [0x40138a, 0x401f72, 0x40197e, 0x400d96]   # per-corner decel values (weights)

def run(wheel_vals, flags=(0,0,0,0)):
    e = Emu(); e.call(0x872cc, args=(0x10,))
    try: e.call(0x7e2d8)
    except Exception: pass
    for i in range(4):
        e.wr(FLAGS[i], flags[i] & 0xffffffff, 4)
        e.wr(VALS[i],  wheel_vals[i] & 0xffff, 2)
    try: e.call(0x90520)
    except Exception: pass
    return e.rds(0x4066e0), e.rd(0x4066e0,2)&0xffff

print("=== estimator output vs per-wheel decel value (all 4 equal, flags=0 => all active) ===")
print(f"  {'wheel_val (each)':>16} -> {'0x4066e0(s16)':>13}  {'raw':>6}  {'>=0x461?':>8}")
for wv in (0, 0x20, 0x40, 0x80, 0x100, 0x1ff, 0x2ff, 0x400, 0x600):
    s, raw = run([wv]*4)
    print(f"  {wv:16d} -> {s:13d}  0x{raw:04x}  {'ARM' if raw>=0x461 and raw<0x8000 else '-'}")

print("\n=== how many wheels must be active? (value=0x300 each, vary how many flags=0) ===")
for nact in range(5):
    flags = [0 if i<nact else 0x00800000 for i in range(4)]  # bit23 set => flag=0 (inactive)
    s, raw = run([0x300]*4, flags)
    print(f"  {nact} wheels active -> 0x4066e0=0x{raw:04x}  {'ARM' if 0x461<=raw<0x8000 else '-'}")
