#!/usr/bin/env python3
# COM RX routing bootstrap-emulation attempt + static flash signal-table decode.
# Result: full config-init emulation BLOCKED (SBOOT-initialized .data absent); the flash
# COM signal->buffer table IS recovered statically. See docs/com_routing_decoded.md.
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu, RET_MAGIC, STACK_BASE, STACK_SIZE
from unicorn.arm_const import *

data=open(os.path.join(os.path.dirname(__file__),'..','firmware','8R0907379BG_0030.bin'),'rb').read()
def u32(o): return struct.unpack('>I',data[o:o+4])[0]
def u16(o): return struct.unpack('>H',data[o:o+2])[0]

# ---- 1) Validate the parent's byteswap/memset correction (the "allocator veneers") ----
def test_veneers():
    e=Emu()
    r=e.call(0x49e80,(0x0102,))          # byteswap16
    print("byteswap16(0x0102) ->", hex(r[1]&0xffff), "(expect 0x0201)")
    e2=Emu(); e2.wr(0x405000,0xdeadbeef,4); e2.call(0x49e64,(0x405000,4))  # memset(ptr,0,4)
    print("memset(0x405000,0,4): [0x405000]=", hex(e2.rd(0x405000)),"(expect 0)")

# ---- 2) Demonstrate the bootstrap blocker: _start uses SBOOT monitor SVCs ----
def test_start_blocked():
    e=Emu(); svc_hits=[]
    from unicorn import UC_HOOK_INTR
    def on_intr(uc,intno,ud): svc_hits.append(uc.reg_read(UC_ARM_REG_PC))
    e.uc.hook_add(UC_HOOK_INTR, on_intr)
    e.call(0x8f440, maxinsn=200)
    print(f"_start @0x8f440 emulation: hit {len(svc_hits)} SVC(monitor) calls -> needs SBOOT, .data uninit")

# ---- 3) FUN_0006b936 bump allocator cannot run without seeded config ----
def test_allocator_needs_config():
    e=Emu()  # zeroed RAM: *0x4069b4 (object table base)=0, msg count=0
    r=e.call(0x6b936, maxinsn=50000)
    wr=[w for w in e.writes if 0x400000<=w[1]<0x600000]
    print(f"FUN_0006b936 from zeroed RAM: {len(wr)} RAM writes (no config -> no buffer allocation)")

# ---- 4) STATIC decode of the flash COM signal->buffer table ----
def decode_signal_table():
    recs=[]; o=0xb0388
    while o<0xb0e00:
        marker=u32(o); buf=u32(o+8)
        if marker in (0x01000000,) and 0x400000<=buf<0x40b000:
            recs.append((o,u16(o+4),data[o+6],data[o+7],buf,u32(o+0xc)))
        o+=0x10
    return recs

if __name__=='__main__':
    print("== veneer correction =="); test_veneers()
    print("\n== bootstrap blocker =="); test_start_blocked()
    print("\n== allocator w/o config =="); test_allocator_needs_config()
    print("\n== flash COM signal table (static) ==")
    recs=decode_signal_table()
    print(f"{len(recs)} signal records recovered. sample:")
    for r in recs[:6]:
        print(f"  @0x{r[0]:x} sig=0x{r[1]:04x} len={r[2]} buf=0x{r[4]:08x}")
