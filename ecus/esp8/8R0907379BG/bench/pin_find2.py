#!/usr/bin/env python3
"""Determine when CAN_PS pin assignment (params 0x22=Hpin, 0x23=Lpin) takes effect.
pin_find showed set-after-connect returns rc=0 but passes no traffic (6/14 control = 0 frames,
though the primary channel on 6/14 is clearly live). Test: (A) set pins, disconnect, reconnect,
check persistence + sniff; (B) set pins, sniff on SAME handle but longer; (C) open primary CAN
(6/14) AND CAN_PS (3/11) concurrently, drive stimulus on both, sniff both -> the dual-bus setup.

Run: tools\\py311x86\\python.exe bench\\pin_find2.py
"""
import collections, ctypes, time
from ctypes import (POINTER, Structure, byref, c_char_p, c_ubyte, c_ulong, c_void_p,
                    create_string_buffer, pointer)
DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
CAN = 5; CAN_PS = 0x8004; PASS_FILTER = 1; GET_CONFIG = 0x01; SET_CONFIG = 0x02; TX = 0x0001
class MSG(Structure):
    _fields_ = [("ProtocolID", c_ulong),("RxStatus", c_ulong),("TxFlags", c_ulong),
                ("Timestamp", c_ulong),("DataSize", c_ulong),("ExtraDataIndex", c_ulong),("Data", c_ubyte*4128)]
class SCONFIG(Structure): _fields_=[("Parameter",c_ulong),("Value",c_ulong)]
class SCONFIG_LIST(Structure): _fields_=[("NumOfParams",c_ulong),("ConfigPtr",POINTER(SCONFIG))]
d = ctypes.WinDLL(DLL)
for n,a in [("PassThruOpen",[c_char_p,POINTER(c_ulong)]),("PassThruClose",[c_ulong]),
            ("PassThruConnect",[c_ulong,c_ulong,c_ulong,c_ulong,POINTER(c_ulong)]),("PassThruDisconnect",[c_ulong]),
            ("PassThruReadMsgs",[c_ulong,POINTER(MSG),POINTER(c_ulong),c_ulong]),
            ("PassThruWriteMsgs",[c_ulong,POINTER(MSG),POINTER(c_ulong),c_ulong]),
            ("PassThruStartMsgFilter",[c_ulong,c_ulong,POINTER(MSG),POINTER(MSG),POINTER(MSG),POINTER(c_ulong)]),
            ("PassThruIoctl",[c_ulong,c_ulong,c_void_p,c_void_p]),("PassThruGetLastError",[c_char_p])]:
    f=getattr(d,n); f.argtypes=a; f.restype=c_ulong
def err(): b=create_string_buffer(160); d.PassThruGetLastError(b); return b.value.decode("latin-1","replace")
def crc8(data,poly=0x1D,init=0xFF,xor=0xFF):
    c=init
    for b in data:
        c^=b
        for _ in range(8): c=((c<<1)^poly)&0xFF if c&0x80 else (c<<1)&0xFF
    return c^xor
def mk(proto,cid,payload=b""):
    m=MSG(); m.ProtocolID=proto; data=cid.to_bytes(4,"big")+payload; m.DataSize=len(data)
    for i,x in enumerate(data): m.Data[i]=x
    return m
def getcfg(ch,pid):
    sc=SCONFIG(pid,0); scl=SCONFIG_LIST(1,pointer(sc))
    return (sc.Value if d.PassThruIoctl(ch,GET_CONFIG,byref(scl),None)==0 else None)
def setpins(ch,h,l):
    arr=(SCONFIG*2)(SCONFIG(0x22,h),SCONFIG(0x23,l)); scl=SCONFIG_LIST(2,arr)
    return d.PassThruIoctl(ch,SET_CONFIG,byref(scl),None)
def passall(proto,ch):
    mask,patt=mk(proto,0),mk(proto,0); fid=c_ulong(0)
    d.PassThruStartMsgFilter(ch,PASS_FILTER,byref(mask),byref(patt),None,byref(fid))
def tx(proto,ch,cid,ctr):
    body=bytes([0,0,0,0,0,0x08,ctr]); m=mk(proto,cid,body+bytes([crc8(body)])); n=c_ulong(1)
    d.PassThruWriteMsgs(ch,byref(m),byref(n),20)

STIM={5:[0x000,0x0a0,0x0c0,0x100,0x103,0x106,0x08a],  # module B accepted ids
      0x8004:[0x100,0x101,0x1a0,0x200,0x0a0,0x0c0,0x060]}

def sniff_one(proto,ch,secs):
    seen=collections.Counter(); ctr=0; t0=time.time(); last=0.0
    while time.time()-t0<secs:
        now=time.time()
        if now-last>=0.02:
            last=now; ctr=(ctr+1)&0xFF
            for cid in STIM[proto]: tx(proto,ch,cid,ctr)
        rx=MSG(); cnt=c_ulong(1)
        if d.PassThruReadMsgs(ch,byref(rx),byref(cnt),2)==0 and cnt.value and rx.DataSize>=4:
            if rx.RxStatus & TX: continue
            seen[int.from_bytes(bytes(rx.Data[:4]),"big")]+=1
    return seen

def rep(tag,seen):
    ids=" ".join(f"0x{c:03x}x{seen[c]}" for c in sorted(seen)[:14])
    print(f"  {tag}: RX={sum(seen.values())} frames  {ids}")

def main():
    dev=c_ulong(0); assert d.PassThruOpen(None,byref(dev))==0
    # --- A: set pins then DISCONNECT/RECONNECT, check persistence + sniff (CAN_PS 6/14 control) ---
    print("=== A: CAN_PS 6/14 (control) — set, reconnect, sniff ===")
    ch=c_ulong(0); d.PassThruConnect(dev,CAN_PS,0,500000,byref(ch))
    print(f"  set 6/14 rc={setpins(ch,6,14)} readback 0x22={getcfg(ch,0x22):#06x} 0x23={getcfg(ch,0x23):#06x}")
    d.PassThruDisconnect(ch)
    ch=c_ulong(0); d.PassThruConnect(dev,CAN_PS,0,500000,byref(ch))
    print(f"  after reconnect: 0x22={getcfg(ch,0x22):#06x} 0x23={getcfg(ch,0x23):#06x} (persisted?)")
    passall(CAN_PS,ch); rep("6/14 after reconnect",sniff_one(CAN_PS,ch,2.5))
    # set again post-reconnect in case it reset
    setpins(ch,6,14); passall(CAN_PS,ch); rep("6/14 reset+set again",sniff_one(CAN_PS,ch,2.5))
    d.PassThruDisconnect(ch)
    # --- C: primary CAN(6/14) + CAN_PS(3/11) concurrently; drive+sniff both ---
    print("=== C: DUAL — primary CAN 6/14 (module B) + CAN_PS 3/11 (module A) ===")
    ch1=c_ulong(0); r1=d.PassThruConnect(dev,CAN,0,500000,byref(ch1)); print(f"  connect primary CAN rc={r1}")
    ch2=c_ulong(0); r2=d.PassThruConnect(dev,CAN_PS,0,500000,byref(ch2)); print(f"  connect CAN_PS rc={r2} {'' if r2==0 else err()}")
    if r2==0:
        print(f"  set 3/11 rc={setpins(ch2,3,11)} readback 0x22={getcfg(ch2,0x22):#06x} 0x23={getcfg(ch2,0x23):#06x}")
    passall(CAN,ch1); passall(CAN_PS,ch2)
    seenB=collections.Counter(); seenA=collections.Counter(); ctr=0; t0=time.time(); last=0.0
    while time.time()-t0<5.0:
        now=time.time()
        if now-last>=0.02:
            last=now; ctr=(ctr+1)&0xFF
            for cid in STIM[CAN]: tx(CAN,ch1,cid,ctr)
            for cid in STIM[CAN_PS]: tx(CAN_PS,ch2,cid,ctr)
        for proto,ch,seen in ((CAN,ch1,seenB),(CAN_PS,ch2,seenA)):
            rx=MSG(); cnt=c_ulong(1)
            if d.PassThruReadMsgs(ch,byref(rx),byref(cnt),1)==0 and cnt.value and rx.DataSize>=4:
                if rx.RxStatus & TX: continue
                seen[int.from_bytes(bytes(rx.Data[:4]),"big")]+=1
    rep("primary 6/14 (module B)",seenB); rep("CAN_PS 3/11 (module A)",seenA)
    d.PassThruDisconnect(ch1)
    if r2==0: d.PassThruDisconnect(ch2)
    d.PassThruClose(dev)

if __name__=="__main__": main()
