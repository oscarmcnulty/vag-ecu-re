#!/usr/bin/env python3
# Initialize calibration pointers via variant_cfg_select, then probe the accel->pressure path.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

e = Emu()
CALIB_PTRS=[0x40081c,0x400820,0x400824,0x400828,0x40082c]
print("calib ptrs before:", [hex(e.rd(a,4)) for a in CALIB_PTRS])
# variant_cfg_select @0x872cc : try each variant code, see which sets calib pointers into flash calib (0xa0000-0xb8000)
for code in (6,10,0x10,0x11):
    e2=Emu()
    r=e2.call(0x872cc, args=(code,))
    vals=[e2.rd(a,4) for a in CALIB_PTRS]
    inrange=any(0xa0000<=v<0xc0000 for v in vals)
    print(f"  variant_cfg_select({code:#x}) -> {r};  calib ptrs = {[hex(v) for v in vals]}  {'<-- FLASH calib!' if inrange else ''}")
