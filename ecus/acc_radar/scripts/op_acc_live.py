#!/usr/bin/env python3
# op_acc_live.py -- live-capture ACC radar (0x0B) measuring blocks and report which BYTES move,
# to tell raw-detection data (tracks a real target) from static config. READ-ONLY.
#   usage: op_acc_live.py [duration_s] [blk ...]
import sys, time
sys.path.insert(0, "/home/om/tools/VW_Flash")
from op_tp20_read2 import Raw, setup, Chan, txt

ACC = 0x0B
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
blks = [int(x, 0) for x in sys.argv[2:]] or [1, 13, 14, 48, 49]

def main():
    raw = Raw()
    try:
        s = setup(raw, ACC)
        if not s:
            print("no channel to 0x0B"); return
        recv, send = s
        c = Chan(raw, recv, send)
        if not c.params():
            print("no params"); return
        c.request(bytes([0x10, 0x89]))
        print(f"connected; part {txt(c.request(bytes([0x22,0xF1,0x87]),secs=1.0)[3:])!r}")
        print(f"capturing blocks {blks} for {dur:.0f}s  --  MOVE A TARGET IN FRONT NOW")
        hist = {b: [] for b in blks}     # (t, bytes)
        t0 = time.monotonic(); cyc = 0
        while time.monotonic() - t0 < dur:
            for b in blks:
                r = c.request(bytes([0x21, b]), secs=0.4)
                if r and r[0] == 0x61:
                    hist[b].append((time.monotonic() - t0, r[2:]))
            cyc += 1
        c.disconnect()
    finally:
        raw.close()

    print(f"\n==== {cyc} cycles ====")
    for b in blks:
        rows = hist[b]
        if not rows:
            print(f"\nblk {b}: no reads"); continue
        L = min(len(x[1]) for x in rows)
        print(f"\n=== blk {b}: {len(rows)} reads, {L}B ===")
        moved = []
        for i in range(L):
            vals = [x[1][i] for x in rows]
            dv = len(set(vals))
            if dv > 1:
                moved.append((i, dv, min(vals), max(vals)))
        if not moved:
            print("  ALL BYTES CONSTANT (static config, not live detection)")
            continue
        for i, dv, lo, hi in moved:
            # flag bytes that swing widely (candidate signal) vs tiny (counter/noise)
            tag = "  <-- WIDE SWING" if (hi - lo) > 8 and dv > 4 else ""
            print(f"  byte[{i:2}]: {dv:3} distinct  {lo:3}..{hi:3} (span {hi-lo:3}){tag}")
        # timeline of the widest-swinging byte (and its 16-bit pair) across the window
        widest = max(moved, key=lambda m: (m[3] - m[2]))
        i = widest[0]
        print(f"  timeline byte[{i}] (10 snapshots):")
        step = max(1, len(rows) // 10)
        for k in range(0, len(rows), step):
            t, d = rows[k]
            w = (d[i] << 8 | d[i + 1]) if i + 1 < len(d) else d[i]
            print(f"    t={t:5.1f}s  byte={d[i]:3}  word16@{i}={w:5}  raw={d.hex()}")

if __name__ == "__main__":
    main()
