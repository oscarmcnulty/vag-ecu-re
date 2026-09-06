#!/usr/bin/env python3
# STEP1 dynamic: find the object-table BUILDER by write-watching 0x4069b4 while running
# each COM-init dispatcher case. Report the storing PC.
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

# COM-init dispatcher (FUN_0008df52) cases + phase machines + likely builders
CANDS = {
 0x814c2:'F_814c2',0x89f90:'F_89f90',0x8efbc:'F_8efbc',0x9a66a:'F_9a66a',
 0x892a0:'F_892a0(phasemach)',0x6bb22:'F_6bb22',0x8e298:'F_8e298',0x7a072:'F_7a072',
 0x9db84:'F_9db84',0xa0d48:'F_a0d48',0x9e64c:'F_9e64c',0x9edd8:'F_9edd8',
 0xa0f98:'F_a0f98',0x89db0:'F_89db0',0x9eb44:'F_9eb44',0x9fd9c:'F_9fd9c',
 0x9e820:'F_9e820',0x931e8:'F_931e8',0x8dac0:'F_8dac0',0x4a034:'F_4a034',
 0x5df44:'F_5df44',0x89194:'F_89194',0x891b8:'F_891b8',0x9e3f4:'F_9e3f4',
}
WATCH_LO, WATCH_HI = 0x4069b0, 0x4069fc

def detect_thumb(fw, addr):
    b=fw[addr:addr+4]
    if b[0]==0xE9 and b[1]==0x2D: return False
    if b[0]==0xB5: return True
    return (addr & 1)==0 and b[0]!=0xE9 and (b[0]&0xF0)!=0xE0  # heuristic

hits={}
for addr,name in CANDS.items():
    e=Emu()
    caught=[]
    def on_w(uc,access,a,size,val,ud):
        if WATCH_LO<=a<=WATCH_HI:
            caught.append((uc.reg_read(UC_ARM_REG_PC),a,val))
    e.uc.hook_add(UC_HOOK_MEM_WRITE, on_w)
    # try both modes; catch any write to the control block
    for thumb in (True, False):
        e.reset(); e.uc.hook_add(UC_HOOK_MEM_WRITE, on_w)
        try:
            e.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x200)
            e.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
            e.uc.emu_start(addr|(1 if thumb else 0), RET_MAGIC, count=300000)
        except Exception:
            pass
        if caught: break
    if caught:
        hits[name]=caught[:4]
        print(f"WRITE to ctrl-block from {name}: "+", ".join(f"pc=0x{pc:x} [0x{a:x}]<-0x{v:x}" for pc,a,v in caught[:4]))
if not hits:
    print("No candidate wrote 0x4069b0-fc directly (base likely set via alloc-return or .data). Next: check callers / .data image.")
