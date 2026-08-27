#!/usr/bin/env python3
# ADVERSARIAL: can anb_decel_request_build (0x4bf3c) be driven to emit a type-4 ANB request
# (enable bit + nonzero decel) using ONLY inputs an external ACC_10 frame could plausibly set,
# vs. requiring ESP-internal AEB gate state (0x405cac==0x10, 0x405abe, 0x40553b, status_flags)?
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

BUILD=0x4bf3c
CALIB=0x40081c
DECEL_IN=0x407906      # jerk-shaped decel input
DECEL_MAG=0x4066e0     # magnitude compared to 0x461
G_405cac=0x405cac      # must==0x10 (delayed ANB master-enable)
G_405abe=0x405abe      # must in {0,4}
G_405473=0x405473      # (x^0x80)>>7 enable byte
G_40553b=0x40553b      # bit3 enable
G_4055b4=0x4055b4      # >0xc
G_4055e4=0x4055e4      # counter <0x37
STRUCT=0x407bc4        # anb_request_struct (psVar14)
STATUSFLAGS=0x407bc4+0x2c  # psVar14+0x16 as short => byte offset 0x2c; the u32 status word
ENABLE_BYTE=0x407bf3   # psVar14+0x2f state_byte (bit0x80 = ANB enable)
EXEC_VAL=0x407c0a      # value broadcast to setpoints by mode-4 executor

def run(label, can_decel=0, set_internal=False, iters=60):
    e=Emu()
    e.wr(CALIB, 0xb0510, 4)          # point calib base at a real variant calib block
    if can_decel:
        e.wr(DECEL_IN, can_decel, 2)
        e.wr(DECEL_MAG, can_decel, 2)
    if set_internal:                 # grant the ESP-internal AEB gate state
        e.wr(G_405cac, 0x10, 1)
        e.wr(G_405abe, 0x00, 1)
        e.wr(G_405473, 0x00, 1)      # (0^0x80)>>7 = 1 -> enable
        e.wr(G_40553b, 0x08, 1)      # bit3
        e.wr(G_4055b4, 0x40, 1)      # >0xc
        e.wr(G_4055e4, 0x00, 2)
        # seed status_flags activation bits (bit0x1e ANB-active region)
        e.wr(STRUCT+0x2c, 0x60000000, 4)
    last=None
    for i in range(iters):
        r=e.call(BUILD)
        if isinstance(r,tuple) and r[0]=='ERR':
            print(f"[{label}] iter{i} EMU-ERR {r[1]} pc=0x{r[2]:x}"); break
        last=r
    en=e.rd(ENABLE_BYTE,1)
    sf=e.rd(STRUCT+0x2c,4)
    val=e.rds(EXEC_VAL,2)
    print(f"[{label}] call={last} enable_byte=0x{en:02x} (bit0x80={'SET' if en&0x80 else 'clear'}) "
          f"status_flags=0x{sf:08x} exec_val(0x407c0a)={val}")
    return en&0x80, val

print("=== A: CAN-only (decel=0x600, Anlauf can't set internal gates) ===")
run("CAN-only", can_decel=0x600, set_internal=False)
print("=== B: CAN decel + ALL ESP-internal AEB gates granted ===")
run("CAN+internal", can_decel=0x600, set_internal=True)
print("=== C: nothing (baseline) ===")
run("baseline", can_decel=0, set_internal=False)
