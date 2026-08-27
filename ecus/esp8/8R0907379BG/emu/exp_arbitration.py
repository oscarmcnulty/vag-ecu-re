#!/usr/bin/env python3
# Experiment: drive the real decel arbitration with a synthetic type-4 (ANB) request
# and confirm it sets ecd_mode=4, then check what higher requests do (MAX-wins).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

ECD_MODE   = 0x405aba
ARB_OUT    = 0x405a7c
STATUS     = 0x405dcd        # per-type status bytes: [0]=type5,[1]=type2,[2]=type4,[6]=type1
ARR        = 0x405a90        # decel_req_array (preprocessed values)
# raw source enable bytes (bit7):
EN = {1:0x403fac+7, 2:0x403a36+1, 4:0x407bb4+7, 5:None}
# assemble value slots (per decel_req_assemble_types map):
VAL = {1:0x405a90, 2:0x405a94, 4:0x405aa0, 5:0x405aac}
# status index per type: type1->[6], type2->[1], type4->[2], type5->[0]
SIDX = {1:6, 2:1, 4:2, 5:0}

def setup_type(e, t, value):
    e.wr(STATUS + SIDX[t], 0x10, 1)          # status == 0x10 (active)
    if EN[t] is not None: e.wr(EN[t], 0x80, 1)  # enable bit 0x80
    e.wr(VAL[t], value, 2)                    # the (preprocessed) request value
    # also set the raw secondary + aux buffers the assemble reads
    raw = {1:0x403fac,2:0x403a40,4:0x407bb4,5:0x403d76}[t]
    e.wr(raw, value, 2)

def run_arbitration(sources):   # sources: {type: value}
    e = Emu()
    for t,v in sources.items(): setup_type(e, t, v)
    r = e.call(0x9b7b4)          # decel_ctrl_top -> assemble + arbitrate
    mode = e.rd(ECD_MODE, 1)
    prim = e.rds(ARB_OUT+0x10, 2)
    return r, mode, prim

print("=== single type-4 (ANB) request, value 0x1000 ===")
r,mode,prim = run_arbitration({4:0x1000})
print(f"  decel_ctrl_top -> {r};  ecd_mode=0x{mode:x} (expect 4);  primary_max=0x{prim&0xffff:x}")

print("=== type-2 (comfort) 0x0800 vs type-4 (ANB) 0x1500  (MAX should win = type4) ===")
r,mode,prim = run_arbitration({2:0x0800, 4:0x1500})
print(f"  ecd_mode=0x{mode:x} (expect 4, the larger);  primary_max=0x{prim&0xffff:x}")

print("=== type-2 (comfort) 0x1500 vs type-4 (ANB) 0x0800  (MAX should win = type2) ===")
r,mode,prim = run_arbitration({2:0x1500, 4:0x0800})
print(f"  ecd_mode=0x{mode:x} (expect 2, the larger);  primary_max=0x{prim&0xffff:x}")

print("=== only type-1 request 0x0900 ===")
r,mode,prim = run_arbitration({1:0x0900})
print(f"  ecd_mode=0x{mode:x} (expect 1);  primary_max=0x{prim&0xffff:x}")
