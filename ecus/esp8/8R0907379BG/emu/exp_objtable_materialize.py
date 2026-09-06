#!/usr/bin/env python3
# Attempt to materialize the COM object table at 0x40a1a8 by applying the recovered RAM bases
# and running the COM-init builder chain, watching writes into the object-table region.
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC

OBJ_LO, OBJ_HI = 0x40a1a8, 0x40a1a8+0x2800   # cover handles up to ~0x280
def load_bases(e):
    p=os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")
    nb=0
    for line in open(p):
        line=line.strip()
        if not line or line.startswith('#') or line.startswith('ram'): continue
        a,v=line.split(',')[:2]
        try: e.wr(int(a,16), int(v,16), 4); nb+=1
        except Exception: pass
    return nb

# candidate builder / com-init entries (seg1)
CANDS=[('FUN_0008db80',0x8db80),('FUN_0008df52_dispatch',0x8df52),('FUN_000892a0_phase',0x892a0),
       ('FUN_0008e298_populate',0x8e298),('FUN_00089f90_alloc',0x89f90),('FUN_0006b936_bump',0x6b936)]

for name,addr in CANDS:
    e=Emu()
    nb=load_bases(e)
    e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
    wr=[]
    def on_w(uc,acc,a,sz,val,ud):
        if OBJ_LO<=a<OBJ_HI: wr.append((a,val))
    h=e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
    res=e.call(addr, maxinsn=3_000_000)
    nwrites=len(wr); span=(min(w[0] for w in wr),max(w[0] for w in wr)) if wr else (0,0)
    print(f"{name:26s} {addr:#x}: res={res[0]} objtable-writes={nwrites} span={hex(span[0])}..{hex(span[1])}")
    if wr:
        # show first distinct addresses written
        seen=[]
        for a,v in wr:
            if a not in [s[0] for s in seen]: seen.append((a,v))
            if len(seen)>=12: break
        for a,v in seen: print(f"     [{a:#x}] <- {v:#x}")
