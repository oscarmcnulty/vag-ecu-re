#!/usr/bin/env python3
# (C) mode-4 executor pressure at low vs high speed; (A) 0x4054c4->0x4066e0 scale.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def base():
    e = Emu(); e.call(0x872cc, args=(0x10,))
    try: e.call(0x7e2d8)
    except Exception: pass
    return e

# ---------- (C) mode-4 emergency executor: setpoints vs speed-avail flag ----------
print("=== (C) mode-4 executor ecd_emergency_pressure(0x9c788): pressure vs 15km/h flag ===")
def run_exec(speed_avail, req=0x1500):
    e = base()
    e.wr(0x403da9, 0x40 if speed_avail else 0, 1)   # flag_ecd_speed_avail bit6
    e.wr(0x407c0a, req, 2)                            # anb_request_struct+6 = requested value
    e.wr(0x405aba, 4, 1)                             # ecd_mode = 4
    # point ecd ctrl struct setpoint ptr etc are init by prior calls; just call executor
    for _ in range(3):
        e.wr(0x407c0a, req, 2); e.wr(0x403da9, 0x40 if speed_avail else 0,1)
        try: e.call(0x9c788)
        except Exception as ex: pass
    sp = [e.rds(0x403d94+2*i) for i in range(6)]
    return sp
hi = run_exec(True)
lo = run_exec(False)
print(f"  speed>=15 (flag set):  6 setpoints = {[hex(x&0xffff) for x in hi]}")
print(f"  speed<15  (flag clr):  6 setpoints = {[hex(x&0xffff) for x in lo]}")
print(f"  -> executor {'IGNORES' if hi==lo else 'DEPENDS ON'} the 15km/h flag "
      f"({'pressure produced at low speed' if any(lo) else 'NO pressure at low speed'})")

# ---------- (A) scale: sweep 0x4054c4 request, read 0x4066e0 ----------
print("\n=== (A) anb_decel_from_wheels(0x7c1d4): 0x4054c4 -> 0x4066e0 scale (wheels=0) ===")
def scale(req):
    e = base()
    # zero the wheel structs the fn reads (DAT_7c42c ptr-array -> 4 structs +0x566)
    for a in range(0x402400, 0x402c00, 4): pass
    e.wr(0x4054c4, req & 0xffff, 2)     # external request
    e.wr(0x4085ce, 0, 2)                # second input
    try: e.call(0x7c1d4)
    except Exception: pass
    return e.rds(0x4066e0)
print(f"  {'req(0x4054c4)':>14} -> {'out(0x4066e0)':>14}")
for req in (0, 0x40, 0x80, 0x100, 0x1ff, 0x2ff, -0x100, -0x1ff):
    out = scale(req)
    print(f"  {req:14d} -> {out:14d}")
