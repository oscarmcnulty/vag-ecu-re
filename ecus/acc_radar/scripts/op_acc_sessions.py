#!/usr/bin/env python3
# op_acc_sessions.py -- probe the B8 Q5 ACC radar (0x0B) in different KWP2000 sessions and
# sweep its measuring blocks under each, to look for raw-radar data. READ-ONLY.
#
# Phase 1: which StartDiagnosticSession modes does the radar accept? (10 81/83/86/89/92)
# Phase 2: under {default, +each accepted session}, sweep measuring blocks 21 01..21 RANGE,
#          capture raw hex; then diff sessions so new/changed blocks stand out.
#
# No writes: only 0x10 (StartDiagnosticSession, itself read-only), 0x22 (ReadDID), 0x21 (readBlock).
import sys, time
sys.path.insert(0, "/home/om/tools/VW_Flash")
from op_tp20_read2 import Raw, setup, Chan, txt

ACC = 0x0B
SESSIONS = [0x81, 0x83, 0x86, 0x89, 0x92]   # default, measurement/cal, coding, application, ?
BLK_MAX = int(sys.argv[1], 0) if len(sys.argv) > 1 else 80

def open_chan(raw):
    s = setup(raw, ACC)
    if not s:
        return None
    recv, send = s
    c = Chan(raw, recv, send)
    if not c.params():
        c.disconnect(); return None
    return c

def identity(c):
    r = c.request(bytes([0x22, 0xF1, 0x87]), secs=1.0)
    return txt(r[3:]) if (r and r[0] == 0x62) else "?"

def start_session(c, sid):
    r = c.request(bytes([0x10, sid]), secs=1.5)
    if not r:
        return "no-resp", None
    if r[0] == 0x50:
        return "OK", r
    if r[0] == 0x7F:
        return f"neg(nrc={r[-1]:#04x})", r
    return f"?{r.hex()}", r

def sweep(c, rng):
    out = {}
    for blk in rng:
        r = c.request(bytes([0x21, blk]), secs=0.5)
        if r and r[0] == 0x61:
            out[blk] = r[2:].hex()
    return out

def main():
    raw = Raw()
    try:
        # sanity + identity
        c = open_chan(raw)
        if not c:
            print("no TP2.0 channel to 0x0B (ignition on? radar awake?)"); return
        print(f"connected to ACC radar 0x0B: part {identity(c)!r}")

        # ---- Phase 1: session acceptance ----
        print("\n=== Phase 1: session acceptance (10 XX) ===")
        accepted = []
        for sid in SESSIONS:
            # fresh channel per session to avoid carryover
            c.disconnect(); time.sleep(0.2)
            c = open_chan(raw)
            if not c:
                print(f"  10 {sid:02x}: (channel reopen failed)"); continue
            status, _ = start_session(c, sid)
            print(f"  10 {sid:02x}: {status}")
            if status == "OK" and sid not in (0x85,):   # never flash
                accepted.append(sid)

        # ---- Phase 2: block sweep per session ----
        modes = [("default", None)] + [(f"sess{sid:02x}", sid) for sid in accepted]
        results = {}
        for name, sid in modes:
            c.disconnect(); time.sleep(0.2)
            c = open_chan(raw)
            if not c:
                print(f"\n[{name}] channel reopen failed"); continue
            if sid is not None:
                start_session(c, sid)
            blocks = sweep(c, range(1, BLK_MAX + 1))
            results[name] = blocks
            print(f"\n=== [{name}] {len(blocks)} blocks respond (1..{BLK_MAX}) ===")
            for b in sorted(blocks):
                print(f"  blk {b:3}: {blocks[b]}")

        # ---- diff: blocks that differ between default and an engineering session ----
        base = results.get("default", {})
        for name in results:
            if name == "default":
                continue
            diff = []
            allb = set(base) | set(results[name])
            for b in sorted(allb):
                if base.get(b) != results[name].get(b):
                    diff.append(b)
            if diff:
                print(f"\n=== DIFF default vs {name}: blocks {diff} ===")
                for b in diff:
                    print(f"  blk {b:3}: default={base.get(b)}")
                    print(f"          {name}={results[name].get(b)}")
            else:
                print(f"\n=== DIFF default vs {name}: identical ===")

        c.disconnect()
    finally:
        raw.close()

if __name__ == "__main__":
    main()
