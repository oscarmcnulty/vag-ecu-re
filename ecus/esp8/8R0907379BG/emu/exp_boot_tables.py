#!/usr/bin/env python3
# Boot from reset (map-on-demand) and check if the COM routing tables materialize.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UcError
from unicorn.arm_const import *

e = Emu()
e.uc.reg_write(UC_ARM_REG_SP, 0x300000+0x80000-0x200)
# watch key routing addrs
WATCH = {0x4069b4:"descTblPtr", 0x4069b0:"struct", 0x406cd0:"groupTbl[0]", 0x40a1a8:"descTbl[0]"}
before = {a:e.rd(a,4) for a in WATCH}
insn=0
try:
    e.uc.emu_start(0x0, 0xFFFFFFF0, count=5_000_000)
except UcError as ex:
    print("stopped:", ex, "pc=0x%x"%e.uc.reg_read(UC_ARM_REG_PC))
after = {a:e.rd(a,4) for a in WATCH}
print("=== routing addrs before -> after boot ===")
for a,nm in WATCH.items():
    print(f"  {nm:12} 0x{a:x}: 0x{before[a]:08x} -> 0x{after[a]:08x}  {'CHANGED' if before[a]!=after[a] else ''}")
# dump group table region if populated
p = e.rd(0x4069b4,4)
print(f"\n*(0x4069b4) = 0x{p:08x}")
print("group table 0x406cd0 (first 6 recs x0x18):")
for g in range(6):
    a=0x406cd0+g*0x18
    print(f"  g{g} @{a:x}:", " ".join(f"{e.rd(a+4*j,4):08x}" for j in range(6)))
print(f"total RAM writes captured: {len(e.writes)}")
