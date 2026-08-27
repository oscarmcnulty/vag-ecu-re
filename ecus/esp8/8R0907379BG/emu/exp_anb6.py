#!/usr/bin/env python3
# Map the ANB activation truth table: statusword state (idle/reset bit31 vs active bit28)
# vs freigabe (0x40553b bit3) x decel demand (0x4066e0 </>= 0x461).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def state(freigabe, decel, cycles=8):
    e = Emu(); e.call(0x872cc, args=(0x10,))
    try: e.call(0x7e2d8)
    except Exception: pass
    for _ in range(cycles):
        e.wr(0x405cac,0x10,1); e.wr(0x40553b,0x08 if freigabe else 0,1)
        e.wr(0x4066e0,decel,2); e.wr(0x4055b4,0x40,2); e.wr(0x4055e4,0,2)
        e.wr(0x405abe,0,1); e.wr(0x407c29,0,1); e.wr(0x405473,0,1)
        e.wr(0x407906,0x2000,2); e.wr(0x403dac+0x12,0,2); e.wr(0x403dac+0x72,0,2)
        e.call(0x4bf3c)
    sw=e.rd(0x407bf0,4)
    top = "IDLE/reset(bit31)" if (sw>>31)&1 else ("ACTIVE(bit28)" if (sw>>28)&1 else f"other")
    return sw, top

print("freigabe | decel  | statusword | top state")
for fg in (True, False):
    for dm in (0x600, 0x300):
        sw, top = state(fg, dm)
        print(f"   {int(fg)}     | 0x{dm:04x} | 0x{sw:08x} | {top}")
print("\nInterpretation: bit31 (idle/reset) = ANB NOT armed; bit28 (active) = ANB request accepted,")
print("state machine progressing. The active state requires BOTH freigabe AND decel >= 0x461.")
