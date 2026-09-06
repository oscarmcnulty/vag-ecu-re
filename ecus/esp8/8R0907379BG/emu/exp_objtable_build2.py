import sys, os, bisect, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR
OBJ_LO,OBJ_HI=0x40a1a8,0x40a1a8+0x3000
FE=sorted(int(l.split(',')[0],16) for l in open("analysis/function_entries.txt") if l.startswith('0x'))
def containing(pc):
    i=bisect.bisect_right(FE,pc)-1
    return FE[i] if i>=0 else None
def load_bases(e):
    for line in open("analysis/ram_bases.csv"):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
STUBS=set()
# never stub the COM-init chain itself
PROTECT={0x8e0aa,0x8df52,0x931e8,0x814c2,0x89f90,0x8e298,0x892a0,0x6b936,0x8db80,0x8dac0,0x89e64,0x9a608,0x8efbc}
for attempt in range(60):
    e=Emu(); e.uc.mem_write(0xbb048,e.fw[0xbb045:0x134011]); load_bases(e)
    e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
    ow={}; last=[0]; disp=[0]
    def on_w(uc,acc,a,sz,val,ud):
        if OBJ_LO<=a<OBJ_HI: ow[a]=val
    def on_code(uc,addr,size,ud):
        last[0]=addr
        if addr==0x8e0aa: disp[0]+=1
        if addr in STUBS:
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR)&~1)
    e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
    e.uc.hook_add(UC_HOOK_CODE,on_code)
    try:
        r=e.call(0x219c0, maxinsn=8_000_000); st=r[0]
    except Exception as ex: st='EXC'
    fn=containing(last[0])
    if disp[0] or ow:
        print(f"attempt{attempt}: REACHED dispatcher x{disp[0]}, objcells={len(ow)}, stubs={len(STUBS)}"); 
        if ow:
            for a in sorted(ow)[:16]: print(f"   [{a:#x}]={ow[a]:#x}")
            break
    if st=='OK':
        print(f"attempt{attempt}: task returned OK, disp={disp[0]} objcells={len(ow)} stubs={len(STUBS)}"); 
        if disp[0]: print("  dispatcher ran but no objtable writes"); 
        break
    # stub the diverging function
    if fn and fn not in PROTECT:
        STUBS.add(fn)
    else:
        print(f"attempt{attempt}: stuck at {last[0]:#x} (fn {fn:#x}) - protected/unknown, stop"); break
print("final: dispatcher hits",disp[0] if 'disp' in dir() else '?',"objcells",len(ow),"stubs",len(STUBS))
