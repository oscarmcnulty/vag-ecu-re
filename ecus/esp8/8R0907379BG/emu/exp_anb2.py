#!/usr/bin/env python3
# Can anb_decel_request_build (0x4bf3c) be driven to OPEN the type-4 enable with properly
# initialized RAM? Prior red-team ran from zeroed RAM (0x405cac=0, not its 0x10 init-default).
# Init the ANB defaults, grant the known gates, run the builder, inspect the type-4 outputs.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

def probe(label, extra=None):
    e = Emu()
    e.call(0x872cc, args=(0x10,))          # variant_cfg_select -> calib pointers
    # ANB subsystem init defaults (sets 0x405cac=0x10 etc.)
    try: e.call(0x7e2d8)
    except Exception as ex: pass
    # Known gate inputs from the builder's decompile:
    e.wr(0x405cac, 0x10, 1)                 # master-enable "available"
    e.wr(0x4066e0, 0x0500, 2)               # decel magnitude >= 0x461
    e.wr(0x405abe, 0x00, 1)                 # status in {0,4}
    e.wr(0x40553b, 0x08, 1)                 # freigabe bit3
    e.wr(0x4055b4, 0x20, 2)                 # quality > 0xc
    e.wr(0x4055e4, 0x00, 2)                 # counter < 0x37
    e.wr(0x407906, 0x2000, 2)               # jerk-shaped decel input
    e.wr(0x407c29, 0x00, 1)                 # DAT_4c314 >= 0 (no fault)
    if extra: extra(e)
    e.call(0x4bf3c)                          # anb_decel_request_build
    en   = e.rd(0x407bbb,1) & 0x80          # type-4 enable bit (assemble gate)
    stat = e.rd(0x405dcd+2,1)               # type-4 status byte (must be 0x10)
    val  = e.rds(0x407c0a,2)                # executor input value
    src  = e.rds(0x407bb4,2)                # type-4 source value
    sw   = e.rd(0x407bf0,4)                 # status word psVar14+0x16
    print(f"  [{label}] enable(0x407bbb&0x80)={en:#x}  status(0x405dcd[2])={stat:#x}  "
          f"exec_val(0x407c0a)={val}  src(0x407bb4)={src}  statusword={sw:#010x}")
    return en, stat, val

print("=== ANB builder reachability with initialized RAM + granted gates ===")
probe("gates granted")
# also try asserting more status bits in the builder's status word
probe("gates + statusword primed", lambda e: e.wr(0x407bf0, 0xC0000000, 4))
probe("gates + all-ANB-context", lambda e: [e.wr(a,v,s) for a,v,s in
      [(0x405cbf,0x10,1),(0x407f90,0x10,1),(0x40691a,0xff,1),(0x406857,0x00,1),(0x4068fd,0x00,1)]])
