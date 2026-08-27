#!/usr/bin/env python3
# The ANB builder (0x4bf3c) is a MULTI-CYCLE latched state machine. Run it repeatedly with
# SUSTAINED valid inputs and watch the status word (0x407bf0) + outputs evolve. Does it ever
# reach an active (non-idle, non-release) state that produces a nonzero brake output?
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

e = Emu()
e.call(0x872cc, args=(0x10,))          # calib
try: e.call(0x7e2d8)                     # ANB init defaults (0x405cac=0x10 etc.)
except Exception: pass

def assert_inputs(e):
    e.wr(0x405cac, 0x10, 1)              # master-enable available
    e.wr(0x40553b, 0x08, 1)             # ANB freigabe bit3 (the request "release")
    e.wr(0x4066e0, 0x0600, 2)           # decel magnitude >= 0x461
    e.wr(0x4055b4, 0x0040, 2)           # quality > 0xc
    e.wr(0x4055e4, 0x0000, 2)           # counter < 0x37
    e.wr(0x405abe, 0x00, 1)             # status in {0,4}
    e.wr(0x407c29, 0x00, 1)             # no fault (DAT_4c314 >= 0)
    e.wr(0x405473, 0x00, 1)             # plausibility (DAT_4c30c)
    e.wr(0x407906, 0x2000, 2)           # jerk-shaped decel input
    e.wr(0x403dac+0x12, 0x00, 2)        # keep <0x189 path
    e.wr(0x403dac+0x72, 0x00, 2)        # clear inhibit bit9

print("cyc | statusword  bit31 bit30 | out_be2 out_be6 arb_bb0 | notes")
for i in range(200):
    assert_inputs(e)
    e.call(0x4bf3c)
    sw = e.rd(0x407bf0, 4)
    be2 = e.rds(0x407be2, 2); be6 = e.rds(0x407be6, 2); bb0 = e.rds(0x407bb0, 2)
    if i < 8 or i % 25 == 0 or (be2 or be6 or bb0):
        b31 = (sw>>31)&1; b30=(sw>>30)&1
        note = "ACTIVE-OUTPUT" if (be2 or be6 or bb0) else ("reset" if b31 else "")
        print(f"{i:3d} | 0x{sw:08x}   {b31}     {b30}   | {be2:6d} {be6:6d} {bb0:6d} | {note}")
        if be2 or be6 or bb0: 
            print("  -> nonzero ANB output reached at cycle", i); break
else:
    print("\n200 cycles: ANB output stayed ZERO. status word:", hex(e.rd(0x407bf0,4)))
    # dump the +0x2f state byte and key counters to see where it's stuck
    print("  state_byte(0x407bf3)=%#x  psVar14[7](0x407bd2)=%d  psVar14[9](0x407bd6)=%d" % (
        e.rd(0x407bf3,1), e.rds(0x407bd2,2), e.rds(0x407bd6,2)))
