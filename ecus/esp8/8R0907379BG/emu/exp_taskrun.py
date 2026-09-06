import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
OBJ_LO,OBJ_HI=0x40a1a8,0x40a1a8+0x2700
def load_bases(e):
    for line in open(os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
e=Emu(); load_bases(e)
ow={}
def on_w(uc,acc,a,sz,val,ud):
    if OBJ_LO<=a<OBJ_HI: ow[a]=val
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
# try the COM-init dispatcher driver path first: FUN_0008e0aa a few thousand times
for it in range(8000):
    e.call(0x8e0aa, maxinsn=100000)
    if it%2000==0: print(f" e0aa iter {it}: objcells={len(ow)} cmd={e.rd(0x4069a8,1)&0xff:#x} phase={e.rd(0x406aa4,4)}")
print("after e0aa loop objcells=",len(ow))
# now try a full task tick
res=e.call(0x219c0, maxinsn=8_000_000)
print("task 219c0 ->",res[0], "objcells=",len(ow), "PC_end=",hex(res[-1]) if res[0]=='ERR' else '')
for a in sorted(ow)[:20]: print(f"   [{a:#x}]={ow[a]:#x}")
