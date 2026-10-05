#!/usr/bin/env python3
"""Probe + wake module A on the SM2's 2nd CAN channel (CAN_PS, OBD 3/11 -> module A T38a 37/24).
(a) GET_CONFIG dump to find the J1962_PINS param id + current pin encoding, then set pins to 3/11.
(b) Actively transmit traffic on CAN2 (module A boots dormant; the 0x060 heartbeat only starts once
    it sees bus activity) while sniffing for module A's response.

Run: tools\\py311x86\\python.exe bench\\can2_probe.py [--secs N]
"""
import argparse, collections, ctypes, time
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
    rc=d.PassThruIoctl(ch,GET_CONFIG,byref(scl),None)
    return (sc.Value if rc==0 else None)
def setcfg(ch,pid,val):
    sc=SCONFIG(pid,val); scl=SCONFIG_LIST(1,pointer(sc))
    return d.PassThruIoctl(ch,SET_CONFIG,byref(scl),None)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--secs",type=float,default=6.0); a=ap.parse_args()
    dev=c_ulong(0); assert d.PassThruOpen(None,byref(dev))==0
    ch=c_ulong(0); rc=d.PassThruConnect(dev,CAN_PS,0,500000,byref(ch))
    print(f"connect CAN_PS rc={rc} {'' if rc==0 else err()}")
    if rc!=0: d.PassThruClose(dev); return
    # (a) GET_CONFIG dump: find which param holds a pin-pair value (look for 0x060e=6/14 or 0x030b=3/11)
    print("=== GET_CONFIG dump (param id -> value) ===")
    pin_param=None; pinset={1,2,3,6,9,10,11,12,13,14}
    ids=list(range(0x01,0x81))+list(range(0x8000,0x8041))
    for pid in ids:
        v=getcfg(ch,pid)
        if v is not None:
            hi,lo=(v>>8)&0xff, v&0xff
            note=""
            if hi in pinset and lo in pinset and hi!=lo:
                note=f"  <-- looks like pins {hi}/{lo}"
                if pin_param is None: pin_param=pid
            if v==0xffff: note+="  <-- 0xffff (unset? pin candidate)"
            print(f"  0x{pid:04x} = 0x{v:08x}{note}")
    # set pins to 3/11 on the discovered param (try both encodings)
    if pin_param is not None:
        for val in (0x030B,0x0B03):
            if setcfg(ch,pin_param,val)==0:
                print(f"[pins] set param 0x{pin_param:02x} = 0x{val:04x} (3/11) OK"); break
    else:
        print("[pins] no pin-pair param found via GET_CONFIG; CAN_PS may default to 3/11")
    # pass-all filter
    mask,patt=mk(0),mk(0); fid=c_ulong(0)
    d.PassThruStartMsgFilter(ch,PASS_FILTER,byref(mask),byref(patt),None,byref(fid))
    # (b) wake: transmit traffic on CAN2 while sniffing (module A heartbeat is traffic-triggered)
    print(f"=== wake+sniff CAN2 {a.secs}s (TX stimulus on module A bus) ===")
    stim=[0x100,0x101,0x1a0,0x200,0x0a0,0x0c0]; ctr=0; seen=collections.Counter(); sample={}
    t0=time.time(); last=0.0
    while time.time()-t0<a.secs:
        now=time.time()
        if now-last>=0.02:   # ~50 Hz stimulus
            last=now; ctr=(ctr+1)&0xFF
            for cid in stim:
                body=bytes([0,0,0,0,0,0x08,ctr]);
                m=mk(cid,body+bytes([crc8(body)])); n=c_ulong(1)
                d.PassThruWriteMsgs(ch,byref(m),byref(n),20)
        rx=MSG(); cnt=c_ulong(1)
        if d.PassThruReadMsgs(ch,byref(rx),byref(cnt),2)==0 and cnt.value and rx.DataSize>=4:
            if rx.RxStatus & TX: continue
            cid=int.from_bytes(bytes(rx.Data[:4]),"big")
            seen[cid]+=1; sample.setdefault(cid,bytes(rx.Data[4:rx.DataSize]).hex(" "))
    print(f"RX on CAN2: {sum(seen.values())} frames, {len(seen)} ids")
    for cid in sorted(seen): print(f"  0x{cid:03x} x{seen[cid]:<5d} {sample[cid]}")
    if not seen: print("  (none - module A silent: check 3/11 wiring+120ohm, or needs module B/vehicle context too)")
    d.PassThruDisconnect(ch); d.PassThruClose(dev)

if __name__=="__main__": main()
