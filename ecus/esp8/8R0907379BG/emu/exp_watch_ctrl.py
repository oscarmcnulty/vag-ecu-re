import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
def load_bases(e):
    for line in open(os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
e=Emu()
e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])   # seg2 at correct VMA
load_bases(e)
e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
writers={}
def on_w(uc,acc,a,sz,val,ud):
    if 0x4069a0<=a<0x406a00:
        pc=uc.reg_read(UC_ARM_REG_PC)
        writers.setdefault(a,[]).append((pc,val))
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
# run each of the 3 task loops once
for entry in (0x219c0,0x21edc,0x223b0):
    e.call(entry, maxinsn=12_000_000)
print("=== writes into COM-init control block 0x4069a0-0x4069ff during task ticks ===")
for a in sorted(writers):
    pcs=set((pc,val) for pc,val in writers[a])
    show=list(pcs)[:4]
    print(f"  [{a:#x}]: "+", ".join(f"pc={pc:#x}<-{val:#x}" for pc,val in show))
if not writers: print("  (no writes to control block)")
