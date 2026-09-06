#!/usr/bin/env python3
# Decode the ESP8 CAN mailbox / message config tables (static). Two tables:
#  - 0xaea38 (31 recs, stride 0x18): HW mailbox config {hwreg@+0, filter@+8, DLC, canid@+0xd..e,
#    handle@+0xf..10, mask@+0x11, arb-word@+0x10}. handle<->mailbox; CAN acceptance uses the mask.
#    EPB_01 = CAN 0x104 -> handle 0x25b (idx4-6) is the on-car-confirmed anchor.
#  - 0xa9fc0 (msg-cfg, stride 0x14): {canid, .., routine=can_rx_indication 0x8e3ec, state_ram}.
#    Real CAN-ids incl ACC_10=0x117 (state_ram 0x404588). (0x100-0x116 incl ACC_05 0x10d live in
#    the other RX table 0xafae0.)
import struct
d=open("firmware/8R0907379BG_0030.bin","rb").read()
u8=lambda o:d[o]; u16=lambda o:struct.unpack('>H',d[o:o+2])[0]; u32=lambda o:struct.unpack('>I',d[o:o+4])[0]
print("== HW mailbox config 0xaea38 (handle <-> mailbox, mask-filtered) ==")
from collections import defaultdict
h2=defaultdict(list)
for i in range(31):
    o=0xaea38+i*0x18
    hw=u32(o); canid=u16(o+0xd); handle=u16(o+0xf); mask=u8(o+0x11); typ=u8(o+0x17)
    h2[handle].append((hw,canid,mask,typ))
for h in sorted(h2):
    ent=h2[h]
    print(f"  handle {h:#06x}: "+", ".join(f"hw={hw&0xffff:#06x}/id={c:#05x}/msk={m:#04x}" for hw,c,m,t in ent))
print("\n== msg-cfg 0xa9fc0 (real CAN-ids -> state_ram status slot) : 0x100-0x130 cluster ==")
for i in range(260):
    o=0xa9fc0+i*0x14; cid=u32(o); state=u32(o+0x10)
    if 0x100<=cid<=0x130 and 0x404000<=state<0x40b000:
        print(f"  CAN {cid:#06x} -> state_ram {state:#x}")
