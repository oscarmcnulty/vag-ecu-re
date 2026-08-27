#!/usr/bin/env python3
"""clbinfo.py - container parser / analyser for modern VCDS label files.

VCDS >= ~12.12 ships its label data as .clb (labels) and .crd (coding
reference) files in a container that is NOT the 2010-era keystream format that
svcdec.py handles. Layout, verified on all 1114 .clb + 48 .crd files in the
VCDS 21.3.0 installer:

    repeat until EOF:
        u16  plaintext_length      (big endian)
        u8[] ciphertext            (plaintext_length rounded UP to a multiple of 8)
        u8   0x00
        u8   0x0A                  (the old format's record separator, kept)

One record = one *data* line of the original .lbl (comment lines are dropped
when Ross-Tech compiles .lbl -> .clb).

The payload is an 8-byte block cipher with chaining, one global key, fixed IV:
  * ciphertext is always a multiple of 8, padding is added only when needed
    (so no PKCS#7 - the length field carries the true size);
  * an identical ciphertext block NEVER appears at two different block indices
    (0 out of 555085 distinct blocks), and every repeated block at index > 0 is
    accompanied by an identical block at index-1 (68619/68619 cases) - that is
    chaining, i.e. CBC, not ECB and not a position-keyed stream;
  * block 0 repeats freely across files whenever the first 8 plaintext bytes
    match, so the IV is constant for every record of every file;
  * .crd and .clb records collide with each other, so both use the same key.

Known plaintext: 418 of 1114 .clb files (all of them redirect stubs, 2-7
records, first record 39-48 bytes) start with the ciphertext block
e6427c2e261007a1 - that is E(IV ^ "REDIRECT"), matching the plaintext
"REDIRECT,<part-number>.CLB,<...>" lines seen in the 1301 label files that
ship unencrypted.

The key itself is not statically recoverable: VCDS-32.exe / VCDS-64.exe are
protector-packed (all sections RWX and entropy 8.00, 1-import-per-DLL stub
table, entry point in the last section), and no other shipped binary touches
.clb. See README.md.

usage:
    clbinfo.py FILE...            per-file record dump
    clbinfo.py --corpus DIR       re-run the mode/chaining analysis on a tree
"""

import collections
import glob
import os
import struct
import sys


def records(path):
    """Yield (plaintext_length, ciphertext) per record. Raises on bad framing."""
    with open(path, 'rb') as fp:
        d = fp.read()
    off = 0
    out = []
    while off + 2 <= len(d):
        n = struct.unpack_from('>H', d, off)[0]
        ct_len = (n + 7) // 8 * 8
        end = off + 2 + ct_len
        if d[end:end + 2] != b'\x00\n':
            raise ValueError('%s: bad framing at 0x%x (len=%d)' % (path, off, n))
        out.append((n, d[off + 2:end]))
        off = end + 2
    if off != len(d):
        raise ValueError('%s: %d trailing bytes' % (path, len(d) - off))
    return out


def dump(path):
    recs = records(path)
    print("%s: %d records, %d plaintext bytes" %
          (path, len(recs), sum(n for n, _ in recs)))
    for i, (n, ct) in enumerate(recs):
        print("  %4d  len=%-5d blocks=%-3d %s%s" %
              (i, n, len(ct) // 8, ct[:16].hex(),
               '...' if len(ct) > 16 else ''))


def corpus(root):
    files = sorted(glob.glob(os.path.join(root, '**', '*.clb'), recursive=True) +
                   glob.glob(os.path.join(root, '**', '*.crd'), recursive=True))
    all_recs = []
    bad = 0
    for fn in files:
        try:
            all_recs.extend(ct for _, ct in records(fn))
        except ValueError as e:
            bad += 1
            print("  FRAMING FAIL:", e)
    print("files %d (framing ok %d), records %d" %
          (len(files), len(files) - bad, len(all_recs)))

    at_index = collections.defaultdict(set)
    positional = collections.defaultdict(list)
    count = collections.Counter()
    for ri, ct in enumerate(all_recs):
        for i in range(0, len(ct), 8):
            b = ct[i:i + 8]
            at_index[b].add(i // 8)
            positional[(i // 8, b)].append(ri)
            count[b] += 1
    multi = sum(1 for s in at_index.values() if len(s) > 1)
    print("distinct blocks %d; appearing at >1 block index: %d  (ECB would be >0)"
          % (len(at_index), multi))

    repeated = broke = 0
    for (j, b), rs in positional.items():
        if j == 0 or len(rs) < 2:
            continue
        repeated += 1
        if len({all_recs[r][(j - 1) * 8:j * 8] for r in rs}) > 1:
            broke += 1
    print("repeated blocks at index>0: %d; of those with a differing previous "
          "block: %d  (0 => chaining/CBC)" % (repeated, broke))
    print("most common first blocks:")
    firsts = collections.Counter(ct[:8] for ct in all_recs if ct)
    for b, c in firsts.most_common(5):
        print("   %s  %d records" % (b.hex(), c))


def main(argv):
    if len(argv) > 2 and argv[1] == '--corpus':
        corpus(argv[2])
        return 0
    if len(argv) < 2:
        print(__doc__)
        return 1
    for path in argv[1:]:
        dump(path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
