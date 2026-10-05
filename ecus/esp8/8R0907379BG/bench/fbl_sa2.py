#!/usr/bin/env python3
"""Flash-level (SBOOT/FBL) SecurityAccess attempt with the SGO SA2 key, sent 27 01 -> 27 02
BACK-TO-BACK with NO intervening frame (hypothesis: FBL subfn 02 is state-gated to fire only
immediately after a 27 01 in the same reconnected channel; a keepalive in between resets it).

Reaches the FBL: 1-msg stimulus to pass the 10 85 gate, 10 89, 10 85 (descent), reconnect. Then:
  tp.request(27 01) -> seed ; immediately tp.request(27 02 <SA2(seed)>)   [no keepalive between]
SA2 key from the SGO blob (sa2_unlock.Sa2SeedKey). One key send (never retried).

Usage (32-bit python, module power-cycled):  fbl_sa2.py [--keyle] [--seedle]
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import Stim, LockedCAN, open_quiet, req_sid
from sa2_unlock import Sa2SeedKey, SA2_TAPE
from tp20_kwp import kfmt

def sa2(seed):  # cross-check: closed-form of the SGO blob
    M=0xffffffff; s=(seed&M)+0x974c58ab; c=1 if s>M else 0; r=s&M
    r^=0xfedcba98 if c else 0x98765432
    for _ in range(11): r=((r>>1)|(r<<31))&M
    return r

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--keyle",action="store_true"); ap.add_argument("--seedle",action="store_true")
    a=ap.parse_args()
    c=LockedCAN(); stim=Stim(c,hz=50,ids=[0x200]); stim.start()
    tp=None
    try:
        tp=open_quiet(c,stim)
        if tp is None: print("[!] TP open failed"); return
        tp.maintain(2.5)
        print(f"  10 89 -> {kfmt(req_sid(tp,bytes.fromhex('1089')))}")
        print(f"  10 85 -> {kfmt(req_sid(tp,bytes.fromhex('1085')))}")
        stim.resume(); time.sleep(0.4); tp.close(); tp=open_quiet(c,stim,keep_quiet=True)
        if tp is None: print("[!] reconnect failed"); return
        print(f"  [*] FBL reconnect tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}")
        print(f"    10 85 -> {kfmt(req_sid(tp,bytes.fromhex('1085')))}")
        # --- the critical back-to-back pair: 27 01 then 27 02, NO frame in between ---
        sr=tp.request(bytes.fromhex('2701'))            # NOTE: no keepalive after this
        print(f"    27 01 seed -> {kfmt(sr)}")
        if not sr or sr[0]!=0x67 or len(sr)<6: print("    [!] no seed"); return
        seed=int.from_bytes(sr[2:6],'little' if a.seedle else 'big')
        kvm=Sa2SeedKey(SA2_TAPE,seed).execute(); kcf=sa2(seed)
        key=kvm; kb=key.to_bytes(4,'little' if a.keyle else 'big')
        print(f"    seed=0x{seed:08x} SA2(vm)=0x{kvm:08x} SA2(cf)=0x{kcf:08x} {'MATCH' if kvm==kcf else 'DIFFER'}")
        print(f"    >>> 27 02 {kb.hex(' ')} (immediate)")
        kr=tp.request(bytes([0x27,0x02])+kb)
        print(f"    27 02 -> {kfmt(kr)}")
        if kr and kr[0]==0x67: print("    *** FBL/FLASH UNLOCKED with SGO SA2 (67 02) ***")
    finally:
        stim.stop=True; stim.join(timeout=1.0)
        try: tp.close()
        except Exception: pass
        c.close()

if __name__=="__main__": main()
