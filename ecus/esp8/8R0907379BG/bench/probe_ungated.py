#!/usr/bin/env python3
"""Enumerate which KWP services/identifiers are UNGATED (not NRC 0x90) in session 0x85, to find a
RAM/data read path that does NOT require SecurityAccess. Read-only probes. 32-bit python."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN
from tp20_kwp import TP20KWP, kfmt

def fresh(c):
    tp=TP20KWP(c)
    if not tp.open(): return None
    r=tp.request(bytes.fromhex("1085"))
    if not r or r[0]!=0x50: return None
    return tp

def one(c, hexreq, reopen=False):
    """send a single request on a fresh-ish channel; returns (resp_bytes_or_None, note)"""
    tp=fresh(c)
    if tp is None: return None,"no-session"
    try:
        tp.maintain(0.05)
        r=tp.request(bytes.fromhex(hexreq))
        return r, kfmt(r)
    finally:
        tp.close()

def main():
    c=RawCAN()
    try:
        # 1) category test: one request per channel to avoid cross-contamination/drops
        print("=== service accessibility (session 0x85, one req per channel) ===")
        tests = {
            "21 01 (ReadDataByLocalId grp1)":"2101",
            "21 02":"2102", "21 03":"2103", "21 0A":"210A",
            "22 F1 90 (VIN DID)":"22F190",
            "23 ReadMem 0x40a1a8":"2340A1A804",
            "2C define-by-addr":"2CF00340A1A804",
            "30 (IOControl?)":"3001",
            "31 01 (RoutineControl start)":"310100",
            "3E TesterPresent":"3E01",
            "1A 9B (ident)":"1A9B",
        }
        for name,hx in tests.items():
            r,note=one(c,hx)
            print(f"  {name:34s} {hx:14s} -> {note}")
            time.sleep(0.2)
    finally:
        c.close()

if __name__=="__main__":
    main()
