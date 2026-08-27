#!/usr/bin/env python3
# Validate ANB arming conditions + SPEED INDEPENDENCE + mode-4 executor at low speed.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

# ---- baseline "all conditions met" RAM setup for the ANB arm builder (0x4bf3c) ----
def setup(e, decel=0x600, freigabe=True, master=0x10, quality=0x40, counter=0,
          abe=0, speed=None):
    e.wr(0x405cac, master, 1)                 # master enable (needs ==0x10)
    e.wr(0x40553b, 0x08 if freigabe else 0,1) # freigabe bit3
    e.wr(0x4066e0, decel, 2)                   # ANB decel magnitude (arm gate >=0x461)
    e.wr(0x4055b4, quality, 2)                 # quality (needs >0xc)
    e.wr(0x4055e4, counter, 2)                 # counter (needs <0x37)
    e.wr(0x405abe, abe, 1)                     # substate (needs in {0,4})
    e.wr(0x407c29, 0, 1); e.wr(0x405473, 0, 1)
    e.wr(0x407906, 0x2000, 2)
    e.wr(0x403dac+0x12, 0, 2); e.wr(0x403dac+0x72, 0, 2)
    if speed is not None:                      # inject speed everywhere it might be read
        for a in (0x4022a2, 0x402482, 0x403f9e, 0x40926a):
            e.wr(a, speed & 0xffff, 2)
        # flag_ecd_speed_avail bit6: set if speed>=15km/h(0x78) else clear
        e.wr(0x403da9, 0x40 if speed >= 0x78 else 0, 1)

def armed(decel=0x600, freigabe=True, master=0x10, quality=0x40, counter=0, abe=0, speed=None):
    e = Emu(); e.call(0x872cc, args=(0x10,))
    try: e.call(0x7e2d8)
    except Exception: pass
    for _ in range(8):
        setup(e, decel, freigabe, master, quality, counter, abe, speed)
        e.call(0x4bf3c)
    sw = e.rd(0x407bf0, 4)
    return sw, bool((sw>>28)&1), bool((sw>>31)&1)   # (statusword, active?, idle?)

print("=== ARM CONDITION SWEEP (baseline: decel=0x600, all met) ===")
tests = [
    ("baseline (all met)",       dict()),
    ("decel=0x300 (<0x461)",     dict(decel=0x300)),
    ("decel=0x461 (==thresh)",   dict(decel=0x461)),
    ("decel=0x460 (thresh-1)",   dict(decel=0x460)),
    ("freigabe OFF",             dict(freigabe=False)),
    ("master!=0x10 (0)",         dict(master=0)),
    ("quality=0x0c (not >0xc)",  dict(quality=0x0c)),
    ("quality=0x0d (>0xc)",      dict(quality=0x0d)),
    ("counter=0x37 (not <0x37)", dict(counter=0x37)),
    ("abe=1 (not in {0,4})",     dict(abe=1)),
    ("abe=4 (in set)",           dict(abe=4)),
]
for name, kw in tests:
    sw, act, idle = armed(**kw)
    print(f"  {name:28} -> sw=0x{sw:08x}  {'ARMED' if act else ('idle' if idle else 'other')}")

print("\n=== SPEED INDEPENDENCE (baseline armed config, vary injected speed) ===")
for spd in (0, 0x20, 0x50, 0x77, 0x78, 0x100, 0x400):
    kmh = spd*0.125
    sw, act, idle = armed(speed=spd)
    print(f"  speed=0x{spd:03x} ({kmh:5.1f} km/h) -> {'ARMED' if act else 'not-armed'}  sw=0x{sw:08x}")
