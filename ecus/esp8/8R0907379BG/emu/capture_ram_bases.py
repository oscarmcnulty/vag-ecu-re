#!/usr/bin/env python3
# Phase 2 (RAM data image): recover boot-installed RAM pointer-table values for ESP8 (ARM-BE),
# mirroring ecus/al551 gen_ram_bases.sh but via our Unicorn harness. Detect self-contained
# pointer-install stubs from the decompiled corpus, run each in isolation, capture RAM writes
# whose value is a pointer (flash <0x134000 or RAM 0x400000-0x40ffff). Output ram_bases.csv.
import sys, os, re, glob, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

HERE=os.path.dirname(os.path.abspath(__file__))
CORP=os.path.join(HERE,'..','analysis','decompiles_r')
ENTRIES=os.path.join(HERE,'..','analysis','function_entries.txt')
OUTCSV=os.path.join(HERE,'..','analysis','ram_bases.csv')

# mode map from the manifest
mode={}
for ln in open(ENTRIES):
    ln=ln.strip()
    if ln.startswith('#') or not ln: continue
    p=ln.split(','); a=int(p[0],16); mode[a]= (len(p)>1 and p[1].upper()=='T')

# --- detect install-stub candidates from the corpus ---
# A stub = a small function whose body is dominated by pointer stores `*X = Y;` and has no calls
# (FUN_...() ) except trivial. These install const pointer tables at boot.
store_re=re.compile(r'^\s*\*')
call_re=re.compile(r'\b(FUN_[0-9a-f]{8}|thunk_FUN_[0-9a-f]{8})\s*\(')
cands=[]
for f in glob.glob(os.path.join(CORP,'*.c')):
    base=os.path.basename(f)[:-2]
    try: addr=int(base,16)
    except: continue
    t=open(f,errors='replace').read()
    body=t[t.find('{')+1:t.rfind('}')]
    lines=[l for l in body.splitlines() if l.strip() and not l.strip().startswith('//')]
    if not lines or len(lines)>80: continue
    stmts=[l for l in lines if '=' in l and 'return' not in l and l.strip() not in ('{','}')]
    if len(stmts)<3: continue
    stores=[l for l in stmts if store_re.match(l)]
    calls=[l for l in lines if call_re.search(l)]
    # dominated by stores, few/no calls -> install stub
    if len(stores)>=max(3,int(0.5*len(stmts))) and len(calls)<=2:
        cands.append(addr)
cands=sorted(set(cands))
print(f"install-stub candidates: {len(cands)}")

# --- run each stub, capture RAM pointer writes ---
POOL=0x500000
def is_ptr(v): return (0<v<0x134000) or (0x400000<=v<0x410000)
rows={}   # ram_addr -> value (last write wins)
ran=0; wrote=0
for addr in cands:
    e=Emu()
    # seed the known constant roots so table-relative writes land coherently
    try:
        e.wr(0x4069b4,0x40a1a8); e.wr(0x4069b0,POOL); e.wr(0x4069fc,0xd6)
    except: pass
    caught=[]
    def on_w(uc,access,a,size,val,ud):
        if 0x400000<=a<0x410000 and size==4:
            caught.append((a,val & 0xffffffff))
    e.uc.hook_add(UC_HOOK_MEM_WRITE, on_w)
    thumb=mode.get(addr, (addr&1)==0)
    try:
        e.call(addr, thumb=thumb, maxinsn=200000)
        ran+=1
    except Exception:
        pass
    for a,v in caught:
        if is_ptr(v):
            rows[a]=v; wrote+=1
print(f"ran {ran}/{len(cands)} stubs; captured {len(rows)} distinct RAM pointer slots ({wrote} writes)")

# --- targeted: variant_cfg_select(0x11) installs the calibration base pointers (0x40081c..0x40082c).
# This build's boot path (variant_init_fixed 0x87410) calls it with the compile-time constant 0x11,
# so the cal bases are deterministic. Run it directly with r0=0x11 and capture the RAM installs so
# the ~85 cal-base readers fold to the concrete dataset. (variant_cfg_select @0x872cc is ARM.)
_e=Emu()
_cal=[]
def _on_cal(uc,access,a,size,val,ud):
    if 0x40081c<=a<=0x400830 and size==4: _cal.append((a,val & 0xffffffff))
_e.uc.hook_add(UC_HOOK_MEM_WRITE, _on_cal)
try:
    _e.call(0x872cc, args=(0x11,), thumb=mode.get(0x872cc, True), maxinsn=20000)
except Exception:
    pass
for a,v in _cal:
    if is_ptr(v): rows[a]=v
print(f"variant_cfg_select(0x11): captured {len(set(a for a,_ in _cal))} cal-base installs")

# --- write ram_bases.csv ---
with open(OUTCSV,'w') as w:
    w.write("ram_addr,value\n")
    for a in sorted(rows):
        w.write(f"0x{a:08x},0x{rows[a]:08x}\n")
print(f"wrote {OUTCSV}: {len(rows)} rows")

# --- validate against anchors ---
print("\n=== anchor check (do known pointer slots appear?) ===")
anchors={0x4069b4:'obj_table_base(->0x40a1a8)'}
for a,nm in anchors.items():
    print(f"  0x{a:x} {nm}: {'0x%08x'%rows[a] if a in rows else 'NOT captured'}")
# show a sample of captured slots pointing into the object-table region or flash config
samp=[(a,v) for a,v in sorted(rows.items()) if 0x40a000<=v<0x40b000 or 0xb0000<=v<0xb8000][:15]
print("  sample slots -> objtable/config region:")
for a,v in samp: print(f"    0x{a:08x} -> 0x{v:08x}")
