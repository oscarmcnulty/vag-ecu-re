#!/usr/bin/env python3
# Diagnostic emulation of the COM config-init bump allocator FUN_0006b936.
# Goal: discover what .data config it needs (via read logging), then try seeding the
# object-table base from the flash candidates and see if buffer assignments materialize.
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn import UC_HOOK_MEM_READ
from unicorn.arm_const import *

FW = open(os.path.join(os.path.dirname(__file__),'..','firmware','8R0907379BG_0030.bin'),'rb').read()
def fu32(o): return struct.unpack('>I',FW[o:o+4])[0]

OBJ_BASE_PTR = 0x4069b4   # *this = object table base
MSG_CNT_PTR  = 0x4069fc   # *this = message count (DAT_0006bbe8 target)
BUMP_PTR     = 0x4069b0   # *this = bump allocator current pointer
BUMP_LIMIT_F = 0xbda34    # *DAT_0006bbf8 (flash) = pool end

def run(seed_obj=None, seed_cnt=None, bump_start=0x500000, label=""):
    e = Emu()
    reads=[]
    def on_read(uc,access,addr,size,value,ud):
        if 0x400000<=addr<0x600000:
            reads.append((uc.reg_read(UC_ARM_REG_PC),addr,size))
    e.uc.hook_add(UC_HOOK_MEM_READ, on_read)
    # seed roots
    if seed_obj is not None: e.wr(OBJ_BASE_PTR, seed_obj)
    if seed_cnt is not None: e.wr(MSG_CNT_PTR, seed_cnt)
    e.wr(BUMP_PTR, bump_start)
    # run FUN_0006b936 (ARM)
    e.writes=[]
    res = e.call(0x6b936, thumb=True, maxinsn=3000000)
    ramw=[(pc,a,s,v) for (pc,a,s,v) in e.writes if 0x400000<=a<0x600000]
    # buffer assignments = writes to descriptor+8 with a bump-pool value
    allocs=[(a,v) for (pc,a,s,v) in ramw if 0x500000<=v<0x520000]
    print(f"--- {label}: res={res}  RAMwrites={len(ramw)} allocs={len(allocs)} bump_end={hex(e.rd(BUMP_PTR))}")
    for a,v in allocs[:20]:
        print(f"     alloc: [{hex(a)}] <- buf {hex(v)}")
    # show distinct uninitialized-read PCs reading obj table area (first run diagnostic)
    if seed_obj is None:
        seen=set()
        for pc,addr,size in reads:
            key=(pc,addr&~0xf)
            if key in seen: continue
            seen.add(key)
        print(f"     (diagnostic) distinct RAM reads: {len(seen)}; sample obj-base reads:",
              [hex(a) for (pc,a,sz) in reads if OBJ_BASE_PTR-8<=a<=OBJ_BASE_PTR+8][:6])
    return e

print("=== candidate flash object tables ===")
for c in (0xb041c,0xb059c,0xb038c):
    print(f"  0x{c:x}: rec0 sc={FW[c+6]} +8ptr={hex(fu32(c+8))} +f={hex(FW[c+0xf])}")
print("\n=== run 0: RAM zeroed (diagnostic) ===")
run(label="zeroed")
print("\n=== run 1: seed obj_base=0xb041c cnt=214 ===")
run(seed_obj=0xb041c, seed_cnt=214, label="obj=0xb041c")
print("\n=== run 2: seed obj_base=0xb059c cnt=214 ===")
run(seed_obj=0xb059c, seed_cnt=214, label="obj=0xb059c")
