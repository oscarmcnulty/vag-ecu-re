#!/usr/bin/env python3
# Phase 2 full-init capture: run the COM-init dispatcher's case functions in sequence in ONE
# emulation context (state carries between phases), seed the recovered roots, and capture every
# write into the object-table region 0x40a1a8-0x40b000 to see if the per-message records / buffers
# materialize (they are loop-built, not simple-stub-installed).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

# FUN_0008df52 dispatcher case handlers, in listed order (0xd3..0xfe)
CASES = [0x814c2,0x89f90,0x8efbc,0x9a66a,0x892a0,0x6bb22,0x9e3f4,0x8e298,0x7a072,0x9db84,
         0xa0d48,0x9e64c,0x9edd8,0xa0f98,0x89db0,0x9eb44,0x9fd9c,0x9e820,0x931e8,0x8dac0,
         0x8db80,0x6b936]  # + the objtable-init-phase + bump allocator last
mode={}
for ln in open(os.path.join(os.path.dirname(__file__),'..','analysis','function_entries.txt')):
    ln=ln.strip()
    if ln.startswith('#') or not ln: continue
    p=ln.split(','); mode[int(p[0],16)] = (len(p)>1 and p[1].upper()=='T')

e=Emu()
# seed the recovered roots
e.wr(0x4069b4,0x40a1a8); e.wr(0x4069b0,0x40a1a8); e.wr(0x4069fc,0xd6)  # base, bump, msgcount
objwrites=[]
def on_w(uc,access,a,size,val,ud):
    if 0x40a1a8<=a<0x40b000:
        objwrites.append((uc.reg_read(UC_ARM_REG_PC),a,val & ((1<<(size*8))-1),size))
e.uc.hook_add(UC_HOOK_MEM_WRITE, on_w)

ran=0; NCALLS=3  # call each phase machine a few times (they progress a state byte per call)
for _ in range(NCALLS):
    for fn in CASES:
        thumb=mode.get(fn,(fn&1)==0)
        e.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x400)
        e.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
        try:
            e.uc.emu_start(fn|(1 if thumb else 0), RET_MAGIC, count=300000); ran+=1
        except Exception: pass

# report
distinct=sorted(set((a,v) for pc,a,v,sz in objwrites))
print(f"ran {ran} phase calls; {len(objwrites)} writes into 0x40a1a8-0x40b000, {len(distinct)} distinct (addr,val)")
print("=== object-table region writes (addr -> val), first 40 ===")
for a,v in distinct[:40]:
    tag=''
    if 0x400000<=v<0x40ffff: tag=' <RAM ptr>'
    elif 0<v<0x134000: tag=' <flash ptr>'
    print(f"  0x{a:08x} -> 0x{v:08x}{tag}")
# specifically: did EPB handle 0x25b's record slot (0x40a1a8 + 0x25b*0x10 = 0x40a1a8+0x25b0=0x40c758) get written? (out of range -> table smaller)
# check how far the table populated
maxaddr=max((a for a,v in distinct), default=0x40a1a8)
print(f"\nobject-table populated up to 0x{maxaddr:x} (span 0x{maxaddr-0x40a1a8:x} = {(maxaddr-0x40a1a8)//0x10} records of 0x10)")
