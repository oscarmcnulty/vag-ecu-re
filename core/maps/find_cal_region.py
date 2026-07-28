#!/usr/bin/env python3
"""Locate the calibration region(s) of a raw ECU image by axis-array density.

Cold-start problem: for a new ECU we know the load base but not which part of the
image is code and which is calibration. Entropy alone does not separate them well --
Bosch cal blocks are dense and look code-like. What DOES separate them is a
structural fingerprint that only calibration data has:

    a map/curve is always preceded (or followed) by its AXIS -- a short, strictly
    monotonic array of u8/u16 breakpoints (rpm, load, speed, temperature ...).

Strictly monotonic runs are vanishingly rare in compiled TriCore code and in
padding, so their density per block is a strong, cheap discriminator. This scans
for them and reports the blocks where they cluster.

    python3 core/maps/find_cal_region.py <image.bin> [--base 0x80000000]
                                         [--block 0x10000] [--min-run 6]

Output: per-block axis-run counts (a histogram over the image) plus the merged
candidate cal ranges, as vaddrs ready to feed reproduce.sh's MarkCalData /
ResolveCalReads --cal window.
"""
import argparse
import struct
import sys


def monotonic_runs(buf, width, min_run, signed=False):
    """Yield (offset, length_in_elements) of strictly monotonic runs of `width`-byte ints.

    Scans on the natural alignment for the width. Requires strict monotonicity
    (no plateaus): repeated values are overwhelmingly padding/zero-fill, and
    admitting them floods the result with false positives from 0x0000 runs.
    """
    fmt = {1: ('b' if signed else 'B'), 2: ('<h' if signed else '<H')}[width]
    n = len(buf) // width
    if n < min_run:
        return
    vals = [struct.unpack_from(fmt, buf, i * width)[0] for i in range(n)]
    start, direction = 0, 0
    for i in range(1, n + 1):
        if i < n:
            d = (vals[i] > vals[i - 1]) - (vals[i] < vals[i - 1])
        else:
            d = 0
        if d == 0 or (direction and d != direction):
            if i - start >= min_run:
                yield start * width, i - start
            start, direction = (i - 1 if d else i), (d if d else 0)
            if d:
                direction = d
        elif direction == 0:
            direction = d
    return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--base', default='0x80000000')
    ap.add_argument('--block', default='0x10000')
    ap.add_argument('--min-run', type=int, default=6,
                    help='minimum breakpoints for a run to count as an axis (default 6)')
    ap.add_argument('--top', type=int, default=0, help='only print the top N blocks')
    a = ap.parse_args()

    base = int(a.base, 16)
    blk = int(a.block, 16)
    data = open(a.image, 'rb').read()

    counts = {}
    for off in range(0, len(data), blk):
        chunk = data[off:off + blk]
        if chunk.count(0) / max(len(chunk), 1) > 0.99:      # erased sector
            counts[off] = None
            continue
        c = 0
        for width in (1, 2):
            for _o, _n in monotonic_runs(chunk, width, a.min_run):
                c += 1
        counts[off] = c

    live = [(o, c) for o, c in counts.items() if c is not None]
    if not live:
        print('no live blocks', file=sys.stderr)
        return 1
    vals = sorted(c for _, c in live)
    med = vals[len(vals) // 2]
    # a cal block carries many times the axis density of a code block
    thresh = max(med * 3, 8)

    print(f'image {a.image}  base 0x{base:08x}  block 0x{blk:x}  min-run {a.min_run}')
    print(f'median axis-runs/live-block = {med}   -> cal threshold = {thresh}\n')
    rows = sorted(live, key=lambda t: -t[1])[:a.top] if a.top else sorted(live)
    print('  vaddr        runs  verdict')
    for off, c in rows:
        mark = 'CAL' if c >= thresh else ''
        bar = '#' * min(c // max(thresh // 10, 1), 60)
        print(f'  0x{base+off:08x} {c:6d}  {mark:3} {bar}')

    # merge adjacent cal blocks into ranges
    cal = sorted(o for o, c in live if c >= thresh)
    ranges, cur = [], None
    for o in cal:
        if cur and o == cur[1]:
            cur = (cur[0], o + blk)
        else:
            if cur:
                ranges.append(cur)
            cur = (o, o + blk)
    if cur:
        ranges.append(cur)
    print('\ncandidate calibration ranges (vaddr):')
    for lo, hi in ranges:
        print(f'  0x{base+lo:08x}..0x{base+hi:08x}   ({(hi-lo)//1024} KB)')
    if ranges:
        lo = base + min(r[0] for r in ranges)
        hi = base + max(r[1] for r in ranges)
        print(f'\nspan for --cal / MarkCalData:  0x{lo:08x} 0x{hi:08x}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
