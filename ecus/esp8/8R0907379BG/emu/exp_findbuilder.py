#!/usr/bin/env python3
# Sweep seg2 Dcm functions; find which one writes the region-table window 0x401ee0-0x401f60.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

TBL_LO, TBL_HI = 0x401ee6, 0x401f50   # the entry area (skip header 0x401ee0-ee6)

# load function entries (VMA, T/A)
ents=[]
for l in open(os.path.join(os.path.dirname(__file__),"..","analysis","function_entries.txt")):
    l=l.strip()
    if not l or l[0]=='#': continue
    p=l.split(','); a=int(p[0],16); t=(len(p)>1 and p[1].upper()=='T')
    if 0xbb048<=a<0xe0000: ents.append((a,t))
print(f"sweeping {len(ents)} seg2 Dcm functions")

bases=[]
bp=os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")
if os.path.exists(bp):
    for line in open(bp):
        line=line.strip()
        if not line or line[0] in '#r': continue
        try:
            a,v=line.split(',')[:2]; bases.append((int(a,16),int(v,16)))
        except: pass

e=Emu()
e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])  # seg2 overlay

hits={}
cur={'w':[]}
def on_w(uc,acc,a,sz,val,ud):
    if TBL_LO<=a<TBL_HI:
        cur['w'].append((a,val & ((1<<(sz*8))-1),sz))
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)

def seed():
    for a,v in bases:
        try: e.wr(a,v,4)
        except: pass
    # zero the window
    e.uc.mem_write(0x401ee0, b'\x00'*0x80)

for a,t in ents:
    seed(); cur['w']=[]
    e.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x400)
    e.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
    try:
        e.uc.emu_start(a|(1 if t else 0), RET_MAGIC, count=200000)
    except Exception: pass
    if cur['w']:
        hits[a]=list(cur['w'])

print(f"\n{len(hits)} functions wrote the entry window:")
for a in sorted(hits):
    ws=hits[a]; addrs=sorted(set(w[0] for w in ws))
    print(f"  FUN_{a:08x}: {len(ws)} writes to {[hex(x) for x in addrs]}")
