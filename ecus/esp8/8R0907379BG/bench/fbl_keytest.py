"""Test candidate FBL/flash key algorithms against the SBOOT level-1 verifier (27 01 -> 27 02,
back-to-back). 27 02 now does a real compare (invalidKey on wrong key), so we sweep candidates.
~3 attempts per power-cycle before lockout (power-cycle resets sa_lockout_counter). Use --start to
resume the candidate list across power-cycles, --n to cap attempts per run (default 3).

Each attempt: 27 01 -> seed ; immediately 27 02 <cand(seed)>  (no intervening frame).
Stop on 67 02 (unlock). SA2 from the SGO blob; also additive (+0x2909) in case the scheme is shared.

Usage:  fbl_keytest.py [--start 0] [--n 3]
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import Stim, LockedCAN, open_quiet, req_sid
from sa2_unlock import Sa2SeedKey, SA2_TAPE
from tp20_kwp import kfmt

M=0xffffffff
def bswap(x): return int.from_bytes(x.to_bytes(4,'big'),'little')
F=0x5FBD5DBD
def xrot(s,f=F,r=5):
    for _ in range(r):
        m=s&0x80000000; s=((s<<1)|(s>>31))&M
        if m: s^=f
    return s&M
def xshift(s,f=F,r=5):
    for _ in range(r):
        m=s&0x80000000; s=(s<<1)&M
        if m: s^=f
    return s&M

def sa2(s): return Sa2SeedKey(SA2_TAPE, s).execute()   # VM validated vs 3 independent vectors
def add(s,c): return ((s+c)&M)
# candidate = (label, fn(seed_be)->key_bytes). seed_be = wire seed as big-endian u32. ONE per
# power-cycle (--n 1): the FBL lockout trips after ~1 wrong key (recoverable, escalating wait).
# [0..2] finish the SGO-SA2 byte-order space; [3..8] = ADDITIVE with the module's own 6 constants
# (the module provably uses additive for coding; flash may reuse the scheme with another constant);
# [9..] misc login variants.
CANDS=[
  ("SGO-SA2 seedBE keyLE", lambda s: sa2(s).to_bytes(4,'little')),          # 0 (tested->invalidKey)
  ("SGO-SA2 seedLE keyBE", lambda s: sa2(bswap(s)).to_bytes(4,'big')),       # 1 (tested->invalidKey)
  ("SGO-SA2 seedLE keyLE", lambda s: sa2(bswap(s)).to_bytes(4,'little')),    # 2 (pending)
  ("add +0x2909 BE",       lambda s: add(s,0x2909).to_bytes(4,'big')),        # 3
  ("add +0x564f BE",       lambda s: add(s,0x564f).to_bytes(4,'big')),        # 4
  ("add +0x75fb BE",       lambda s: add(s,0x75fb).to_bytes(4,'big')),        # 5
  ("add +0x9ce8 BE",       lambda s: add(s,0x9ce8).to_bytes(4,'big')),        # 6
  ("add +0xefc2 BE",       lambda s: add(s,0xefc2).to_bytes(4,'big')),        # 7
  ("add +0xfe10 BE",       lambda s: add(s,0xfe10).to_bytes(4,'big')),        # 8
  ("rot5 F keyLE",         lambda s: xrot(s).to_bytes(4,'little')),           # 9
  ("shift5 F BE",          lambda s: xshift(s).to_bytes(4,'big')),            # 10
  ("add +0x11170 BE",      lambda s: add(s,0x11170).to_bytes(4,'big')),       # 11 (ecu_azx constant)
]

def reach_fbl(c, stim):
    """Drive to the FBL/level-1 context: operational stimulus -> 10 89 -> 10 85 (descent) -> reconnect."""
    stim.resume()
    tp=open_quiet(c,stim)
    if tp is None: return None
    tp.maintain(3.0)
    req_sid(tp,bytes.fromhex('1089'))
    r85=req_sid(tp,bytes.fromhex('1085'))
    if not (r85 and r85[0]==0x50): return None
    stim.resume(); time.sleep(0.4); tp.close(); tp=open_quiet(c,stim,keep_quiet=True)
    if tp is None: return None
    req_sid(tp,bytes.fromhex('1085'))
    return tp

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--start",type=int,default=0); ap.add_argument("--n",type=int,default=1)
    ap.add_argument("--bypass",action="store_true",help="on 0x36 lockout, ECUReset(11) + re-descend, then retry")
    a=ap.parse_args()
    c=LockedCAN(); stim=Stim(c,hz=8,ids=None); stim.start(); tp=None   # full set @8Hz ~41% - proven 10 85 balance
    def is36(r): return r and r[0]==0x7f and len(r)>2 and r[2]==0x36
    def bypass():
        nonlocal tp
        print("    [bypass] ECUReset(11 01) + re-descend ...")
        try: tp.request(bytes.fromhex('1101'))
        except Exception: pass
        time.sleep(1.5)
        try: tp.close()
        except Exception: pass
        tp=reach_fbl(c,stim)
        return tp is not None
    try:
        tp=reach_fbl(c,stim)
        if tp is None: print("  [!] could not reach FBL (power-cycle & retry)"); return
        print("  [*] FBL reached")
        end=min(a.start+a.n, len(CANDS))
        for i in range(a.start, end):
            label,fn=CANDS[i]
            sr=tp.request(bytes.fromhex('2701'))          # seed (no keepalive after)
            if not sr or sr[0]!=0x67 or len(sr)<6:
                if a.bypass and bypass(): sr=tp.request(bytes.fromhex('2701'))
                if not sr or sr[0]!=0x67 or len(sr)<6:
                    print(f"  [{i}] {label}: no seed ({kfmt(sr)}) - lockout; --bypass or power-cycle & --start {i}"); return
            seed=int.from_bytes(sr[2:6],'big'); kb=fn(seed)
            kr=tp.request(bytes([0x27,0x02])+kb)          # key (immediate)
            if is36(kr) and a.bypass and bypass():   # locked at key stage -> bypass + retry this candidate once
                sr=tp.request(bytes.fromhex('2701'))
                if sr and sr[0]==0x67 and len(sr)>=6:
                    seed=int.from_bytes(sr[2:6],'big'); kb=fn(seed); kr=tp.request(bytes([0x27,0x02])+kb)
            print(f"  [{i}] {label:18s} seed=0x{seed:08x} key={kb.hex(' ')} -> {kfmt(kr)}")
            if kr and kr[0]==0x67: print(f"  *** FBL UNLOCKED by candidate [{i}] {label} ***"); return
        print(f"  -- tried {a.start}..{end-1}; next: power-cycle & --start {end} --")
    finally:
        stim.stop=True; stim.join(timeout=1.0)
        try: tp.close()
        except Exception: pass
        c.close()

if __name__=="__main__": main()
