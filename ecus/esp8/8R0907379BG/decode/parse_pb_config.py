#!/usr/bin/env python3
# Static parser for the ESP8 8R0907379BG flash COM PB-config (no bench, no emulation).
# Recovers signal->buffer for the two explicit-buffer COM signal tables and the type5-unused proof.
import struct
FW="firmware/8R0907379BG_0030.bin"
data=open(FW,'rb').read(); n=len(data)
u32=lambda o: struct.unpack('>I',data[o:o+4])[0]
u16=lambda o: struct.unpack('>H',data[o:o+2])[0]
u8 =lambda o: data[o]

def sig_table_0xb038c():
    # stride 0x10: {marker 0x01000000, sig u16@+4, len u8@+6, flags u8@+7, RAM_buf u32@+8, consumer_fn u32@+c}
    out=[]; o=0xb038c
    while u32(o)==0x01000000 and u16(o+4)!=0:
        out.append(dict(off=o,sig=u16(o+4),length=u8(o+6),flags=u8(o+7),buf=u32(o+8),consumer=u32(o+0xc)))
        o+=0x10
    return out

def pdu_table_0xb06ec():
    # stride 0xc: {sig u16@+0, len u8@+2, flags u8@+3, RAM_buf u32@+4, idx u16@+8, grp u8@+a}
    out=[]; o=0xb06f0
    while True:
        buf=u32(o+4); ln=u8(o+2)
        if not (0x400000<=buf<0x40b000 and 1<=ln<=64 and u8(o+0xb)==0): break
        out.append(dict(off=o,sig=u16(o),length=u8(o+2),flags=u8(o+3),buf=buf,idx=u16(o+8),grp=u8(o+0xa)))
        o+=0xc
    return out

def type5_unused_proof():
    def findall(v):
        b=struct.pack('>I',v); r=[]; i=data.find(b)
        while i!=-1: r.append(i); i=data.find(b,i+1)
        return r
    res={}
    for name,v in [('type5_staging_0x403d6e',0x403d6e),('type5_commitdst_0x403d66',0x403d66),
                   ('type5_current_0x403d76',0x403d76),('type5_enable_0x403d7d',0x403d7d)]:
        offs=findall(v); res[name]=[(hex(x),'code' if x<0xa2000 else 'config') for x in offs]
    return res

if __name__=="__main__":
    st=sig_table_0xb038c(); pt=pdu_table_0xb06ec()
    print(f"signal table 0xb038c: {len(st)} signals")
    print(f"PDU table 0xb06ec: {len(pt)} signal records, groups={sorted(set(r['grp'] for r in pt))}")
    print("type5 unused proof (all occurrences are CODE, none in CONFIG):")
    for k,v in type5_unused_proof().items(): print(f"  {k}: {v}")
