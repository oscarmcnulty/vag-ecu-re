#!/usr/bin/env python3
# ANB builder produces nonzero output with sustained inputs. Does it propagate to the type-4
# arbitration source (0x407bb4), the enable (0x407bbb), and the executor input (0x407c0a),
# and does mode-4 then win and apply pressure? Run builder -> full decel chain.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def anb_inputs(e):
    for _ in range(3):  # sustain a few cycles
        e.wr(0x405cac,0x10,1); e.wr(0x40553b,0x08,1); e.wr(0x4066e0,0x0600,2)
        e.wr(0x4055b4,0x0040,2); e.wr(0x4055e4,0,2); e.wr(0x405abe,0,1)
        e.wr(0x407c29,0,1); e.wr(0x405473,0,1); e.wr(0x407906,0x2000,2)
        e.wr(0x403dac+0x12,0,2); e.wr(0x403dac+0x72,0,2)
        e.call(0x4bf3c)

e = Emu()
e.call(0x872cc, args=(0x10,))
try: e.call(0x7e2d8)
except Exception: pass
anb_inputs(e)

print("=== ANB struct after activation ===")
for off in range(0x407bac, 0x407c0c, 2):
    v = e.rds(off,2)
    tag=""
    if off==0x407bb4: tag=" <- type4 arb source (preprocess reads)"
    if off==0x407be2: tag=" <- builder output psVar14[0xf]"
    if off==0x407c0a: tag=" <- executor input (ecd_emergency_pressure)"
    if v: print(f"  0x{off:08x} = {v}{tag}")
print(f"  enable byte 0x407bbb = {e.rd(0x407bbb,1):#x} (bit0x80={'SET' if e.rd(0x407bbb,1)&0x80 else 'clear'})")
print(f"  type4 status 0x405dcd[2] = {e.rd(0x405dcd+2,1):#x}")

# Now run the arbitration chain and see if mode-4 wins + executor applies pressure
print("\n=== downstream: decel_ctrl_top -> state machine -> setpoints ===")
e.call(0x9b7b4)
print(f"  ecd_mode(0x405aba) = {e.rd(0x405aba,1):#x}  (4 = ANB/mode-4)")
e.call(0x633fc)
sp=[e.rds(0x403d94+2*i,2) for i in range(6)]
print(f"  setpoints after state machine = {sp}")
