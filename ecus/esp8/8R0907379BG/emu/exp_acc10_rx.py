#!/usr/bin/env python3
# Empirically find where a received ACC_10 frame's payload lands and gets unpacked.
# Drive can_rx_indication (0x8e3ec, ARM) with a marked frame + the ACC_10 record's state_ram,
# log every write, then report which RAM the marker bytes reach.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn.arm_const import *

e = Emu()
FRAME_HDR = 0x500100
PAYLOAD   = 0x500200
DEST      = 0x404588            # ACC_10 record state_ram (from msg cfg table rec#13)
# ACC_10 payload: put a distinctive marker in each byte so we can see where each lands
marker = bytes([0xA0,0xA1,0xA2,0xA3,0xA4,0xA5,0xA6,0xA7])
e.uc.mem_write(PAYLOAD, marker)
# frame header: *r7 halfword -> FUN_00049e48 byteswap -> DLC; 0x0800 -> DLC 8
e.uc.mem_write(FRAME_HDR, (0x0800).to_bytes(2,'big') + (0x0117).to_bytes(2,'big') + b'\x00\x00\x00\x00')
e.uc.reg_write(UC_ARM_REG_R4, PAYLOAD)
e.uc.reg_write(UC_ARM_REG_R5, DEST)
e.uc.reg_write(UC_ARM_REG_R7, FRAME_HDR)
e.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x200)
e.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
e.uc.reg_write(UC_ARM_REG_CPSR, 0x00000013)   # SVC mode, N=0 V=0 -> in_NG==in_OV branch
e.writes=[]
try:
    e.uc.emu_start(0x8e3ec, RET_MAGIC, count=200000)
    print("returned OK")
except Exception as ex:
    print("stopped:", ex, "pc=0x%x"%e.uc.reg_read(UC_ARM_REG_PC))

# Where did the marker bytes land? scan RAM for 0xA0..0xA7 sequence and singles
print("\n=== writes during reception (addr: value) ===")
seen=set()
for pc,addr,size,val in e.writes:
    if 0x400000<=addr<0x600000 and addr not in seen:
        seen.add(addr)
        v=val & ((1<<(size*8))-1)
        tag=" <-- MARKER" if (v&0xf0)==0xa0 or v in marker else ""
        print(f"  w @0x{addr:08x} sz{size} = 0x{v:x}{tag}")
print(f"\ntotal distinct RAM writes: {len(seen)}")
# also scan for the marker landing anywhere
print("\n=== marker bytes found in RAM after reception ===")
for base in range(0x404000, 0x409000, 4):
    chunk=bytes(e.uc.mem_read(base,4))
    if any((b&0xf0)==0xa0 and b>=0xa0 and b<=0xa7 for b in chunk):
        print(f"  0x{base:08x}: {chunk.hex()}")
