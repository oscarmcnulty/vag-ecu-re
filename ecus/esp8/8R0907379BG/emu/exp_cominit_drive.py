#!/usr/bin/env python3
# Software-only: drive the COM-init dispatcher (FUN_0008e0aa -> FUN_0008df52) in a tight loop,
# keeping RAM state, to build the object table at 0x40a1a8 without running the whole task list.
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE

OBJ_LO, OBJ_HI = 0x40a1a8, 0x40a1a8+0x2700
def load_bases(e):
    p=os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv"); nb=0
    for line in open(p):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try: e.wr(int(a,16),int(v,16),4); nb+=1
        except: pass
    return nb

e=Emu()
load_bases(e)
e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
objwrites={}
def on_w(uc,acc,a,sz,val,ud):
    if OBJ_LO<=a<OBJ_HI: objwrites[a]=val
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)

prev=0; stalls=0
DISPATCH=0x8e0aa
for it in range(60000):
    e.call(DISPATCH, maxinsn=200000)
    cur=len(objwrites)
    if cur==prev:
        stalls+=1
        if stalls>2000: break
    else:
        stalls=0
    prev=cur
    if it%5000==0:
        cmd=e.rd(0x4069a8,1)&0xff; phase=e.rd(0x406aa4,4)
        print(f"  iter {it}: objtable-cells={cur} cmd_byte={cmd:#x} phase={phase:#x}")
print(f"\nfinal object-table cells written: {len(objwrites)}")
if objwrites:
    for a in sorted(objwrites)[:24]:
        print(f"  [{a:#x}] = {objwrites[a]:#x}")
