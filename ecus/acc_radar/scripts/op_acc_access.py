#!/usr/bin/env python3
# op_acc_access.py -- enumerate the ACC radar (0x0B) ACCESS MODEL purely from the CAN bus.
# READ-ONLY: only 0x10 StartDiagnosticSession (session requests) and 0x27 SecurityAccess SEED
# requests (requestSeed sub-functions only -- NEVER sends a key). No other services touched.
#
# Phase A: quick sweep of all 0x10 sub-functions (0x00..0xFF) from a single channel -> first map.
# Phase B: re-test every sub-function that was NOT "not-supported" on a FRESH channel (clean
#          classification: reachable from default? positive / needs-SA / wrong-conditions).
# Phase C: SecurityAccess seed enumeration (0x27 01..1F odd) in default and in the app session.
import sys, time
sys.path.insert(0, "/home/om/tools/VW_Flash")
from op_tp20_read2 import Raw, setup, Chan, txt

ACC = 0x0B
NRC = {0x10:"generalReject",0x11:"serviceNotSupported",0x12:"subFn/sessionNotSupported",
       0x13:"badLength/format",0x22:"conditionsNotCorrect",0x31:"requestOutOfRange",
       0x33:"securityAccessDenied",0x35:"invalidKey",0x36:"exceededAttempts",
       0x37:"timeDelayNotExpired",0x78:"responsePending",0x7E:"subFnNotSuppInSession",
       0x7F:"svcNotSuppInSession"}

def nrc(b):
    return f"{b:#04x} {NRC.get(b,'?')}"

def open_chan(raw):
    s = setup(raw, ACC)
    if not s: return None
    recv, send = s
    c = Chan(raw, recv, send)
    if not c.params(): c.disconnect(); return None
    return c

def classify(r):
    if not r: return "no-resp", None
    if r[0] == 0x50: return "POSITIVE", r
    if r[0] == 0x7F and len(r) >= 3: return f"neg {nrc(r[-1])}", r
    return f"?{r.hex()}", r

def main():
    raw = Raw()
    try:
        c = open_chan(raw)
        if not c: print("no channel to 0x0B (ign on? radar awake?)"); return
        part = c.request(bytes([0x22,0xF1,0x87]), secs=1.0)
        print(f"ACC radar 0x0B connected: part {txt(part[3:]) if part and part[0]==0x62 else '?'!r}")

        # ---- Phase A: fast full sweep (session may drift as positives are entered) ----
        print("\n=== Phase A: 0x10 sub-function sweep 0x00..0xFF ===")
        interesting = []
        for sf in range(0x100):
            r = c.request(bytes([0x10, sf]), secs=0.25)
            st, _ = classify(r)
            if r is not None and not (r and r[0]==0x7F and r[-1]==0x12):
                interesting.append(sf)
                print(f"  10 {sf:02x}: {st}")
        if not interesting:
            print("  (every sub-function => not-supported except any already shown)")

        # ---- Phase B: clean re-test from a FRESH channel (default session) ----
        print("\n=== Phase B: clean classification from default (fresh channel each) ===")
        sessions_open, sessions_sa, sessions_cond = [], [], []
        for sf in interesting:
            c.disconnect(); time.sleep(0.15)
            c = open_chan(raw)
            if not c: print(f"  10 {sf:02x}: reopen failed"); continue
            r = c.request(bytes([0x10, sf]), secs=0.8)
            st, _ = classify(r)
            print(f"  10 {sf:02x}: {st}")
            if r and r[0]==0x50: sessions_open.append(sf)
            elif r and r[0]==0x7F and r[-1]==0x33: sessions_sa.append(sf)
            elif r and r[0]==0x7F and r[-1]==0x22: sessions_cond.append(sf)

        # ---- Phase C: SecurityAccess seed enumeration ----
        def sa_probe(label):
            print(f"\n=== Phase C: SecurityAccess seeds ({label}) ===")
            for lvl in range(0x01, 0x20, 2):
                r = c.request(bytes([0x27, lvl]), secs=0.8)
                if not r: print(f"  27 {lvl:02x}: no-resp"); continue
                if r[0] == 0x67:
                    seed = r[2:]
                    nz = any(seed)
                    print(f"  27 {lvl:02x}: SEED {seed.hex()}" + ("" if nz else "  (all-zero = already unlocked / no-auth)"))
                elif r[0] == 0x7F:
                    print(f"  27 {lvl:02x}: neg {nrc(r[-1])}")
                else:
                    print(f"  27 {lvl:02x}: {r.hex()}")

        # default session
        c.disconnect(); time.sleep(0.15); c = open_chan(raw)
        if c: sa_probe("default session")
        # application session 0x89
        if c:
            c.disconnect(); time.sleep(0.15); c = open_chan(raw)
            if c and (lambda r: r and r[0]==0x50)(c.request(bytes([0x10,0x89]), secs=0.8)):
                sa_probe("app session 0x89")

        print("\n=== SUMMARY ===")
        print(f"  sessions OPEN (no SA):      {[f'{s:#04x}' for s in sessions_open]}")
        print(f"  sessions needing SA (0x33): {[f'{s:#04x}' for s in sessions_sa]}")
        print(f"  sessions conditions (0x22): {[f'{s:#04x}' for s in sessions_cond]}")
        if c: c.disconnect()
    finally:
        raw.close()

if __name__ == "__main__":
    main()
