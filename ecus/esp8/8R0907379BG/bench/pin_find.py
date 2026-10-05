#!/usr/bin/env python3
"""Find the SM2 CAN_PS pin-selection param + encoding, empirically.

GET_CONFIG on CAN_PS shows two params reading 0xffff (0x22, 0x23) while every other id is a
CAN/ISO timing value -> those two are the unassigned pin-select params (high-pin / low-pin).
We try each assignment strategy, read it back, then TX a stimulus + sniff 2s and report frame
count. 6/14 is a positive control (module B lives on OBD 6/14 and is traffic-wakeable); once a
strategy yields frames on 6/14 we know the mechanism, then 3/11 targets module A.

Run: tools\\py311x86\\python.exe bench\\pin_find.py
"""
import collections, ctypes, time
from ctypes import (POINTER, Structure, byref, c_char_p, c_ubyte, c_ulong, c_void_p,
                    create_string_buffer, pointer)
DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
CAN_PS = 0x8004; PASS_FILTER = 1; GET_CONFIG = 0x01; SET_CONFIG = 0x02; TX = 0x0001
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
def mk(cid,payload=b""):
    m=MSG(); m.ProtocolID=CAN_PS; data=cid.to_bytes(4,"big")+payload; m.DataSize=len(data)
    for i,x in enumerate(data): m.Data[i]=x
    return m
def getcfg(ch,pid):
    sc=SCONFIG(pid,0); scl=SCONFIG_LIST(1,pointer(sc))
    return (sc.Value if d.PassThruIoctl(ch,GET_CONFIG,byref(scl),None)==0 else None)
def setcfg_list(ch,pairs):
    arr=(SCONFIG*len(pairs))(*[SCONFIG(p,v) for p,v in pairs]); scl=SCONFIG_LIST(len(pairs),arr)
    return d.PassThruIoctl(ch,SET_CONFIG,byref(scl),None)

def sniff(ch,secs,stim):
    mask,patt=mk(0),mk(0); fid=c_ulong(0)
    d.PassThruStartMsgFilter(ch,PASS_FILTER,byref(mask),byref(patt),None,byref(fid))
    seen=collections.Counter(); ctr=0; t0=time.time(); last=0.0
    while time.time()-t0<secs:
        now=time.time()
        if now-last>=0.02:
            last=now; ctr=(ctr+1)&0xFF
            for cid in stim:
                body=bytes([0,0,0,0,0,0x08,ctr]); m=mk(cid,body+bytes([crc8(body)])); n=c_ulong(1)
                d.PassThruWriteMsgs(ch,byref(m),byref(n),20)
        rx=MSG(); cnt=c_ulong(1)
        if d.PassThruReadMsgs(ch,byref(rx),byref(cnt),2)==0 and cnt.value and rx.DataSize>=4:
            if rx.RxStatus & TX: continue
            seen[int.from_bytes(bytes(rx.Data[:4]),"big")]+=1
    return seen

def trial(dev,label,setpairs,stim,secs=2.0):
    ch=c_ulong(0)
    if d.PassThruConnect(dev,CAN_PS,0,500000,byref(ch))!=0:
        print(f"[{label}] connect FAIL {err()}"); return
    rc=setcfg_list(ch,setpairs) if setpairs else 0
    rb=" ".join(f"0x{p:02x}->{(getcfg(ch,p)):#06x}" for p,_ in setpairs) if setpairs else "(none)"
    seen=sniff(ch,secs,stim)
    tot=sum(seen.values())
    ids=" ".join(f"0x{c:03x}x{seen[c]}" for c in sorted(seen)[:12])
    print(f"[{label}] set rc={rc} readback[{rb}]  RX={tot} frames  {ids}")
    d.PassThruDisconnect(ch)

def main():
    dev=c_ulong(0); assert d.PassThruOpen(None,byref(dev))==0
    stimB=[0x000,0x0a0,0x0c0,0x100,0x280,0x288]   # module B bus wake ids
    stimA=[0x100,0x101,0x1a0,0x200,0x0a0,0x0c0]   # module A bus wake ids
    print("=== POSITIVE CONTROL: assign CAN_PS to 6/14 (module B, known live) ===")
    trial(dev,"6/14 combined@0x22=0x060e", [(0x22,0x060E)], stimB)
    trial(dev,"6/14 separate 0x22=6,0x23=14", [(0x22,6),(0x23,14)], stimB)
    trial(dev,"6/14 combined@0x22=0x0e06", [(0x22,0x0E06)], stimB)
    print("=== TARGET: assign CAN_PS to 3/11 (module A) ===")
    trial(dev,"3/11 combined@0x22=0x030b", [(0x22,0x030B)], stimA)
    trial(dev,"3/11 separate 0x22=3,0x23=11", [(0x22,3),(0x23,11)], stimA)
    trial(dev,"3/11 combined@0x22=0x0b03", [(0x22,0x0B03)], stimA)
    d.PassThruClose(dev)

if __name__=="__main__": main()
