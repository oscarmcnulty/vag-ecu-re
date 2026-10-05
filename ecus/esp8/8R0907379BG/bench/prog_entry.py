#!/usr/bin/env python3
"""ESP8 (8R0907379BG) programming-mode entry probe (corrected sequence).

VAG flash entry (VW KWP2000-Flashen spec + bri3d VW_Flash docs): SA2 SecurityAccess is only valid
AFTER a knock + 0x31 precondition routine + 10 85 which "descends" into the boot loader. The 10 85
descent DROPS the TP2.0 channel -> a RECONNECT is required (spec section 3.6), and only then is 27 01
requested in the boot-loader context. Earlier runs did 27 01 cold, in the wrong context -> SA2 rejected.

SAFE: no SecurityAccess key is sent (no lockout), no destructive routine parameters, 0xC4 EraseFlash
is never called. Routines swept with no params in the locked session (flash-erase is gated there).

Usage (32-bit python, ignition ON):  prog_entry.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN
from tp20_kwp import TP20KWP, kfmt

def seedinfo(r):
    if r and r[0] == 0x67 and len(r) >= 6: return "SEED " + r[2:6].hex(' ')
    return kfmt(r)

def main():
    # ---- Phase 1: extended session, knock, 0x31 routine sweep (channel NOT yet disrupted) ----
    # Poll for state A (fully-booted app: 10 89 accepted). After a power-cycle this appears; a prior
    # cold 10 85 descent leaves the module in state B (10 89 rejected) until the next power-cycle.
    print("[*] waiting for state A (10 89 accepted) — power-cycle the module now if needed ...")
    c = tp = None; r = None; t0 = time.time()
    while time.time() - t0 < 40:
        try:
            c = RawCAN(); tp = TP20KWP(c)
            if tp.open():
                r = tp.request(bytes.fromhex('1089'))
                if r and r[0] == 0x50:
                    break
            tp.close(); c.close()
        except Exception:
            pass
        time.sleep(0.5)
    try:
        if not (r and r[0] == 0x50):
            print("[!] state A (10 89) not seen within 40s — power-cycle and retry"); return
        print(f"[*] state A reached: 10 89 -> {kfmt(r)}  (tx->0x{tp.tx:03x} rx<-0x{tp.rx:03x})")
        tp.keepalive(force=True)
        print("  -- knock --")
        for req in ("14FFFF", "1A9B", "22F187"):
            print(f"  {req:8s} -> {kfmt(tp.request(bytes.fromhex(req)))}"); tp.keepalive(force=True)
        print("  -- 0x31 routine sweep (no params, locked; 0xC4 skipped) --")
        positives = []
        for rli in list(range(0x01, 0x11)) + [0x20, 0x30] + list(range(0xC0, 0xD0)) + [0xE0, 0xFF]:
            if rli == 0xC4: continue
            r = tp.request(bytes([0x31, rli])); tp.keepalive(force=True)
            if r and r[0] == 0x71:
                positives.append(rli); print(f"  31 {rli:02x} -> POSITIVE [{r.hex(' ')}]")
            elif r and r[0] == 0x7f and len(r) > 2 and r[2] not in (0x11, 0x12):
                print(f"  31 {rli:02x} -> {kfmt(r)}")
        print(f"  positive routines: {[hex(x) for x in positives]}")
        print("  -- descent: 10 85 (expect channel drop) --")
        r = tp.request(bytes.fromhex('1085'))
        print(f"  10 85 -> {kfmt(r)}")
    finally:
        tp.close(); c.close()

    # ---- Phase 2: RECONNECT after the descent, then request the boot-loader seed ----
    print("  -- reconnect (TP2.0 re-open) --")
    time.sleep(0.4)
    c2 = RawCAN(); tp2 = TP20KWP(c2)
    try:
        if not tp2.open():
            print("  [!] reconnect failed — module may be mid-reset; retrying once"); time.sleep(0.8)
            tp2.close(); c2.close(); c2 = RawCAN(); tp2 = TP20KWP(c2)
            if not tp2.open(): print("  [!] reconnect failed again"); return
        print(f"  [*] reconnected tx->0x{tp2.tx:03x} rx<-0x{tp2.rx:03x}")
        # In the boot loader after descent: try 27 01 directly, and (10 85 then 27 01)
        print(f"  27 01 (post-descent)        -> {seedinfo(tp2.request(bytes.fromhex('2701')))}"); tp2.keepalive(force=True)
        r = tp2.request(bytes.fromhex('1085')); print(f"  10 85 (in boot loader)      -> {kfmt(r)}"); tp2.keepalive(force=True)
        print(f"  27 01 (after 10 85)         -> {seedinfo(tp2.request(bytes.fromhex('2701')))}")
    finally:
        tp2.close(); c2.close()

if __name__ == "__main__":
    main()
