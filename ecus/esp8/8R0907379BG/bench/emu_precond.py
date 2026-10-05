#!/usr/bin/env python3
"""Emulate the module's running network context on the MAIN bus, then run the programming
precondition — testing whether 'operational context' (not a second CAN bus) is what clears
conditionsNotCorrect.

On the bench the module answers diag but reports conditionsNotCorrect to the 0x31 precondition
routine and to 14 FF FF. Hypothesis: the routine checks that the module is RUNNING/operational
(sees its vehicle network live), which never happens on a quiet bench bus. Here a background
thread continuously transmits the module's accepted RX ids (counter+CRC, the proven wake
stimulus) to hold it operational, while the foreground runs TP2.0+KWP: 10 89, knock, 31 C1
precondition, 14 FF FF, and the 10 85 descent — reporting whether conditionsNotCorrect clears.

SAFE: only the precondition ROUTINE is invoked (no params); no SecurityAccess key is sent; the
0xC4 erase routine is never called.

Run (32-bit python, ignition ON):  emu_precond.py [--warmup S] [--hz H]
"""
import argparse, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, ACCEPTED_IDS, crc8_j1850
from tp20_kwp import TP20KWP, kfmt

class LockedCAN(RawCAN):
    """RawCAN with a lock so a background stimulus thread and the foreground TP2.0 client can
    share the single J2534 channel handle safely."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._lk = threading.Lock()
    def read(self, timeout_ms=100):
        with self._lk: return super().read(timeout_ms)
    def write(self, cid, payload):
        with self._lk: return super().write(cid, payload)

class Stim(threading.Thread):
    """Continuously transmit the accepted-id set (counter+CRC) to keep the module operational."""
    def __init__(self, can, hz=20):
        super().__init__(daemon=True); self.c=can; self.hz=hz; self.stop=False; self.ctr=0; self.tx=0
    def run(self):
        period=1.0/self.hz
        while not self.stop:
            t=time.time(); self.ctr=(self.ctr+1)&0xFF
            for i,cid in enumerate(ACCEPTED_IDS):
                body=bytes([0,0,0,0,0,0x08,self.ctr])
                self.c.write(cid, body+bytes([crc8_j1850(body)])); self.tx+=1
                if i & 0x1f == 0x1f: time.sleep(0)   # yield lock periodically
            dt=period-(time.time()-t)
            if dt>0: time.sleep(dt)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--warmup",type=float,default=2.0)
    ap.add_argument("--hz",type=int,default=20); a=ap.parse_args()
    c=LockedCAN(); stim=Stim(c,a.hz); stim.start()
    print(f"[*] background stimulus running ({len(ACCEPTED_IDS)} ids @ {a.hz}Hz); warmup {a.warmup}s ...")
    time.sleep(a.warmup)
    tp=TP20KWP(c)
    try:
        if not tp.open():
            print("[!] TP2.0 open failed even with network stimulus — check bus/ignition"); return
        print(f"[*] TP2.0 OPEN  tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}  (stim tx={stim.tx})")
        steps=[("10 89 StartDiagSession","1089"),
               ("10 85 ProgrammingSession","1085"),
               ("14 FF FF ClearDTC","14FFFF"),
               ("31 C1 precondition routine","31C1"),
               ("31 B0 (alt precond)","31B0"),
               ("27 01 request seed","2701")]
        for label,hx in steps:
            r=tp.request(bytes.fromhex(hx)); tp.keepalive(force=True)
            print(f"  {label:32s} {hx:8s} -> {kfmt(r)}")
        print(f"[*] done (stim tx={stim.tx})")
    finally:
        stim.stop=True; time.sleep(0.1); tp.close(); c.close()

if __name__=="__main__": main()
