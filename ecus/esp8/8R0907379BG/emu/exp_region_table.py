#!/usr/bin/env python3
# Materialize the Dcm memory-region allowlist at RAM 0x401eee by running full startup and
# capturing writes into the 12x8-byte table window. Then decode it with FUN_000dc958's logic.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP

TBL_LO, TBL_HI = 0x401ee0, 0x401f60   # a bit wider than the 12x8 table (0x401eee..0x401f4e)

def load_bases(e):
    p=os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")
    nb=0
    if os.path.exists(p):
        for line in open(p):
            line=line.strip()
            if not line or line[0] in '#r': continue
            try:
                a,v=line.split(',')[:2]; e.wr(int(a,16),int(v,16),4); nb+=1
            except Exception: pass
    return nb

e=Emu()
# overlay seg2 at correct VMA (file+3) so Dcm init code executes
e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])
nb=load_bases(e)

writes={}   # addr -> (pc,val)
pcs=set()
def on_w(uc,acc,a,sz,val,ud):
    if TBL_LO<=a<TBL_HI:
        pc=uc.reg_read(UC_ARM_REG_PC)
        writes[a]=(pc,val & ((1<<(sz*8))-1), sz); pcs.add(pc)
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)

e.uc.reg_write(UC_ARM_REG_SP, 0x300000+0x80000-0x200)
import unicorn
START=0x8f440   # _start (per exp_startup.py)
try:
    e.uc.emu_start(START, RET_MAGIC, count=120_000_000)
    print("startup ended normally")
except unicorn.UcError as ex:
    print("startup stopped:", ex, "PC=", hex(e.uc.reg_read(UC_ARM_REG_PC)))

print(f"loaded {nb} ram bases; {len(writes)} cells written in table window by {len(pcs)} PCs")
print("writer PCs:", sorted(hex(p) for p in pcs))
print("\n== table window 0x401ee0..0x401f60 (final RAM) ==")
def be16(a): return e.rd(a,2)
raw=e.uc.mem_read(0x401ee0,0x80)
for r in range(0,0x80,16):
    print(f"  {0x401ee0+r:08x}  "+" ".join(f"{raw[r+k]:02x}" for k in range(16)))

print("\n== decode 12 entries @0x401eee (FUN_000dc958 logic) ==")
base=0x401eee
for i in range(12):
    ent=base+i*8
    hw0=be16(ent); hw4=be16(ent+4)
    desc=(hw0<<16)|hw4; nib=(desc>>4)&0xf
    gran=0xFFFFFC00 if i<6 else 0xFFFF8000
    if nib:
        mask=(gran<<(nib-1))&0xFFFFFFFF; region=mask&desc
        print(f"  [{i:2d}] desc={desc:#010x} nib={nib} mask={mask:#010x} region_base={region:#010x} size~{(~mask)&0xffffffff:#x}")
    else:
        print(f"  [{i:2d}] desc={desc:#010x} nib=0 (empty/disabled)")
