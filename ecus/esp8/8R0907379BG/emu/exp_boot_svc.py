#!/usr/bin/env python3
# Boot emulation with SBOOT SVCs modeled. Try to reach COM config-init from _start (0x8f440)
# so the object table materializes. Fallback: run FUN_0006b936 with seeded config.
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import *
from unicorn.arm_const import *
import capstone
HERE=os.path.dirname(os.path.abspath(__file__))
FW=open(os.path.join(HERE,'..','firmware','8R0907379BG_0030.bin'),'rb').read()
md_a=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM|capstone.CS_MODE_BIG_ENDIAN)
md_t=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB|capstone.CS_MODE_BIG_ENDIAN)
def fu32(o): return struct.unpack('>I',FW[o:o+4])[0]

uc=Uc(UC_ARCH_ARM,UC_MODE_ARM|UC_MODE_BIG_ENDIAN)
uc.mem_map(0,0x140000); uc.mem_write(0,FW)
uc.mem_map(0x400000,0x200000)      # RAM
uc.mem_map(0x300000,0x80000)       # stack
uc.mem_map(0xfff00000,0x100000)    # peripherals (CAN 0xfff7xxxx etc.)
extra=set()
svc_log=[]; last_pcs=[]
def on_unmapped(uc,acc,addr,size,val,ud):
    page=addr&~0xFFF
    if page not in extra:
        try: uc.mem_map(page,0x1000); extra.add(page)
        except UcError: return False
    return True
def on_intr(uc,intno,ud):
    pc=uc.reg_read(UC_ARM_REG_PC)
    # read svc imm from instruction at pc-4 (thumb) or pc (arm) — pc already advanced?
    # In unicorn ARM, PC on intr points at the svc instr. Decode it.
    cpsr=uc.reg_read(UC_ARM_REG_CPSR); thumb=cpsr&(1<<5)
    ins=FW[pc:pc+4] if pc<len(FW) else bytes(uc.mem_read(pc,4))
    imm=None
    try:
        md=md_t if thumb else md_a
        i=next(md.disasm(ins,pc))
        if i.mnemonic.startswith('svc'): imm=i.op_str
    except StopIteration: pass
    # PC already advanced past svc by unicorn; decode imm from the svc instr at pc-4 (ARM)
    immn=None
    sp=pc-4
    if not thumb and sp>=0 and sp+4<=len(FW):
        immn=struct.unpack('>I',FW[sp:sp+4])[0] & 0x00ffffff
    svc_log.append((sp,hex(immn) if immn is not None else None))
    uc.reg_write(UC_ARM_REG_R0, 0xffffffff if immn in (0xff10,0x7f10) else 0)
    return   # do NOT advance PC; unicorn already did
def on_code(uc,addr,size,ud):
    last_pcs.append(addr)
uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED|UC_HOOK_MEM_WRITE_UNMAPPED|UC_HOOK_MEM_FETCH_UNMAPPED,on_unmapped)
uc.hook_add(UC_HOOK_INTR,on_intr)
uc.hook_add(UC_HOOK_CODE,on_code)

uc.reg_write(UC_ARM_REG_SP,0x37fe00)
uc.reg_write(UC_ARM_REG_CPSR,0x1d3)   # SVC mode, I/F disabled, ARM state
uc.reg_write(UC_ARM_REG_LR,0xFFFFFFF0)
print("=== Approach A: boot from _start 0x8f440, model SVCs ===")
try:
    uc.emu_start(0x8f440,0xFFFFFFF0,count=3000000)
    print("returned; pc=0x%x"%uc.reg_read(UC_ARM_REG_PC))
except UcError as e:
    print("STOP:",e,"pc=0x%x"%uc.reg_read(UC_ARM_REG_PC))
print("insns executed:",len(last_pcs))
print("distinct code regions hit:",sorted(set(p&~0xfff for p in last_pcs))[:20])
print("SVCs hit (first 15):",svc_log[:15])
print("total SVCs:",len(svc_log))
# did *0x4069b4 (obj table base) get written?
def rd(a,n=4): return int.from_bytes(uc.mem_read(a,n),'big')
print("*0x4069b4 (obj base) =",hex(rd(0x4069b4)),"  *0x4069fc (cnt)=",hex(rd(0x4069fc)),"  *0x4069b0(bump)=",hex(rd(0x4069b0)))
