#!/usr/bin/env python3
# Phase 2 #1: skeleton-seeded iterative bootstrap. Seed the emulator with the recovered 58-slot
# control-block skeleton, run the install stubs + COM-init phase machines in ONE accumulating
# context, capture all RAM writes, fold them back into the seed, iterate to fixpoint. Then read
# the object-table region 0x40a1a8+ to see if per-message records materialized.
import sys, os, re, glob, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

HERE=os.path.dirname(os.path.abspath(__file__)); A=os.path.join(HERE,'..','analysis')
mode={}
for ln in open(os.path.join(A,'function_entries.txt')):
    ln=ln.strip()
    if ln.startswith('#') or not ln: continue
    p=ln.split(','); mode[int(p[0],16)]=(len(p)>1 and p[1].upper()=='T')

# load the 58-slot skeleton
seed={}
for ln in open(os.path.join(A,'ram_bases.csv')):
    ln=ln.strip()
    if ln.startswith('ram_addr') or not ln: continue
    a,v=ln.split(','); seed[int(a,16)]=int(v,16)
print(f"skeleton seed: {len(seed)} slots")

# install stubs (same detector as capture) + phase machines
def stub_cands():
    store=re.compile(r'^\s*\*'); call=re.compile(r'\b(FUN_[0-9a-f]{8}|thunk_FUN_[0-9a-f]{8})\s*\(')
    out=[]
    for f in glob.glob(os.path.join(A,'decompiles_r','*.c')):
        try: addr=int(os.path.basename(f)[:-2],16)
        except: continue
        t=open(f,errors='replace').read(); body=t[t.find('{')+1:t.rfind('}')]
        lines=[l for l in body.splitlines() if l.strip() and not l.strip().startswith('//')]
        if not lines or len(lines)>80: continue
        st=[l for l in lines if '=' in l and 'return' not in l]
        if len(st)<3: continue
        if len([l for l in st if store.match(l)])>=max(3,int(0.5*len(st))) and len([l for l in lines if call.search(l)])<=2:
            out.append(addr)
    return sorted(set(out))
STUBS=stub_cands()
PHASES=[0x814c2,0x89f90,0x8efbc,0x9a66a,0x892a0,0x6bb22,0x9e3f4,0x8e298,0x7a072,0x9db84,
        0xa0d48,0x9e64c,0x9edd8,0xa0f98,0x89db0,0x9eb44,0x9fd9c,0x9e820,0x931e8,0x8dac0,0x8db80,0x6b936]
print(f"{len(STUBS)} stubs + {len(PHASES)} phases")

def run_pass(seed):
    e=Emu()
    for a,v in seed.items():
        try: e.wr(a,v)
        except: pass
    writes={}
    def on_w(uc,access,a,size,val,ud):
        if 0x400000<=a<0x410000:
            writes[a & ~3]= (writes.get(a&~3,0))  # placeholder; capture below
    # capture full 4-byte words
    raw=[]
    def on_w2(uc,access,a,size,val,ud):
        if 0x400000<=a<0x410000: raw.append((a,size,val))
    e.uc.hook_add(UC_HOOK_MEM_WRITE, on_w2)
    # run stubs then phases (phases x3 for state progression)
    order=STUBS + PHASES*3
    for fn in order:
        thumb=mode.get(fn,(fn&1)==0)
        e.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x400)
        e.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
        try: e.uc.emu_start(fn|(1 if thumb else 0), RET_MAGIC, count=300000)
        except Exception: pass
    # accumulate final state per 4-byte slot from the emulator memory
    newstate=dict(seed)
    touched=set(a&~3 for a,sz,v in raw)
    for a in touched:
        try: newstate[a]=int.from_bytes(e.uc.mem_read(a,4),'big')
        except: pass
    return newstate, e

# fixpoint iteration
prev=-1
for it in range(6):
    seed, e = run_pass(seed)
    objslots=[a for a in seed if 0x40a1a8<=a<0x40b000]
    print(f"iter {it}: total slots={len(seed)}  object-table-region slots={len(objslots)}")
    if len(seed)==prev: print("  fixpoint reached"); break
    prev=len(seed)

# report object-table region
print("\n=== object-table region 0x40a1a8+ after bootstrap ===")
objslots=sorted(a for a in seed if 0x40a1a8<=a<0x40b000)
if objslots:
    print(f"populated slots: {len(objslots)}, span 0x{objslots[0]:x}-0x{objslots[-1]:x} ({(objslots[-1]-0x40a1a8)//0x10} records)")
    for a in objslots[:30]:
        v=seed[a]; tag=' <ptr>' if (0<v<0x134000 or 0x400000<=v<0x40ffff) else ''
        print(f"  0x{a:08x} -> 0x{v:08x}{tag}")
else:
    print("  still empty -> per-message records did not materialize even with skeleton seed")

# ---- VALIDATION ----
print("\n=== VALIDATION ===")
anchors={0x405e81:'ESP_05 sig base(TX)',0x403a40:'decel_src_comfort',0x403fac:'decel_src_type1',
         0x407bb4:'decel_src_type4',0x4069b4:'objtable base',0x40a1a4:'objtable extent'}
for a,nm in anchors.items():
    aa=a & ~3
    v=seed.get(aa,None)
    print(f"  0x{a:x} {nm}: slot0x{aa:x}={'0x%08x'%v if v is not None else 'unset'}")
# count object-table records that look VALID: +8 field a 0x40xxxx or flash pointer, +6 small
def rd(a): return seed.get(a & ~3)
valid=0; total=0
for rec in range(0x40a1a8,0x40affc,0x10):
    total+=1
    p8=rd(rec+8)
    if p8 is not None and (0x400000<=p8<0x40ffff or 0<p8<0x134000): valid+=1
print(f"  object-table records with a valid pointer at +8: {valid}/{total}")
# save full bootstrapped state
with open(os.path.join(A,'ram_bootstrap.csv'),'w') as w:
    w.write("ram_addr,value\n")
    for a in sorted(seed): w.write(f"0x{a:08x},0x{seed[a]:08x}\n")
print(f"  saved {len(seed)} slots -> analysis/ram_bootstrap.csv")
