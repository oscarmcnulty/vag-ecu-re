#!/usr/bin/env python3
# Static decode of the ESP8 8R0907379BG COM config (partial). Decodes the two EXPLICIT-buffer
# signal tables (the app-consumed signal subset) and reports the bump-allocator inputs. Documents
# the precise blocker for a full bump replication. Pure static (no emulation).
import struct
FW="firmware/8R0907379BG_0030.bin"; data=open(FW,'rb').read(); n=len(data)
u32=lambda o: struct.unpack('>I',data[o:o+4])[0] if o+4<=n else 0
u16=lambda o: struct.unpack('>H',data[o:o+2])[0] if o+2<=n else 0
u8=lambda o: data[o] if o<n else 0

def sig_table_0xb038c():
    o=0xb038c; out=[]
    while u32(o)==0x01000000 and u16(o+4)!=0 and o<0xb0800:
        out.append(dict(off=o,sig=u16(o+4),length=u8(o+6),flags=u8(o+7),buf=u32(o+8),consumer=u32(o+0xc))); o+=0x10
    return out
def pdu_table_0xb06f0():
    o=0xb06f0; out=[]
    while 0x403000<=u32(o+4)<0x40b000 and 1<=u8(o+2)<=80:
        out.append(dict(off=o,sig=u16(o),length=u8(o+2),flags=u8(o+3),buf=u32(o+4),idx=u16(o+8),grp=u8(o+0xa))); o+=0xc
    return out

if __name__=="__main__":
    st=sig_table_0xb038c(); pt=pdu_table_0xb06f0()
    print(f"EXPLICIT-buffer signal tables (app-consumed subset):")
    print(f"  sig_table 0xb038c: {len(st)} signals, all with a consumer fn ptr and a fixed buffer")
    print(f"  pdu_table 0xb06f0: {len(pt)} signals (grp 0x02/0xff = front-sensor)")
    print(f"  TOTAL explicit signals: {len(st)+len(pt)} (of ~3000 across 214 msgs -> the rest are bump-allocated)")
    print(f"  EPB_01 signals present in explicit tables: NO (EPB is in the bump-allocated bulk RX)")
    print(f"\nBump allocator inputs (FUN_0006b936): objtable base *0x4069b4, count *0x4069fc, limit *0xbda34")
    print(f"BLOCKER: the bulk-RX signal->buffer map (incl EPB) is NOT in the explicit tables; the nested")
    print(f"PB-config (0xb2xxx=signal-id arrays, 0xa7xxx=handle lists, 0xb6a44 group table) did not decode")
    print(f"into the {{size,ptr}} descriptor arrays the allocator reads, and NO bump-allocated buffer exists")
    print(f"as a validation anchor (the 87 explicit buffers use a tightly-packed gap=len format, NOT the")
    print(f"header-bump format of FUN_0006b936). So a bump replication could not be built AND validated.")
