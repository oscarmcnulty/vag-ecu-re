#!/usr/bin/env python3
"""Path A: after the CODING unlock (level-3, key=seed+0x2909), map what memory-read primitives open.
Non-destructive: coding key is the CORRECT key (not a guess), and all probes are reads (21/22/2C/23/
35/36) - no writes, no erase, no flash-SA guessing. Tries, in the app session (10 89) and the upload
session (10 86, which the coding grant enables):
  - 21 ReadDataByLocalId sweep (find ids returning large/memory data)
  - 2C DynamicallyDefineLocalId (define a memory window) + 21 read it
  - 35 RequestUpload (several layouts) + 36 TransferData
  - 23 ReadMemoryByAddress (recheck with coding grant active)
Prints every response so we can see which path is ungated.

Usage (32-bit python, module power-cycled):  read_probe.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN
from tp20_kwp import TP20KWP, kfmt

def main():
    c=RawCAN(); tp=TP20KWP(c)
    def rq(hx):
        r=tp.request(bytes.fromhex(hx)); tp.keepalive(force=True); return r
    try:
        if not tp.open(): print("[!] TP open failed"); return
        print(f"[*] OPEN tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}")
        print(f"  10 89 -> {kfmt(rq('1089'))}")
        sr=rq('2703'); print(f"  27 03 seed -> {kfmt(sr)}")
        if not sr or sr[0]!=0x67 or len(sr)<6: print("  [!] no coding seed"); return
        seed=int.from_bytes(sr[2:6],'big'); kb=((seed+0x2909)&0xffffffff).to_bytes(4,'big')
        kr=tp.request(bytes([0x27,0x04])+kb); tp.keepalive(force=True)
        print(f"  27 04 key {kb.hex(' ')} -> {kfmt(kr)}")
        if not (kr and kr[0]==0x67): print("  [!] coding unlock failed"); return
        print("  *** CODING UNLOCKED ***")
        print("  -- 21 ReadDataByLocalId sweep (app session) --")
        for lid in (0x01,0x02,0x03,0x0f,0x10,0x80,0xa0,0xc0,0xf0,0xfc,0xfd,0xfe,0xff):
            r=rq(f"21{lid:02x}")
            if r and (r[0]==0x61 or (r[0]==0x7f and r[2] not in (0x11,0x12))):
                print(f"    21 {lid:02x} -> {kfmt(r)[:70]}")
        print("  -- 2C DynamicallyDefineLocalId (define mem window) + 21 read --")
        for label,hx in [("2C F0 mode03 addr3 size","2CF003000100 04".replace(' ','')),
                         ("2C F0 mode03 size addr3","2CF00304 000100".replace(' ','')),
                         ("2C F0 03 pos size addr","2CF003 01 04 000100".replace(' ','')),
                         ("2C F0 mode04 addr4 size","2CF004 00000100 04".replace(' ',''))]:
            r=rq(hx); print(f"    {label:26s} [{hx}] -> {kfmt(r)}")
            if r and r[0]==0x6c:
                print(f"      define OK -> 21 F0 -> {kfmt(rq('21F0'))}")
        print("  -- 35 RequestUpload (app session) --")
        for hx in ("3500010010","35000100000010","350044000001000000 0010".replace(' ','')):
            print(f"    35 [{hx}] -> {kfmt(rq(hx))}")
        print("  -- 10 86 upload session, then 35/36 --")
        r86=rq('1086'); print(f"    10 86 -> {kfmt(r86)}")
        if r86 and r86[0]==0x50:
            for hx in ("3500010010","35000100000010"):
                ru=rq(hx); print(f"    35 [{hx}] -> {kfmt(ru)}")
                if ru and ru[0]==0x75: print(f"      upload OK -> 36 -> {kfmt(rq('36'))}")
        print("  -- 23 ReadMemoryByAddress recheck (coding grant active) --")
        for hx in ("2300010010","230000010010"):
            print(f"    23 [{hx}] -> {kfmt(rq(hx))}")
    finally:
        tp.close(); c.close()

if __name__=="__main__": main()
