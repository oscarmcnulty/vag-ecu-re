import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE
OBJ_LO,OBJ_HI=0x40a1a8,0x40a1a8+0x2700
def load_bases(e):
    for line in open(os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
e=Emu(); load_bases(e)
# force init entry gates (from FUN_0008df52 gate logic)
e.wr(0x4092e0,0,1)   # PTR_DAT_0008e0b4 busy-latch clear
e.wr(0x406aa0,0,1)   # PTR_DAT_0008e0b8 done clear
e.wr(0x4069e4,1,1)   # cVar1 = DAT_0008e0bc[2] = 1 (proceed)
e.wr(0x4069e7,0,1)   # DAT_0008e0bc[5] = 0
e.wr(0x406aa4,0,4)   # phase = 0
e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
ow={}
def on_w(uc,acc,a,sz,val,ud):
    if OBJ_LO<=a<OBJ_HI: ow[a]=val
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
for it in range(30000):
    e.call(0x8e0aa, maxinsn=300000)
    if it%3000==0:
        print(f" iter{it}: objcells={len(ow)} cmd={e.rd(0x4069a8,1)&0xff:#x} phase={e.rd(0x406aa4,4)} gate={e.rd(0x4069e4,1)&0xff:#x}")
    # if init signalled done (0x406aa0 set), stop
    if e.rd(0x406aa0,1)&0xff: print(f"  init done flag set at iter {it}"); break
print("final objcells=",len(ow))
for a in sorted(ow)[:24]: print(f"   [{a:#x}]={ow[a]:#x}")
