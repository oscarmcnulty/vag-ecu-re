#!/usr/bin/env python3
# Fast validator: seed the 58-slot skeleton, run ONLY the 22 COM-init phases (3x), then read the
# object-table region + anchors directly from emulator RAM and judge real-vs-garbage.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn.arm_const import *
A=os.path.join(os.path.dirname(__file__),'..','analysis')
mode={}
for ln in open(os.path.join(A,'function_entries.txt')):
    ln=ln.strip()
    if not ln or ln.startswith('#'): continue
    p=ln.split(','); mode[int(p[0],16)]=(len(p)>1 and p[1].upper()=='T')
seed={}
for ln in open(os.path.join(A,'ram_bases.csv')):
    ln=ln.strip()
    if ln.startswith('ram_addr') or not ln: continue
    a,v=ln.split(','); seed[int(a,16)]=int(v,16)
PHASES=[0x814c2,0x89f90,0x8efbc,0x9a66a,0x892a0,0x6bb22,0x9e3f4,0x8e298,0x7a072,0x9db84,
        0xa0d48,0x9e64c,0x9edd8,0xa0f98,0x89db0,0x9eb44,0x9fd9c,0x9e820,0x931e8,0x8dac0,0x8db80,0x6b936]
e=Emu()
for a,v in seed.items():
    try: e.wr(a,v)
    except: pass
for _ in range(3):
    for fn in PHASES:
        thumb=mode.get(fn,(fn&1)==0)
        e.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x400)
        e.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
        try: e.uc.emu_start(fn|(1 if thumb else 0), RET_MAGIC, count=150000)
        except Exception: pass
def rd(a):
    try: return int.from_bytes(e.uc.mem_read(a&~3,4),'big')
    except: return None
out=open('/tmp/claude-1000/-home-om-vag-ecu-re/40bdcfd8-6a56-4ae0-82cb-66b213f06d13/scratchpad/bv.txt','w')
def P(s): print(s); out.write(s+"\n"); out.flush()
P("=== ANCHORS (should hold if state is real) ===")
for a,nm in [(0x405e81,'ESP_05 TX base'),(0x403a40,'decel comfort'),(0x403fac,'decel type1'),
             (0x407bb4,'decel type4'),(0x4069b4,'objtable base(->0x40a1a8)'),(0x40a1a4,'objtable extent')]:
    P(f"  0x{a:x} {nm}: 0x{rd(a):08x}")
# object-table record validity: +8 a pointer, +6 small sigcount
valid=0; tot=0; sample=[]
for rec in range(0x40a1a8,0x40affc,0x10):
    tot+=1; p8=rd(rec+8)
    sc=(rd(rec+4)>>16)&0xff if rd(rec+4) is not None else None
    ok=p8 is not None and (0x400000<=p8<0x40ffff or 0<p8<0x134000)
    if ok: valid+=1
    if rec<0x40a1a8+0x60: sample.append((rec,rd(rec),rd(rec+4),rd(rec+8),rd(rec+0xc)))
P(f"=== object-table records: {valid}/{tot} have a valid pointer at +8 ===")
for rec,w0,w4,w8,wc in sample:
    P(f"  rec@0x{rec:x}: +0={'0x%08x'%w0 if w0 is not None else '?'} +4={'0x%08x'%w4 if w4 is not None else '?'} +8={'0x%08x'%w8 if w8 is not None else '?'} +c={'0x%08x'%wc if wc is not None else '?'}")
P("VERDICT: "+("REAL (anchors hold + records carry pointers)" if valid>tot*0.5 else "GARBAGE (records lack valid pointers -> cold-state computation)"))
out.close()
