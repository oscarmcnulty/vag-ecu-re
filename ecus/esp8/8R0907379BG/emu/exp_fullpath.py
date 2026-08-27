#!/usr/bin/env python3
# Full brake control path under emulation: type-4 (ANB) request -> arbitrate -> state machine
# -> actuation pipeline. Log ecd_mode, the 6 setpoints, all writes into the pressure region,
# and ANY unmapped (peripheral/MMIO) access -> discover the actuator boundary.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

ECD_MODE=0x405aba; SETP=0x403d94; STATUS=0x405dcd
def setup_type4(e, value):
    e.wr(STATUS+2, 0x10, 1)            # type4 status active
    e.wr(0x407bb4+7, 0x80, 1)          # type4 enable
    e.wr(0x405aa0, value, 2)           # type4 array slot value
    e.wr(0x407bb4, value, 2)           # type4 raw source
    e.wr(0x407c0a, value, 2)           # ANB request value (executor input)

e = Emu()
setup_type4(e, 0x1000)
print("1) decel_ctrl_top:", e.call(0x9b7b4), " ecd_mode=0x%x"%e.rd(ECD_MODE,1))

# state machine needs an active flag + substate; run and observe
r = e.call(0x633fc)     # ecd_state_machine
print("2) ecd_state_machine:", r, " ecd_mode=0x%x"%e.rd(ECD_MODE,1))
print("   setpoints after SM:", [hex(e.rds(SETP+2*i,2)&0xffff) for i in range(6)])

# actuation pipeline (param1 = ecd_ctrl_struct 0x403a14)
e.wr(0x403a14, 6, 2)                 # slot_count
e.wr(0x403a14+8, SETP, 4)            # setpoint ptr
allw_before=len(e.writes)
r = e.call(0x9f190, args=(0x403a14,))
print("3) ecd_actuation_pipeline:", r)

# report writes into the pressure/actuation region + MMIO
peri = {a:v for a,v in e.mmio.items()}
print("\n=== unmapped/peripheral accesses during full path ===")
if peri:
    for a,v in sorted(peri.items()): print(f"   0x{a:08x}: reads={v['r']} writes={v['w']} wvals={[hex(x) for x in v['wvals'][:4]]}")
else:
    print("   (none — actuation stayed within mapped flash+RAM; valve driver not reached from this entry)")
print("\n=== distinct write target regions (last run) ===")
import collections
regs=collections.Counter((a>>12)<<12 for _,a,_,_ in e.writes)
for base,c in sorted(regs.items()): print(f"   0x{base:08x}: {c} writes")
