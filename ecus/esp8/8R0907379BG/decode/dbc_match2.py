#!/usr/bin/env python3
"""Refined DBC fingerprint match: exact multi-byte-signal signature, filtered to the 214 IDs the
ESP actually receives (msg-config 0xa9fc0). Signature = the set of {start_byte: byte_span} for
signals that span >1 byte -- the strongest discriminator."""
import struct, os, re
HERE=os.path.dirname(os.path.abspath(__file__))
fw=open(os.path.join(HERE,"..","firmware","8R0907379BG_0030.bin"),"rb").read()
def u32(a): return struct.unpack('>I',fw[a:a+4])[0]
DBC="/home/om/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"

# received IDs from msg-config 0xa9fc0
rx_ids=set()
for i in range(223):
    v=u32(0xa9fc0+i*0x14)
    if 0x80<=v<=0x7ff: rx_ids.add(v)

# DBC
msgs={}; cur=None
for line in open(DBC):
    m=re.match(r'BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)',line)
    if m: cur=int(m.group(1)); msgs[cur]=dict(name=m.group(2),dlc=int(m.group(3)),sigs=[])
    s=re.match(r'\s+SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@',line)
    if s and cur is not None: msgs[cur]['sigs'].append((s.group(1),int(s.group(2)),int(s.group(3))))
def dbc_mb(mid):
    d={}
    for nm,sb,ln in msgs[mid]['sigs']:
        if nm in ('CHECKSUM','COUNTER'): continue
        span=(sb%8+ln+7)//8
        if span>1: d[sb//8]=span
    return tuple(sorted(d.items()))

# descriptor blocks
def parse(lo,hi):
    out=[];a=lo
    while a+12<=hi:
        c,b,e=u32(a),u32(a+4),u32(a+8)
        if 0x400000<=b<0x410000 and 1<=c<=8: out.append((c,b,e));a+=0xc
        else:a+=4
    return out
sigs=parse(0xb6a44,0xb7400)
blocks=[]; cur=[]; boff=0
for c,b,e in sigs:
    cur.append((c,b,boff)); boff+=c
    if e==0 or boff>=8: blocks.append(cur); cur=[]; boff=0
if cur: blocks.append(cur)
def blk_mb(blk): return tuple(sorted((bo,c) for c,b,bo in blk if c>=2))

print(f"ESP receives {len(rx_ids)} IDs; DBC has {len(msgs)}; decoded {len(blocks)} blocks\n")
print("=== high-confidence matches (exact multi-byte signature, RECEIVED ids only, >=1 multi-byte sig) ===")
for bi,blk in enumerate(blocks):
    sig=blk_mb(blk); dlc=sum(c for c,_,_ in blk)
    if not sig: continue
    cands=[mid for mid in rx_ids if mid in msgs and msgs[mid]['dlc']==dlc and dbc_mb(mid)==sig]
    b0=blk[0][1]
    if cands:
        names=", ".join(f"0x{m:x} {msgs[m]['name']}" for m in cands)
        star=" <-- UNIQUE" if len(cands)==1 else ""
        print(f"  block{bi} bufs 0x{b0:x} sig{list(sig)}: {names}{star}")
print("\n=== AEB block ===")
aeb=[blk for blk in blocks if any(b==0x40926c for _,b,_ in blk)][0]
sig=blk_mb(aeb); dlc=sum(c for c,_,_ in aeb)
cands=[mid for mid in rx_ids if mid in msgs and msgs[mid]['dlc']==dlc and dbc_mb(mid)==sig]
print(f"  AEB sig={list(sig)} dlc={dlc}; received-DBC matches: {[hex(m) for m in cands] or 'NONE (undocumented radar msg)'}")
# also show received IDs NOT in DBC (candidates for the undoc AEB msg)
undoc=sorted(i for i in rx_ids if i not in msgs)
print(f"  received IDs absent from DBC (undoc pool, {len(undoc)}): {[hex(i) for i in undoc[:24]]}")

# ============ narrow the AEB radar message: find the ID run of matching-signature blocks ============
print("\n=== radar-object run: blocks with signature [(1,2),(3,2),(5,2)] ===")
aeb_sig=((1,2),(3,2),(5,2))
run=[(bi,blk[0][1]) for bi,blk in enumerate(blocks) if blk_mb(blk)==aeb_sig]
for bi,b0 in run: print(f"    block{bi}: first-buffer 0x{b0:x}")
# msg-config: the 0xa9fc0 table in order; find a contiguous ID run matching the buffer run count
print(f"\n  {len(run)} radar-object-shaped blocks. Their buffers:", [hex(b) for _,b in run])
# dump msg-config IDs in the 0x117-0x140 range (radar/ACC extended) in table order
print("\n  msg-config IDs (0xa9fc0) in radar range, in TABLE ORDER (candidate radar-object IDs):")
seq=[]
for i in range(223):
    v=u32(0xa9fc0+i*0x14)
    if 0x110<=v<=0x160: seq.append((i,v))
print("   ", " ".join(f"#{i}=0x{v:x}" for i,v in seq[:30]))
# The AEB decel signal 0x40926c: which object index? and the ANB target ties to ONE object (the threat)
print("\n  => the AEB decel input (0x40926c) is ONE radar-object message; the object set are consecutive")
print("     0xa9fc0 IDs. Exact ID = correlate block order to table order (radar objects are a contiguous run).")
