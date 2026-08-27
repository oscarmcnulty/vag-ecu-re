#!/usr/bin/env python3
# What actually drives estimator 0x4066e0 to >=0x461? 0x4054c4 (gate) vs 0x4085ce (input) vs wheels.
# And can it reach threshold at STANDSTILL (wheels=0)?
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def base():
    e = Emu(); e.call(0x872cc, args=(0x10,))
    try: e.call(0x7e2d8)
    except Exception: pass
    # give the wheel pointer array (0x402590) 4 valid struct pointers -> zeroed RAM (standstill)
    for i in range(4): e.wr(0x402590+4*i, 0x401000+0x600*i, 4)
    return e

def run(gate, inp, prev=0, wheel=0, cycles=6):
    e = base()
    for i in range(4):  # wheel decel value at +0x566 in each struct
        e.wr(0x401000+0x600*i+0x566, wheel & 0xffff, 2)
    e.wr(0x4066e0, prev & 0xffff, 2); e.wr(0x4065e4, prev & 0xffff, 2)
    out=[]
    for _ in range(cycles):
        e.wr(0x4054c4, gate & 0xffff, 2)     # gate input
        e.wr(0x4085ce, inp & 0xffff, 2)      # estimator input
        try: e.call(0x7c1d4)
        except Exception: pass
        out.append(e.rds(0x4066e0))
    return out

print("=== can estimator 0x4066e0 reach arm threshold 0x461 (=1121)? ===")
print("gate=0x4054c4  inp=0x4085ce  wheel=0x402x+0x566  prev  -> 0x4066e0 over 6 cycles")
scenarios = [
    ("standstill, max gate+inp, no wheel", 0x1ff, 0x1ff, 0, 0),
    ("standstill, gate only",               0x1ff, 0,     0, 0),
    ("standstill, inp only",                0,     0x1ff, 0, 0),
    ("standstill, seeded prev=0x400",       0x1ff, 0x1ff, 0x400, 0),
    ("MOVING+decel wheel=0x100",            0x1ff, 0x1ff, 0, 0x100),
    ("MOVING+decel wheel=0x1ff, prev0x400", 0x1ff, 0x1ff, 0x400, 0x1ff),
]
for name, g, i, p, w in scenarios:
    o = run(g, i, p, w)
    hit = "ARMS (>=0x461)" if any(v>=0x461 for v in o) else "no arm"
    print(f"  {name:38} -> {[hex(v&0xffff) for v in o]}  [{hit}]")
