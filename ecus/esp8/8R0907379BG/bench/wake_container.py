#!/usr/bin/env python3
"""ESP8 (8R0907379BG) targeted wake: 0x40c container with 0x600 sub-PDU byte1 bit5 set.

Gate logic (fully reversed, see docs/operational_gate_trace.md): can_tx_scheduler broadcasts
ESP_01/02/08 iff comm_enable_flag(0x40944c)==1 (trivial) AND tx_gate2(0x409438)!=0, where
tx_gate2 = bit21 of COM signal 0x046f (0x408f10) = **byte1 bit5 (0x20) of the 4-byte sub-PDU
0x600** carried in the 23-byte container on CAN-id 0x40c. So the wake frame is the 0x40c
container whose 0x600 sub-PDU value has byte1=0x20 (node byte0 in {0x4a,5f,98,99,9a,d4}).

This tries several container byte-layouts x multi-frame framings (single-frame, ISO-TP FF+CF)
with the 0x600 value = [node,0x20,00,00], watching for the ECU to leave 0x060-only (any new tx
id = it went operational). Run with 32-bit python.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, crc8_j1850

NODE = 0x5f
def sub600(node): return bytes([node,0x20,0x00,0x00])   # byte1 bit5 -> tx_gate2

def containers(node):
    s6 = sub600(node)
    outs = []
    # Layout A: [len][subid06 00][4data] per sub-PDU, concatenated, padded to 23
    a = bytes([0x07])+bytes([0x06,0x00])+s6 + bytes([0x06,0xf1,0xa3,0,0,0]) + bytes([0x0b,0xf1,0xa4,0,0,0,0,0,0,0,0])
    outs.append(("A", a[:23].ljust(23,b"\0")))
    # Layout B: [len16][subid16][data]
    b = bytes([0,0x07,0x06,0x00])+s6 + bytes([0,0x06,0xf1,0xa3,0,0,0]) + bytes([0,0x0b,0xf1,0xa4,0,0,0,0])
    outs.append(("B", b[:23].ljust(23,b"\0")))
    # Layout C: just 0x600 first with node+bit21, rest zero
    c = bytes([0x06,0x00])+s6 + bytes(23-6)
    outs.append(("C", c[:23]))
    # Layout D: container with J1850 CRC in last byte
    d = bytearray(a[:23].ljust(23,b"\0")); d[-1]=crc8_j1850(bytes(d[:22]))
    outs.append(("D-crc", bytes(d)))
    return outs

def send_multiframe(c, cid, payload):
    # ISO-TP FF + CF
    n=len(payload)
    c.write(cid, bytes([0x10, n & 0xff])+payload[:6])
    idx=6; sn=1
    while idx < n:
        c.write(cid, bytes([0x20|(sn&0xf)])+payload[idx:idx+7].ljust(7,b"\0"))
        idx+=7; sn+=1

def send_single(c, cid, payload):
    # single frame (first 7 bytes) - in case ECU accepts short container
    c.write(cid, payload[:8] if len(payload)>=8 else payload.ljust(8,b"\0"))

def run(secs_each=2.0):
    c=RawCAN()
    base=set()
    t=time.time()
    while time.time()-t<1.0:
        r=c.read(10)
        if r and r[0]!=0x060: base.add(r[0])
    print("baseline non-0x060 ids:", [hex(x) for x in base] or "none (only 0x060)")
    for name,cont in containers(NODE):
        for mode,fn in [("FF+CF",send_multiframe),("single",send_single)]:
            newids=set(); b5=set()
            t=time.time(); last=0
            while time.time()-t<secs_each:
                now=time.time()
                if now-last>=0.02:
                    last=now; fn(c,0x40c,cont)
                r=c.read(1)
                if r:
                    rid,pl=r
                    if rid==0x060:
                        if len(pl)>5: b5.add(pl[5])
                    elif rid not in base:
                        newids.add((hex(rid),pl.hex()))
            flag = "*** WAKE ***" if newids else ("byte5!" if (b5-{0x08}) else "")
            print(f"  layout {name:6s} {mode:7s}: new={list(newids)[:4] or '-'} b5={sorted(hex(x) for x in b5)} {flag}")
    c.close()

if __name__=="__main__":
    run()
