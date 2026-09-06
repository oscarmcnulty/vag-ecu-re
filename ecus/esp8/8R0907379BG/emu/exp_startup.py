import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP
OBJ_LO,OBJ_HI=0x40a1a8,0x40a1a8+0x3000
e=Emu()
e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])  # seg2 correct VMA
ow={}; pcset=set()
def on_w(uc,acc,a,sz,val,ud):
    if OBJ_LO<=a<OBJ_HI: ow[a]=val
e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
# run from _start; harness continues past SVC and maps MMIO on demand (reads 0)
e.uc.reg_write(UC_ARM_REG_SP, 0x300000+0x80000-0x200)
import unicorn
try:
    e.uc.emu_start(0x8f440, 0xFFFFFFF0, count=60_000_000)
    print("emu ended normally")
except unicorn.UcError as ex:
    print("emu stopped:", ex, "PC=", hex(e.uc.reg_read(UC_ARM_REG_PC)))
print("object-table cells written:", len(ow), " obj_base *0x4069b4=", hex(e.rd(0x4069b4)))
for a in sorted(ow)[:30]: print(f"  [{a:#x}]={ow[a]:#x}")
