#!/usr/bin/env python3
"""Extract a calibration-object inventory from an in-image pointer table.

Bosch MED17 keeps a flat table of pointers to every calibration object, sorted by
address, outside the calibration region itself (on MED17.1.1 @0x80103464, 971
entries). That table is effectively an A2L index with the names stripped: it gives
you the address AND -- because the entries are sorted and the objects are packed --
the SIZE of each object as the gap to the next pointer.

That matters because without a DAMOS/A2L you otherwise cannot tell where one map
ends and the next begins, which is the thing that blocks naming and editing them.

The table is located by scanning for the longest run of 4-byte little-endian words
that (a) all point into the calibration window and (b) increase monotonically. Both
conditions together are what distinguish an object table from incidental pointers.

    python3 core/maps/cal_object_table.py <image.bin> --cal 0x80380000:0x80400000
                                          [--base 0x80000000] [--out cal_objects.csv]
"""
import argparse
import csv
import struct
import sys


def find_table(data, base, cal_lo, cal_hi, min_entries=32):
    """Longest monotonic run of 4-byte pointers into [cal_lo, cal_hi). Returns (off, n)."""
    n_words = len(data) // 4
    words = struct.unpack_from('<%dI' % n_words, data, 0)
    best = (0, 0)
    i = 0
    while i < n_words:
        if not (cal_lo <= words[i] < cal_hi):
            i += 1
            continue
        j = i + 1
        while j < n_words and cal_lo <= words[j] < cal_hi and words[j] > words[j - 1]:
            j += 1
        if j - i > best[1]:
            best = (i * 4, j - i)
        i = max(j, i + 1)
    return best if best[1] >= min_entries else (None, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--cal', required=True, help='cal window as 0xLO:0xHI')
    ap.add_argument('--base', default='0x80000000')
    ap.add_argument('--out', default=None)
    ap.add_argument('--at', default=None, help='vaddr of the table, if already known')
    a = ap.parse_args()

    base = int(a.base, 16)
    lo, hi = (int(x, 16) for x in a.cal.split(':'))
    data = open(a.image, 'rb').read()

    if a.at:
        off = int(a.at, 16) - base
        n = 0
        while True:
            v = struct.unpack_from('<I', data, off + n * 4)[0]
            if not (lo <= v < hi):
                break
            if n and v <= struct.unpack_from('<I', data, off + (n - 1) * 4)[0]:
                break
            n += 1
    else:
        off, n = find_table(data, base, lo, hi)
        if off is None:
            print('no calibration object table found', file=sys.stderr)
            return 1

    ptrs = [struct.unpack_from('<I', data, off + i * 4)[0] for i in range(n)]
    print(f'object table @0x{base+off:08x}  entries={n}')
    print(f'  objects span 0x{ptrs[0]:08x}..0x{ptrs[-1]:08x}')

    rows = []
    for i, p in enumerate(ptrs):
        # size = gap to the next object; the last one is open-ended (unknown)
        size = (ptrs[i + 1] - p) if i + 1 < n else None
        rows.append({'index': i, 'addr': f'0x{p:08x}', 'size': size if size is not None else '',
                     'file_offset': f'0x{p-base:06x}'})

    sizes = [r['size'] for r in rows if r['size'] != '']
    hist = {}
    for s in sizes:
        hist[s] = hist.get(s, 0) + 1
    top = sorted(hist.items(), key=lambda t: -t[1])[:8]
    print('  most common object sizes (bytes: count): ' +
          ', '.join(f'{s}:{c}' for s, c in top))
    print(f'  scalars (size<=2): {sum(1 for s in sizes if s <= 2)}   '
          f'curves/maps (size>=8): {sum(1 for s in sizes if s >= 8)}')

    if a.out:
        with open(a.out, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['index', 'addr', 'size', 'file_offset'])
            w.writeheader()
            w.writerows(rows)
        print(f'  wrote {len(rows)} rows -> {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
