import sys, os, struct
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
def map_seg2(e):
    # place seg2 (file 0xbb045..) at its true VMA = file+3 (0xbb048..)
    fw=e.fw
    e.uc.mem_write(0xbb048, fw[0xbb045:0x134011])
e=Emu(); map_seg2(e); load_bases(e)
e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
ow={}
def on_w(uc,acc,a,sz,val,ud):
    if OBJ_LO<=a<OBJ_HI: ow[a]=val
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
# force init gates and drive dispatcher wrapper repeatedly
e.wr(0x4092e0,0,1); e.wr(0x406aa0,0,1); e.wr(0x4069e4,1,1); e.wr(0x4069e7,0,1); e.wr(0x406aa4,0,4)
for it in range(40000):
    e.call(0x8e0aa, maxinsn=300000)
    if it%4000==0:
        print(f" iter{it}: objcells={len(ow)} cmd={e.rd(0x4069a8,1)&0xff:#x} phase={e.rd(0x406aa4,4)}")
    if e.rd(0x406aa0,1)&0xff: print(f"  init-done at iter{it}"); break
print("after dispatcher loop objcells=",len(ow))
# also try running the full task tick with seg2 mapped
res=e.call(0x219c0, maxinsn=10_000_000)
print("task 219c0 ->",res[0],"objcells=",len(ow))
for a in sorted(ow)[:24]: print(f"   [{a:#x}]={ow[a]:#x}")
