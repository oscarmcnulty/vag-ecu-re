#!/usr/bin/env python3
"""Probe the FBL / level-1 SecurityAccess (the post-10 85 reconnect context that issues 0xFD-prefixed
27 01 seeds). We know: 27 01 -> seed, 27 03/05.. -> subFnNotSupported, 27 02 -> subFnNotSupported.
Find which EVEN subfunction actually does a key compare (invalidKey vs subFnNotSupported), and test the
two candidate key algorithms on the level-1 seed:
  - SGO SA2  (ADD 0x974c58ab; EOR 0xfedcba98/0x98765432; ROR11)
  - additive +0x2909 (the level-3 algo, in case it's shared)

A subFunctionNotSupported (7F .. 12) costs NO lockout attempt; only a real wrong-key compare
(7F .. 35 invalidKey) costs one of ~3. We first map subfns with a DUMMY key (cheap), then on the
compare subfn send the real computed keys.

Usage (32-bit python, module power-cycled to state A):  fbl_probe.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import Stim, LockedCAN, open_quiet, req_sid
from sa2_unlock import Sa2SeedKey, SA2_TAPE
from tp20_kwp import kfmt

def seedof(r):
    return int.from_bytes(r[2:6],'big') if (r and r[0]==0x67 and len(r)>=6) else None

def main():
    c=LockedCAN(); stim=Stim(c,hz=50,ids=[0x200]); stim.start()   # 1-msg keepalive to pass 10 85 gate
    tp=None
    try:
        tp=open_quiet(c,stim)
        if tp is None: print("[!] TP open failed"); return
        tp.maintain(2.5)
        print(f"  10 89 -> {kfmt(req_sid(tp,bytes.fromhex('1089')))}")
        r85=req_sid(tp,bytes.fromhex('1085')); print(f"  10 85 -> {kfmt(r85)}")
        # descend + reconnect into the FBL context (stimulus stays on through the gap)
        stim.resume(); time.sleep(0.4); tp.close(); tp=open_quiet(c,stim,keep_quiet=True)
        if tp is None: print("[!] reconnect failed"); return
        print(f"  [*] reconnected (FBL) tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}")
        print(f"    10 85 -> {kfmt(req_sid(tp,bytes.fromhex('1085')))}")
        sr=req_sid(tp,bytes([0x27,0x01])); print(f"    27 01 seed -> {kfmt(sr)}")
        seed=seedof(sr)
        if seed is None: print("    [!] no level-1 seed in FBL"); return
        # (a) map which even subfn does a real compare, using a DUMMY key (subFnNotSupported=free)
        print("    -- subfn map (dummy key; 12=notsupported[free], 35=invalidKey[compare,burns]) --")
        compare_sf=None
        for sf in (0x02,0x04,0x06,0x08):
            r=tp.request(bytes([0x27,sf])+b'\xde\xad\xbe\xef'); tp.keepalive(force=True)
            print(f"      27 {sf:02x} dummy -> {kfmt(r)}")
            if r and r[0]==0x7f and len(r)>2 and r[2]==0x35: compare_sf=sf; break   # real compare here
            if r and r[0]==0x67: print("      *** unlocked with dummy?! ***"); return
        if compare_sf is None:
            print("    [!] no even subfn does a key compare in FBL (key path not here / needs 31/34 first)")
            return
        print(f"    [*] level-1 key subfunction = 27 {compare_sf:02x}; re-seed and send real keys")
        # (b) fresh seed, then send the SA2 key on the compare subfn
        sr=req_sid(tp,bytes([0x27,0x01])); seed=seedof(sr); print(f"    27 01 seed -> 0x{seed:08x}")
        sa2=Sa2SeedKey(SA2_TAPE,seed).execute(); kb=sa2.to_bytes(4,'big')
        print(f"    >>> 27 {compare_sf:02x} SA2 key {kb.hex(' ')} (0x{sa2:08x})")
        kr=tp.request(bytes([0x27,compare_sf])+kb); print(f"    -> {kfmt(kr)}")
        if kr and kr[0]==0x67: print("    *** FBL UNLOCKED with SGO SA2 ***"); return
    finally:
        stim.stop=True; stim.join(timeout=1.0)
        try: tp.close()
        except Exception: pass
        c.close()

if __name__=="__main__": main()
