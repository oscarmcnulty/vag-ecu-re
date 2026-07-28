#!/usr/bin/env python3
"""Recover missed TriCore functions from the raw bin by harvesting CALL targets.

Why: this firmware is ~75% "undefined" to Ghidra because it is heavily function-pointer
dispatched -> auto-analysis (direct-call following) never disassembles the indirectly-reachable
code. But every direct CALL/JL/FCALL encodes its target, and a call target IS a function entry.

Method + validation tiers (see RESULTS UPDATE 38/39):
  - Calibrated TriCore B-format displacement: op1 in {0x6D CALL,0x5C JL,0x61 FCALL};
    disp24 = (W>>16)&0xFFFF | ((W>>8)&0xFF)<<16 ; target = site + sign_ext(disp24)*2.
    (Verified: reproduces 100% of the >=2-caller set that Ghidra decompiled with 0 bad markers.)
  - MULTI tier: target called by >=2 independent sites -> airtight (coincidence negligible).
  - SINGLE tier, validated: (a) call-site is a real instruction boundary reachable by linear
    decode from a known function start (TriCore len = 2 if byte0&1==0 else 4) -> the CALL is real;
    AND (b) target decodes to a clean body (all-valid opcodes reaching a return).
Emits addr lists; integrate with core/ghidra/DecompileAddrs.java then drop any Ghidra bad-markers.
"""
import struct,os,glob,sys
BASE=0x80000000; LO,HI=0x80020000,0x80200000
# repo-relative so this runs from any checkout; override either with an env var.
PACK=os.environ.get("PACK", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ecus","simos85"))
BIN=os.environ.get("BIN", os.path.join(PACK,"firmware","8R0907551F_Original.bin"))
ANA=os.path.join(PACK,"analysis")
data=open(BIN,"rb").read()
# valid opcode set: low-bytes actually seen at any 2/4-decoded position in KNOWN functions.
def known_starts():
    s=set()
    for d in ("decompiles_r","decompiles_extra"):
        for f in glob.glob(f"{ANA}/{d}/*.c"):
            try: s.add(int(os.path.basename(f)[:-2],16))
            except: pass
    for l in open(f"{ANA}/function_entries.txt"):
        l=l.strip()
        if l.startswith("0x"):
            try: s.add(int(l,16))
            except: pass
    return sorted(x for x in s if LO<=x<HI)
starts=known_starts()
valid=set(); 
for i,F in enumerate(starts):
    nxt=starts[i+1] if i+1<len(starts) else HI
    va=F;st=0
    while va<nxt and va<HI-1 and st<4000:
        b=data[va-BASE]; valid.add(b); va+= 2 if (b&1)==0 else 4; st+=1
def w32(va): return struct.unpack("<I",data[va-BASE:va-BASE+4])[0]
def tgt(va):
    W=w32(va); d=((W>>16)&0xFFFF)|(((W>>8)&0xFF)<<16)
    if d&0x800000: d-=0x1000000
    return va+d*2
sites={}
va=LO
while va<HI-4:
    if data[va-BASE] in (0x6D,0x5C,0x61):
        t=tgt(va)
        if LO<=t<HI and (t&1)==0: sites.setdefault(t,[]).append(va)
    va+=1
boundary=set()
for i,F in enumerate(starts):
    nxt=starts[i+1] if i+1<len(starts) else HI
    va=F;st=0
    while va<nxt and va<HI-1 and st<4000:
        boundary.add(va); b=data[va-BASE]
        if b not in valid: break
        va+= 2 if (b&1)==0 else 4; st+=1
def body_ok(T):
    va=T;st=0
    while va<HI-1 and st<2000:
        b=data[va-BASE]
        if b not in valid: return False
        if b in (0x00,0x90): return True
        va+= 2 if (b&1)==0 else 4; st+=1
    return False
known=set(starts)
multi=[t for t,s in sites.items() if len(s)>=2 and t not in known]
single_hi=[t for t,s in sites.items() if len(s)==1 and t not in known
           and any(x in boundary for x in s) and body_ok(t)]
print(f"known={len(known)} harvested_targets={len(sites)}")
print(f"MULTI (>=2 callers, new): {len(multi)}")
print(f"SINGLE validated (site-in-code + clean body, new): {len(single_hi)}")
if len(sys.argv)>1 and sys.argv[1]=="--emit":
    open("multi.txt","w").write("\n".join(f"0x{t:08x}" for t in sorted(multi))+"\n")
    open("single_hi.txt","w").write("\n".join(f"0x{t:08x}" for t in sorted(single_hi))+"\n")
    print("wrote multi.txt, single_hi.txt")
