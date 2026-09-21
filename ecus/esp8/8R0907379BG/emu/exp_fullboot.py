#!/usr/bin/env python3
"""Full-boot COM-init emulation: run the task tick FUN_000219c0 with the MMIO the init
waits on modeled 'ready', so the boot-installed COM/CanIf dispatch runs and builds the
object table 0x40a1a8. Auto-detects wait loops (PC stuck / MMIO polled) and reports them
so each can be modeled. Watches object-table writes + RAM function-pointer installs."""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_PC

HERE=os.path.dirname(os.path.abspath(__file__))
def load_bases(e):
    p=os.path.join(HERE,"..","analysis","ram_bases.csv")
    for line in open(p):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try: e.wr(int(a,16),int(v,16),4)
        except: pass

# MMIO addresses to force-return nonzero ('ready'). Filled in iteratively.
READY_MMIO=set()

def build():
    e=Emu()
    e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])   # seg2
    load_bases(e)
    e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
    return e

def run(secs_insn=20_000_000, ready=None):
    e=build()
    ready = ready or {}
    pc_hits=collections.Counter()
    objw={}
    fnptr_installs={}
    # loop detection: track recent PCs
    recent=collections.deque(maxlen=200)
    stuck=[None]
    def on_code(uc,addr,size,ud):
        recent.append(addr)
        pc_hits[addr]+=1
        # detect tight loop: same small set of PCs repeated a lot
        if pc_hits[addr]==50000 and stuck[0] is None:
            stuck[0]=addr
            uc.emu_stop()
    def on_write(uc,ac,a,sz,val,ud):
        if 0x40a1a8<=a<0x40a1a8+0x8000: objw[a]=val
        # RAM function-pointer install: writing a code addr (<0x134000) to RAM
        if 0x400000<=a<0x410000 and 0<val<0x134000 and sz==4: fnptr_installs[a]=val
    # model 'ready' MMIO via a read hook that patches values
    def on_read(uc,ac,a,sz,val,ud):
        pass
    e.uc.hook_add(UC_HOOK_CODE,on_code)
    e.uc.hook_add(UC_HOOK_MEM_WRITE,on_write)
    # pre-seed ready MMIO values
    for addr,v in ready.items():
        page=addr & ~0xfff
        try: e.uc.mem_map(page,0x1000)
        except: pass
        e.wr(addr,v,4)
    res=e.call(0x219c0, maxinsn=secs_insn)
    top=pc_hits.most_common(8)
    return res, stuck[0], top, objw, fnptr_installs

if __name__=="__main__":
    res,stuck,top,objw,fnptr=run()
    print("task tick ->",res[0], "stuck at:", hex(stuck) if stuck else None)
    print("hottest PCs (loop candidates):",[(hex(p),c) for p,c in top])
    print("obj-table cells:",len(objw), " fn-ptr installs:",len(fnptr))
    if stuck:
        print("STUCK loop at 0x%x - inspect what MMIO it polls"%stuck)

# ---------------------------------------------------------------------------
# RESULT (session 2): the task tick FUN_000219c0 hangs jumping to 0x0 -- it calls a
# RAM function pointer that is NULL because the COM/CanIf dispatch was never installed.
# The dispatch is installed by boot init (EcuM/module inits) that is NOT in the task
# tick and is itself RAM-wired (FUN_0008db80 etc. have no callers). _start (0x8f440)
# hands off to main via an SBOOT monitor SVC (svc #0xff10; bx sp), so main's address is
# SBOOT-provided and absent from the ASW image; there is no in-image main/EcuM (the only
# many-call functions are the periodic task lists 0x2174e/21edc/21bac/220cc/219c0/223b0).
# => Full-boot emulation cannot bootstrap the dispatch from the ASW image alone; it needs
#    the SBOOT context (a separate/protected flash not in this bin). This confirms, from a
#    third independent direction, the documented SBOOT-install blocker.
# ---------------------------------------------------------------------------
