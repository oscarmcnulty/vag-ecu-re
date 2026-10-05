#!/usr/bin/env python3
"""Full bench unlock path with the main-bus operational emulation (threaded stimulus).

emu_precond proved that holding the module operational (a background stimulus of its accepted RX
ids) turns 10 85 ProgrammingSession from conditionsNotCorrect into 50 85 -> the programming gate
is open. 10 85 then drops the TP2.0 channel as the module descends toward the boot loader, so we
RECONNECT (stimulus still flowing) and request the SecurityAccess seed in the programming context,
then compute the key with the SA2 bytecode recovered from the OEM SGO.

The stimulus runs in a background thread (concurrent read/write is what the module needs to see a
live network; a single-threaded 225-frame burst before each read instead buries the diag frames).
The Scanmatik DLL is NOT safe when two threads enter it at once, so: (1) every DLL call goes through
a lock, and (2) the stim thread is PAUSED around TP open (which issues an unlocked CLEAR_RX_BUFFER
ioctl) and around shutdown. open() also runs on a quiet bus (the setup handshake is timing-sensitive).

SAFE BY DEFAULT: dry-run — requests the seed and prints the computed key but sends NOTHING
(sending a key costs one of ~3 attempts before lockout). --send actually transmits the key.

Run (32-bit python, ignition ON, module in state A i.e. freshly power-cycled):
  emu_unlock.py                 # dry-run up to computed key
  emu_unlock.py --send          # also send the key (uses one lockout attempt)
"""
import argparse, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, ACCEPTED_IDS, crc8_j1850
from tp20_kwp import TP20KWP, kfmt
from sa2_unlock import Sa2SeedKey, SA2_TAPE

class LockedCAN(RawCAN):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._lk=threading.Lock()
    def read(self, t=100):
        with self._lk: return super().read(t)
    def write(self, cid, pl):
        with self._lk: return super().write(cid, pl)

class Stim(threading.Thread):
    """Continuously transmit the accepted-id set (counter+CRC) to hold the module operational.
    Pausable so the foreground can safely run TP open()/ioctls with no 2nd thread in the DLL."""
    def __init__(self, can, hz=8, ids=None, payloads=None):
        # hz = full passes/sec. One 225-id pass is ~52ms of 500k bus time, so 20Hz (period 50ms)
        # is ~100% busload and starves diag. 8Hz (period 125ms) is ~42% -> leaves headroom. A small
        # ids subset lowers busload dramatically so diag runs clean alongside. payloads = optional
        # {cid: bytes7} for ids that need specific content (e.g. the NM container's node-id bytes);
        # ids without an entry get the generic 00..00 08 CTR + CRC E2E frame.
        super().__init__(daemon=True); self.c=can; self._period=1.0/hz
        self.ids=list(ids) if ids else list(ACCEPTED_IDS)
        self.payloads=payloads or {}
        self.stop=False; self.paused=True; self.ctr=0; self.tx=0
    def run(self):
        while not self.stop:
            if self.paused: time.sleep(0.005); continue
            t=time.time(); self.ctr=(self.ctr+1)&0xFF
            gen=bytes([0,0,0,0,0,0x08,self.ctr]); genframe=gen+bytes([crc8_j1850(gen)])
            for cid in self.ids:
                if self.paused or self.stop: break
                if cid in self.payloads:
                    body=bytes(self.payloads[cid][:6])+bytes([self.ctr])   # ctr in byte6
                    frame=body+bytes([crc8_j1850(body)])
                else:
                    frame=genframe
                self.c.write(cid, frame); self.tx+=1
            end=t+self._period
            while time.time()<end and not self.stop and not self.paused: time.sleep(0.003)
    def pause(self):  self.paused=True;  time.sleep(0.02)   # let an in-flight batch drain
    def resume(self): self.paused=False

def open_quiet(c, stim, keep_quiet=False):
    """TP2.0 open with stimulus paused (quiet bus + no 2nd thread in the DLL). Resumes the stimulus
    afterwards unless keep_quiet (bootloader phase: the boot loader doesn't monitor the restbus, so
    we stay silent to give the flash channel the whole bus)."""
    stim.pause()
    tp=TP20KWP(c); ok=tp.open()
    if not keep_quiet: stim.resume()
    return tp if ok else None

def seedinfo(r):
    if r and r[0]==0x67 and len(r)>=6: return "SEED "+r[2:6].hex(' ')
    return kfmt(r)

def _readtest(tp, where):
    """Non-destructive probe for a working ReadMemoryByAddress (23) primitive in the given session.
    Tries several KWP request layouts against known flash @0x000100; a 0x63 positive with matching
    bytes = we have a memory-read primitive (then we can hunt SBOOT). 0x33/0x90 = gated (needs SA)."""
    import os as _os
    try:
        fwp=_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                          "firmware","8R0907379BG_0030.bin")
        known=open(fwp,"rb").read()[0x100:0x110].hex(' ')
    except Exception:
        known="(fw not found)"
    print(f"  [*] read-primitive probe in {where}; flash@0x000100 = {known}")
    trials=[
        ("23 addr3=000100 len1=10",   "2300010010"),
        ("23 addr3=000100 len2=0010", "230001000010"),
        ("23 addr4=00000100 len1=10", "230000010010"),
        ("23 ALFID14 addr4 len1",     "23140000010010"),
        ("23 ALFID24 addr3 len2",     "23240001000010"),
    ]
    for label,hx in trials:
        r=req_sid(tp,bytes.fromhex(hx),tries=4); tp.keepalive(force=True)
        print(f"    {label:26s} [{hx}] -> {kfmt(r)}")

def req_sid(tp, kwp, tries=4, timeout=2.0):
    """Send a KWP request, retrying through stale/lost frames (the stimulus flood occasionally
    misaligns RX). Accepts a positive response whose echoed SID matches, or any real 7F NRC."""
    r=None
    for _ in range(tries):
        r=tp.request(kwp, timeout); tp.keepalive(force=True)
        if r is None: continue
        if r[0]==0x7f: return r                                   # genuine NRC
        if r[0]==0x40|kwp[0] and (len(kwp)<2 or (len(r)>1 and r[1]==kwp[1])): return r
        # else stale/mismatched frame -> retry
    return r

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--warmup",type=float,default=3.0); ap.add_argument("--hz",type=int,default=8)
    ap.add_argument("--send",action="store_true"); ap.add_argument("--level",type=int,default=1)
    ap.add_argument("--probe",action="store_true",help="enumerate 27 subfunctions (no key sent)")
    ap.add_argument("--seed-le",action="store_true"); ap.add_argument("--op-le",action="store_true")
    ap.add_argument("--key-le",action="store_true")
    ap.add_argument("--readtest",action="store_true",help="after 10 85, probe ReadMemoryByAddress (23) - non-destructive")
    ap.add_argument("--ids",default="",help="comma hex stimulus-id subset (default all 225 accepted ids)")
    a=ap.parse_args()
    seed_sf=a.level; key_sf=a.level+1
    ids=[int(x,16) for x in a.ids.replace(" ","").split(",") if x] or None
    c=LockedCAN(); stim=Stim(c,a.hz,ids=ids); stim.start()
    if ids: print(f"[*] stimulus restricted to {len(ids)} ids: {[hex(i) for i in ids]}")
    tp=None
    print(f"[*] stimulus {len(ACCEPTED_IDS)} ids @ {a.hz} passes/s (~{int(len(ACCEPTED_IDS)*0.23*a.hz/10)}% busload)")
    try:
        # ---- Phase 1 (application, stimulus ON): descend to the boot loader via 10 85 ----
        tp=open_quiet(c,stim)
        if tp is None: print("[!] TP2.0 open failed"); return
        print(f"[*] TP2.0 OPEN tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}; warmup {a.warmup}s operational ...")
        tp.maintain(a.warmup)
        print(f"  10 89 -> {kfmt(req_sid(tp,bytes.fromhex('1089')))}")
        if a.readtest:
            _readtest(tp,"app session (10 89)")   # then fall through: descend + reconnect, probe in FBL
        r85=req_sid(tp,bytes.fromhex('1085')); print(f"  10 85 -> {kfmt(r85)}")
        if not (r85 and r85[0]==0x50 and len(r85)>1 and r85[1]==0x85):
            print("  [!] programming session refused this run (need fresh power-cycle to state A)"); return
        # ---- Phase 2a: SecurityAccess on the SAME channel (programming session, app still running
        #      -> keep the low restbus stimulus so it stays operational). The factory does SA inside
        #      the programming session; the reconnect below was likely the mistake. ----
        ctx="same-channel programming session"
        sr=req_sid(tp,bytes([0x27,seed_sf]))
        if not (sr and sr[0]==0x67 and len(sr)>=6):
            # ---- Phase 2b: no seed here / channel dropped -> boot loader: silence bus, reconnect ----
            print(f"  [*] same-channel 27 {seed_sf:02x} -> {seedinfo(sr)}; reconnecting (bus silent) ...")
            stim.pause(); ctx="reconnected boot-loader context"; sr=None
            for attempt in range(4):
                time.sleep(0.4); tp.close(); tp=open_quiet(c,stim,keep_quiet=True)
                if tp is not None:
                    print(f"  [*] reconnected tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x}")
                    print(f"    10 85 -> {kfmt(req_sid(tp,bytes.fromhex('1085')))}")
                    sr=req_sid(tp,bytes([0x27,seed_sf])); break
                print(f"  [*] reconnect attempt {attempt+1} failed")
        else:
            print(f"  [*] seed on SAME channel, no reconnect -> {ctx}")
        if a.probe:
            print(f"  [*] probing 27 seed subfunctions in {ctx} (odd only; no key) ...")
            for sf in (0x01,0x03,0x05,0x07,0x09,0x0b,0x0d,0x0f,0x11):
                rp=req_sid(tp,bytes([0x27,sf]),tries=2); tp.keepalive(force=True)
                print(f"    27 {sf:02x} -> {seedinfo(rp)}")
            return
        print(f"  27 {seed_sf:02x} (seed) -> {seedinfo(sr)}  [{ctx}]")
        if a.readtest:
            # clean bus now (few-id stimulus) + we're in the live post-descent context where 27 01
            # works -> this is where ReadMemoryByAddress (table B / 23) should answer if it can.
            _readtest(tp, ctx+" [post-descent, clean bus]")
            # also try alternate reads that may be the real dump primitive in this context
            for label,hx in [("3D WriteMem? (skip)","" ),("21 readLocalId 01","2101"),
                             ("23 small@000000 len1","2300000001"),("23 @000100 len4","2300010004")]:
                if not hx: continue
                rr=req_sid(tp,bytes.fromhex(hx),tries=3); tp.keepalive(force=True)
                print(f"    {label:22s} [{hx}] -> {kfmt(rr)}")
            return
        if not sr or sr[0]!=0x67 or len(sr)<6:
            print("  [!] no seed in either context"); return
        seed=int.from_bytes(sr[2:6],'little' if a.seed_le else 'big')
        key=Sa2SeedKey(SA2_TAPE,seed,le_operand=a.op_le).execute()
        kb=key.to_bytes(4,'little' if a.key_le else 'big')
        bo=f"seed{'LE' if a.seed_le else 'BE'}/op{'LE' if a.op_le else 'BE'}/key{'LE' if a.key_le else 'BE'}"
        print(f"      seed=0x{seed:08x}  KEY=0x{key:08x} ({kb.hex(' ')})  [SA2 from SGO; {bo}]")
        if a.send:
            print(f"  >>> SENDING 27 {key_sf:02x} {kb.hex(' ')}  [{ctx}]")
            kr=tp.request(bytes([0x27,key_sf])+kb, timeout=3.0)   # single send — never retry a key
            print(f"  27 {key_sf:02x} -> {kfmt(kr)}")
            if kr and kr[0]==0x67: print("  *** UNLOCKED ***")
        else:
            print(f"  [dry-run] would send 27 {key_sf:02x} {kb.hex(' ')}  (re-run --send)")
    finally:
        stim.stop=True; stim.join(timeout=1.0)
        try: tp.close()
        except Exception: pass
        c.close()

if __name__=="__main__": main()
