import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR
OBJ_LO,OBJ_HI=0x40a1a8,0x40a1a8+0x3000
def load_bases(e):
    for line in open(os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
# functions to stub (immediate return). Seed with the known diverging one + common MMIO/delay ones.
STUBS=set([0x9d2d6])
def build(stubs, run_task=True):
    e=Emu(); e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011]); load_bases(e)
    e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
    ow={}
    def on_w(uc,acc,a,sz,val,ud):
        if OBJ_LO<=a<OBJ_HI: ow[a]=val
    e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
    stubset=set(x&~1 for x in stubs)
    def on_code(uc,addr,size,ud):
        if (addr&~1) in stubset:
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR)&~1)
    e.uc.hook_add(UC_HOOK_CODE,on_code)
    disp_reached=[False]
    def on_blk(uc,addr,size,ud):
        if addr==0x8e0aa: disp_reached[0]=True
    from unicorn import UC_HOOK_BLOCK
    e.uc.hook_add(UC_HOOK_BLOCK,on_blk)
    res=e.call(0x219c0, maxinsn=20_000_000)
    return e,res,ow,disp_reached[0]
import unicorn
# auto-stub loop: run, if ERR find where PC is stuck and stub that fn, retry
from unicorn.arm_const import UC_ARM_REG_PC
for attempt in range(40):
    e=Emu(); e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011]); load_bases(e)
    e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
    ow={}
    def on_w(uc,acc,a,sz,val,ud):
        if OBJ_LO<=a<OBJ_HI: ow[a]=val
    e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
    stubset=set(x&~1 for x in STUBS)
    last=[0]
    def on_code(uc,addr,size,ud):
        last[0]=addr
        if (addr&~1) in stubset:
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR)&~1)
    e.uc.hook_add(UC_HOOK_CODE,on_code)
    disp=[False]
    from unicorn import UC_HOOK_BLOCK
    e.uc.hook_add(UC_HOOK_BLOCK, lambda uc,a,s,u: disp.__setitem__(0,True) if a==0x8e0aa else None)
    try:
        e.uc.reg_write(0, 0)  # noop
        r=e.call(0x219c0, maxinsn=20_000_000)
        st=r[0]
    except Exception as ex:
        st='EXC'; 
    stuck=last[0]
    # find containing fn of stuck PC (approx: round down to a task fn or the addr itself)
    print(f"attempt {attempt}: status={st} disp_reached={disp[0]} objcells={len(ow)} stuck_pc={stuck:#x} nstubs={len(STUBS)}",flush=True)
    if disp[0] or len(ow)>0:
        print("  -> dispatcher reached / objtable growing!")
        for a in sorted(ow)[:20]: print(f"     [{a:#x}]={ow[a]:#x}")
        break
    if st in ('OK',) and not disp[0]:
        print("  completed without reaching dispatcher; stub list insufficient"); break
    # stub the stuck region: add stuck_pc's function (approx by rounding to nearest 'task-ish' start)
    STUBS.add(stuck & ~1)
