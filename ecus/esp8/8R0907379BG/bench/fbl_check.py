#!/usr/bin/env python3
"""SAFE lockout-state check for the FBL/flash SecurityAccess. Reaches the FBL context and requests
ONLY the seed (27 01) - sends NO key, so it CANNOT burn a lockout attempt. Tells us whether the
0x36 (exceedNumberOfAttempts) lockout has cleared:
  27 01 -> 67 01 <seed>  => lockout cleared (seed requests allowed again)
  27 01 -> 7F 27 36      => still locked (wait longer / power-cycle+time)
Usage (32-bit python, module powered):  fbl_check.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import Stim, LockedCAN, open_quiet, req_sid
from tp20_kwp import kfmt

def main():
    c=LockedCAN(); stim=Stim(c,hz=50,ids=[0x200]); stim.start(); tp=None
    try:
        tp=open_quiet(c,stim); tp.maintain(2.5)
        print(f"  10 89 -> {kfmt(req_sid(tp,bytes.fromhex('1089')))}")
        print(f"  10 85 -> {kfmt(req_sid(tp,bytes.fromhex('1085')))}")
        stim.resume(); time.sleep(0.4); tp.close(); tp=open_quiet(c,stim,keep_quiet=True)
        if tp is None: print("[!] reconnect failed"); return
        print(f"  [*] FBL reconnect; 10 85 -> {kfmt(req_sid(tp,bytes.fromhex('1085')))}")
        r=req_sid(tp,bytes([0x27,0x01]))     # SEED ONLY - no key, no burn
        print(f"  27 01 (seed, no key) -> {kfmt(r)}")
        if r and r[0]==0x67: print("  => lockout CLEARED (seed requests allowed)")
        elif r and r[0]==0x7f and len(r)>2 and r[2]==0x36: print("  => still LOCKED (0x36) - wait longer")
        else: print("  => other state")
    finally:
        stim.stop=True; stim.join(timeout=1.0)
        try: tp.close()
        except Exception: pass
        c.close()

if __name__=="__main__": main()
