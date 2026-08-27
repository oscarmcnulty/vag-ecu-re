#!/usr/bin/env python3
# Does ANB LATCH and maintain a hold once armed then decel drops (car stopped)?
# Sequence: arm (decel>=0x461) for N cycles, then decel->0 (stopped), check latch/active persists.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def cyc(e, decel, freigabe=True, speed=0):
    e.wr(0x405cac,0x10,1); e.wr(0x40553b,0x08 if freigabe else 0,1)
    e.wr(0x4066e0,decel,2); e.wr(0x4055b4,0x40,2); e.wr(0x4055e4,0,2)
    e.wr(0x405abe,0,1); e.wr(0x407c29,0,1); e.wr(0x405473,0,1)
    e.wr(0x407906,0x2000,2); e.wr(0x403dac+0x12,0,2); e.wr(0x403dac+0x72,0,2)
    for a in (0x4022a2,0x402482,0x403f9e): e.wr(a, speed&0xffff, 2)
    e.wr(0x403da9, 0x40 if speed>=0x78 else 0,1)
    e.call(0x4bf3c)

e = Emu(); e.call(0x872cc, args=(0x10,))
try: e.call(0x7e2d8)
except Exception: pass

print("phase                     | statusword | active(b28) latch(b2ofword) idle(b31)")
def show(tag):
    sw=e.rd(0x407bf0,4); lat=e.rd(0x407bf0,1)  # byte2 anb_active_latch=0x407bf2
    b2=e.rd(0x407bf2,1)
    print(f"  {tag:24} | 0x{sw:08x} | act={bool((sw>>28)&1)} latch(0x407bf2)=0x{b2:02x} idle={bool((sw>>31)&1)}")

# 1) arm while decelerating (speed high->dropping, decel above threshold)
for i,spd in enumerate((0x200,0x150,0x100,0x80,0x40)):
    cyc(e, 0x600, speed=spd)
show("after arming (decel)")
# 2) car reaches standstill: speed=0, decel demand drops to 0 (no more measured decel)
for _ in range(6):
    cyc(e, 0x000, speed=0)
show("standstill, decel=0")
# 3) keep holding at standstill several more cycles
for _ in range(10):
    cyc(e, 0x000, speed=0)
show("standstill +10 cycles")
