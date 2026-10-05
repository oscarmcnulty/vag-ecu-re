#!/usr/bin/env python3
"""ESP8 (8R0907379BG) KWP2000 SecurityAccess UNLOCK - level 3, recovered from firmware RE.

The real SA is LEVEL 3 (27 03 request seed / 27 04 send key) in the application session, handled by
FUN_00084cd4 in the ASW image. The key transform is a simple additive constant (emulator-verified):

    key = (seed + 0x2909) & 0xFFFFFFFF      # seed+key big-endian on the wire

The handler accepts 6 valid keys (seed + different const), each granting a different sec_access_state
(0x4079e4) bit; seed+0x2909 sets the primary bit 0x20000000. --const picks which (default 0x2909).

After unlock this probes what opened: re-reads identification, tries SID 23 ReadMemoryByAddress in the
app session and (optionally) after 10 85, to see if the memory-read / dump primitive is now ungated.

SAFE: one key send per run (never retried). A wrong key costs 1 of ~3 lockout attempts (power-cycle
resets sa_lockout_counter). No writes/erase. Requires a freshly power-cycled module (state A).

Usage (32-bit python, ignition ON, module power-cycled):
  esp_unlock.py                 # unlock with +0x2909 and probe
  esp_unlock.py --const 0x75fb  # try an alternate grant bit
  esp_unlock.py --dumptest      # after unlock, read a few memory windows to validate the dump path
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN
from tp20_kwp import TP20KWP, kfmt

KEYS = {0x2909:"bit29(primary)",0x564f:"bit9",0x75fb:"bit25",0x9ce8:"bit24",0xefc2:"bit10",0xfe10:"bit26"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--const",default="0x2909"); ap.add_argument("--dumptest",action="store_true")
    a=ap.parse_args(); const=int(a.const,16)
    c=RawCAN(); tp=TP20KWP(c)
    try:
        if not tp.open(): print("[!] TP2.0 open failed - ignition ON?"); return
        print(f"[*] channel OPEN tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}")
        print(f"  10 89 -> {kfmt(tp.request(bytes.fromhex('1089')))}"); tp.keepalive(force=True)
        sr=tp.request(bytes.fromhex('2703')); print(f"  27 03 (seed) -> {kfmt(sr)}")
        if not sr or sr[0]!=0x67 or len(sr)<6:
            print("  [!] no level-3 seed"); return
        seed=int.from_bytes(sr[2:6],'big'); key=(seed+const)&0xffffffff
        kb=key.to_bytes(4,'big')
        print(f"      seed=0x{seed:08x}  key=seed+0x{const:x}=0x{key:08x} ({kb.hex(' ')})  [{KEYS.get(const,'?')}]")
        kr=tp.request(bytes([0x27,0x04])+kb)             # single send, never retried
        print(f"  >>> 27 04 (key) -> {kfmt(kr)}")
        if not (kr and kr[0]==0x67):
            print("  [!] not unlocked (if invalidKey, a power-cycle resets the lockout to retry)"); return
        print("  *** SECURITYACCESS LEVEL 3 UNLOCKED (67 04) ***")
        tp.keepalive(force=True)
        # ---- SAME-CHANNEL post-unlock exploration (no reconnect - preserve the grant) ----
        def rtry(hx,tries=4):
            r=None
            for _ in range(tries):
                r=tp.request(bytes.fromhex(hx)); tp.keepalive(force=True)
                if r is not None and not (r[0]==0x50 and len(r)>1 and r[1]!=int(hx[2:4],16)): return r
            return r
        print("  -- same-channel: sessions enabled by the grant, then read primitives --")
        for sess in ("1086","1085","1083","1084"):
            rs=rtry(sess); print(f"    {sess} -> {kfmt(rs)}")
            if rs and rs[0]==0x50:
                for label,hx in [("23 @100 l16","2300010010"),("23 @0 l16","2300000010"),
                                 ("35 up @100","35000100000010"),("3D? skip","")]:
                    if not hx: continue
                    print(f"      {label:12s} [{hx}] -> {kfmt(rtry(hx))}")
        print("  -- also: dynamic-id / direct reads in current session --")
        for label,hx in [("21 01","2101"),("2C define","2C F0 03 01 00 0100 10".replace(' ','')),
                         ("21 F0","21F0"),("23 @100 l4","2300010004")]:
            print(f"    {label:12s} [{hx}] -> {kfmt(rtry(hx))}")
    finally:
        tp.close(); c.close()

if __name__=="__main__": main()
