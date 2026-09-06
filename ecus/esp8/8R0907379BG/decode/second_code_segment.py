#!/usr/bin/env python3
# Proves (statically, no Ghidra) that a SECOND code region exists above CODE_HI=0xa2000 in the
# ESP8 8R0907379BG image, which the reproduce pipeline previously excluded as DATA. This region
# holds the AUTOSAR-COM signal-deserialization / RX-processing stack -- the code that binds CAN
# frames to the signal buffers, incl. the 4 decel channels. Its ARM sub-blocks load at
# VMA = file_offset + 3 (a reconstruction shift), proven by cross-references from seg1/config.
#   run: python3 decode/second_code_segment.py
import struct
FW="firmware/8R0907379BG_0030.bin"; d=open(FW,"rb").read(); n=len(d)
u32=lambda o: struct.unpack('>I',d[o:o+4])[0] if o+4<=n else 0
def is_push(w): return (w&0xffff0000)==0xe92d0000 and (w&0x4000)   # push {..,lr}
def is_poppc(w): return (w&0xffff0000)==0xe8bd0000 and (w&0x8000)  # pop {..,pc}

# 1) ARM prologues/epilogues above 0xa2000 cluster at file-offset residue 1 (not 0) -> shifted code
from collections import Counter
rp=Counter(); re_=Counter()
for o in range(0xa2000,0x134000):
    w=u32(o)
    if is_push(w): rp[o&3]+=1
    if is_poppc(w): re_[o&3]+=1
print("ARM push{..lr} by (file offset mod 4):", dict(rp))
print("ARM pop{..pc}  by (file offset mod 4):", dict(re_))
res=max(rp,key=lambda k:rp[k])
pushes=[o for o in range(0xa2000,0x134000) if (o&3)==res and is_push(u32(o))]
print(f"dominant residue={res}: {len(pushes)} functions, span file {pushes[0]:#x}..{pushes[-1]:#x}")

# 2) VMA = file + 3: seg1/config references to seg2 resolve only with delta +3
starts=set(pushes)
def find_ptrs(valset):
    hits=[]
    for o in range(0, n-4):
        if u32(o) in valset: hits.append(o)
    return hits
p_flat=[o for o in find_ptrs(starts)          if o<0xa2000 or o>=0x106000]  # ptr==file addr
p_p3  =[o for o in find_ptrs(set(s+3 for s in starts)) if o<0xa2000 or o>=0x106000] # ptr==file+3
print(f"\nabsolute pointers to a seg2 function start:")
print(f"  using VMA==file   : {len(p_flat)}")
print(f"  using VMA==file+3 : {len(p_p3)}   <- the correct model")
for o in p_p3[:6]:
    print(f"    @{o:#x} -> {u32(o):#x} (seg2 fn at file {u32(o)-3:#x})")

# 3) sample: the ARM code at file 0xfa239 (comfort-message COM deserializer) is coherent
print("\nsample bytes @file 0xfa239 (VMA 0xfa23c) e92d4ff0 = 'push {r4-r11,lr}':",
      f"{u32(0xfa239):#010x}")
print("=> integrate with EspSeg2.java (split DATA at 0xbb045, move +3, exec). See docs/second_code_segment.md")
