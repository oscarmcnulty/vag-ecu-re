#!/usr/bin/env python3
"""Option 2: after the CODING unlock (key=seed+0x2909), test whether the flash-WRITE/READ transfer
services are gated by the coding SA (which we can satisfy) or the flash SA (SBOOT, which we can't).
Probes (NON-destructive: NO TransferData 36, NO erase routine, NO RequestTransferExit):
  - 34 RequestDownload (app session, table A) in several KWP layouts -> 74 = coding-gated (WIN:
    patched-firmware write path open); 7F 90/33 = needs flash SA.
  - 35 RequestUpload likewise (74/75 = a READ/dump path open with the key we have).
A bare 34/35 declares intent only; erase on VAG is a separate 31 routine / first 36 block, so this
does not modify flash. Reports every NRC.

Usage (32-bit python, module power-cycled to state A):  flash_probe.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN
from tp20_kwp import TP20KWP, kfmt

def main():
    c=RawCAN(); tp=TP20KWP(c)
    def rq(hx): r=tp.request(bytes.fromhex(hx)); tp.keepalive(force=True); return r
    try:
        if not tp.open(): print("[!] TP open failed"); return
        print(f"[*] OPEN; 10 89 -> {kfmt(rq('1089'))}")
        sr=rq('2703')
        if not sr or sr[0]!=0x67 or len(sr)<6: print(f"  [!] no coding seed: {kfmt(sr)}"); return
        seed=int.from_bytes(sr[2:6],'big'); kb=((seed+0x2909)&0xffffffff).to_bytes(4,'big')
        kr=tp.request(bytes([0x27,0x04])+kb); tp.keepalive(force=True)
        print(f"  27 03/04 coding unlock -> {kfmt(kr)}")
        if not (kr and kr[0]==0x67): print("  [!] coding unlock failed"); return
        print("  *** CODING UNLOCKED *** now probe transfer services (no 36/erase)")
        # 34 RequestDownload layouts (addr=0x000000, tiny size) - declares intent only
        print("  -- 34 RequestDownload --")
        for label,hx in [("34 a3=000000 fmt00 s3=000010","3400000000000010"),
                         ("34 fmt00 a3 s3","3400 000000 000010".replace(' ','')),
                         ("34 a3 s1","3400000010"),
                         ("34 fmt00 alfid44 a4 s4","340044 00000000 00000010".replace(' ',''))]:
            print(f"    {label:30s} [{hx}] -> {kfmt(rq(hx))}")
        print("  -- 35 RequestUpload --")
        for label,hx in [("35 a3=000000 fmt00 s3=000010","3500000000000010"),
                         ("35 fmt00 alfid44 a4 s4","350044 00000000 00000010".replace(' ',''))]:
            print(f"    {label:30s} [{hx}] -> {kfmt(rq(hx))}")
        # also: does entering programming session 10 85 preserve the coding grant for 34?
        print("  -- 10 85 (same channel) then 34 --")
        r85=rq('1085'); print(f"    10 85 -> {kfmt(r85)}")
        if r85 and r85[0]==0x50:
            print(f"    34 [3400000000000010] -> {kfmt(rq('3400000000000010'))}")
    finally:
        tp.close(); c.close()

if __name__=="__main__": main()
