import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK
from unicorn.arm_const import UC_ARM_REG_PC
def load_bases(e):
    for line in open(os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
e=Emu(); e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011]); load_bases(e)
e.wr(0x4069b4,0x40a1a8,4)
# task-list call targets (from 219c0)
TASKFNS=[0x21896,0x8760a,0x9d2d6,0xa1060,0x53e3c,0x9f32c,0x9c0c4,0x9ed00,0x77d42,0x33338,0x9cff6,
0xa0614,0x6b00,0x827ac,0x82732,0x6b550,0x3d13c,0xa4ec,0xa168,0x9e28,0x9be0,0xa314,0x3d260,
0x3aba0,0x9543c,0x50460,0x29b70,0x962e8,0xa1a28,0x37b54,0x33e10,0x310ec,0x3714c,0x5216c,
0x507f4,0xa0654,0x93600,0x93674,0x9b910,0x83d14,0x8c9c8,0x976e8,0x14dec,0x40268,0x9fb54,
0x90db2,0x317c,0x1750,0x6d81a,0x9f276,0x91168,0x7630c,0x8e0aa]
reached=set()
tset=set(TASKFNS)|{0x8df52,0x8e0aa}
def on_blk(uc,addr,size,ud):
    if addr in tset: reached.add(addr)
e.uc.hook_add(UC_HOOK_BLOCK,on_blk)
res=e.call(0x219c0, maxinsn=15_000_000)
print("219c0 ->",res[0])
# which task functions were reached, in order of the list
order=[hex(f) for f in TASKFNS if f in reached]
print(f"reached {len(order)}/{len(TASKFNS)} task fns")
print("reached list:", order)
print("dispatcher 0x8e0aa reached:", 0x8e0aa in reached, "| 0x8df52:", 0x8df52 in reached)
# find first task fn NOT reached (divergence point)
for f in TASKFNS:
    if f not in reached:
        print(f"first UNreached task fn: {f:#x}"); break
