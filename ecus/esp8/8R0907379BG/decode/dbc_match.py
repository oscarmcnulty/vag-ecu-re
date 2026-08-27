#!/usr/bin/env python3
"""Heuristic: fingerprint-match decoded descriptor blocks to vw_mlb.dbc messages by byte-layout.
Each descriptor block = ordered {frame-byte -> signal, byte-size}. Each DBC message = signals with
(start_bit,len). A block matches a message if their MULTI-BYTE-signal byte positions + DLC align."""
import struct, os, re
HERE=os.path.dirname(os.path.abspath(__file__))
fw=open(os.path.join(HERE,"..","firmware","8R0907379BG_0030.bin"),"rb").read()
DBC="/home/om/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
def u32(a): return struct.unpack('>I',fw[a:a+4])[0]

# ---- parse DBC: message -> (dlc, [(name,start_bit,len)]) ----
msgs={}; cur=None
for line in open(DBC):
    m=re.match(r'BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)',line)
    if m: cur=int(m.group(1)); msgs[cur]=dict(name=m.group(2),dlc=int(m.group(3)),sigs=[])
    s=re.match(r'\s+SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@',line)
    if s and cur is not None:
        nm,sb,ln=s.group(1),int(s.group(2)),int(s.group(3))
        msgs[cur]['sigs'].append((nm,sb,ln))
# DBC signature: set of byte indices that a >=9-bit (or byte-crossing) signal covers >1 byte
def dbc_sig(mid):
    mb=set()  # byte offsets that start a multi-byte grouping
    for nm,sb,ln in msgs[mid]['sigs']:
        if nm in ('CHECKSUM','COUNTER'): continue
        if ln>8 or (sb%8)+ln>8:   # spans >1 byte
            mb.add(sb//8)
    return frozenset(mb)

# ---- parse descriptor blocks (corrected {count,buffer,encoding}) ----
def parse(lo,hi):
    out=[];a=lo
    while a+12<=hi:
        c,b,e=u32(a),u32(a+4),u32(a+8)
        if 0x400000<=b<0x410000 and 1<=c<=8: out.append((c,b,e));a+=0xc
        else:a+=4
    return out
sigs=parse(0xb6a44,0xb7400)
# segment into messages
blocks=[]; cur=[]; boff=0
for c,b,e in sigs:
    cur.append((c,b,boff)); boff+=c
    if e==0 or boff>=8:
        blocks.append(cur); cur=[]; boff=0
if cur: blocks.append(cur)
def blk_sig(blk):
    return frozenset(bo for c,b,bo in blk if c>=2)   # multi-byte-signal byte offsets

# ---- match ----
print(f"DBC messages: {len(msgs)}; decoded blocks: {len(blocks)}")
print("\n=== fingerprint matches (block multi-byte positions == DBC multi-byte positions, same DLC) ===")
for bi,blk in enumerate(blocks):
    bs=blk_sig(blk); dlc=sum(c for c,_,_ in blk)
    cands=[mid for mid in msgs if msgs[mid]['dlc']==dlc and dbc_sig(mid)==bs and len(bs)>0]
    if cands:
        bufs=f"0x{blk[0][1]:x}.."
        for mid in cands:
            print(f"  block{bi} (dlc{dlc}, mb@{sorted(bs)}, bufs {bufs}) == 0x{mid:x} {msgs[mid]['name']}")
# the AEB block specifically
print("\n=== AEB block signature vs candidates ===")
aeb=[blk for blk in blocks if any(b==0x40926c for _,b,_ in blk)]
if aeb:
    blk=aeb[0]; bs=blk_sig(blk); dlc=sum(c for c,_,_ in blk)
    print(f"  AEB block: dlc={dlc}, multi-byte signals at byte-offsets {sorted(bs)}")
    for mid in msgs:
        if msgs[mid]['dlc']==dlc:
            d=dbc_sig(mid)
            if d and (d==bs or d<=bs or bs<=d):
                print(f"    candidate 0x{mid:x} {msgs[mid]['name']}: mb@{sorted(d)}")
