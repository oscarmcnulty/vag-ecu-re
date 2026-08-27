#!/usr/bin/env python3
# Boot emulation to map peripherals: run from reset; on-demand-map unmapped pages and
# record every access outside flash+RAM -> reveals the SFR/peripheral (MMIO) address map.
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UcError
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR
import capstone

e = Emu()
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM|capstone.CS_MODE_BIG_ENDIAN)
print("reset vector @0x0:", e.uc.mem_read(0,16).hex())
for i in md.disasm(bytes(e.uc.mem_read(0,32)),0):
    print(f"  {i.address:08x}: {i.mnemonic} {i.op_str}")
# Run from reset. SP/LR set by harness defaults; count-capped. Map-on-demand keeps it going.
e.uc.reg_write(UC_ARM_REG_SP, 0x300000+0x80000-0x200)
e.writes=[]
try:
    e.uc.emu_start(0x0, 0xFFFFFFF0, count=2_000_000)
except UcError as ex:
    print("stopped:", ex, "at pc=0x%x"%e.uc.reg_read(UC_ARM_REG_PC))
# Peripheral accesses (outside flash 0-0x140000 and RAM 0x400000-0x600000, stack 0x300000-0x380000)
def is_peri(a): return not (a<0x140000 or 0x400000<=a<0x600000 or 0x300000<=a<0x380000)
peri_w=collections.Counter(); peri_r=collections.Counter()
for a,rec in e.mmio.items():
    if is_peri(a):
        if rec['w']: peri_w[a&0xFFFFF000]+=rec['w']
        if rec['r']: peri_r[a&0xFFFFF000]+=rec['r']
print("\n=== peripheral WRITE pages during boot (candidate SFR/valve regions) ===")
for base,c in peri_w.most_common(25): print(f"   0x{base:08x}: {c} writes")
print("\n=== peripheral READ pages ===")
for base,c in peri_r.most_common(15): print(f"   0x{base:08x}: {c} reads")
