#!/usr/bin/env python3
# ESP8 8R0907379BG COM config-graph static decode (partial). What decodes cleanly from flash:
#  - mailbox config (canid->handle) @0xaea38
#  - config-root records {count, ptr_a, ptr_b} @0xa7e14 (routing/gateway grouping, NOT per-msg signals)
#  - 0xb2xxx flat signal-ID membership lists
# BLOCKER: the per-message signal grouping WITH byte-sizes (the bump allocator's input) is assembled at
# runtime by the registration driver reading multiple tables via RAM base pointers into staging 0x4069a6;
# it is not a single decodable static table, and there is no bump-allocated buffer to validate against.
import struct
FW="firmware/8R0907379BG_0030.bin"
data=open(FW,'rb').read();n=len(data)
u32=lambda o: struct.unpack('>I',data[o:o+4])[0] if o+4<=n else 0
u16=lambda o: struct.unpack('>H',data[o:o+2])[0] if o+2<=n else 0
u8 =lambda o: data[o] if o<n else 0

def mailbox_config():
    # 31 records stride 0x18 @0xaea38: +0 RX HW reg, +8 filter reg, +0xd..e canid, +0xf..10 handle, +0x11 mask, +0x17 type
    out=[]
    for r in range(31):
        o=0xaea38+r*0x18
        canid=u16(o+0xd); handle=u16(o+0xf)
        if 0x40<=canid<0x800:
            out.append(dict(rec=r,off=o,canid=canid,handle=handle,mask=u8(o+0x11),type=u8(o+0x17)))
    return out

def config_root():
    # {count<<16, ptr_a, ptr_b} records @~0xa7e14; ptrs -> 0xae/0xaf/0xb0 config
    out=[]; o=0xa7e14
    while o<0xa7ed0:
        w=u32(o)
        if (w&0xffff)==0 and 1<=(w>>16)<=64 and 0xa2000<=u32(o+4)<0xb8000 and 0xa2000<=u32(o+8)<0xb8000:
            out.append(dict(off=o,count=w>>16,ptr_a=u32(o+4),ptr_b=u32(o+8))); o+=12
        else: o+=4
    return out

if __name__=="__main__":
    mb=mailbox_config()
    print(f"mailbox config: {len(mb)} records")
    for m in mb: print(f"  canid=0x{m['canid']:x} -> handle=0x{m['handle']:x} (mask 0x{m['mask']:02x} type 0x{m['type']:02x})")
    print(f"\nconfig root: {len(config_root())} records (routing/gateway groups, small counts)")
    for r in config_root(): print(f"  count={r['count']} ptr_a=0x{r['ptr_a']:x} ptr_b=0x{r['ptr_b']:x}")
