#!/usr/bin/env python3
"""Locate and identify CRC lookup tables in a raw ECU image.

Scans for 256-entry CRC tables (8/16/32-bit, reflected or not) and recovers the
generator polynomial, so you can find the checksum primitive without decompiling.
This is what pinned the Simos8.5 CRC32 table at file 0x9083c (poly 0xEDB88320).

Usage:
    crc_finder.py IMAGE.bin [--base 0x80000000] [--width 8,16,32]
"""
import argparse, struct, sys


def reflect(v, bits):
    r = 0
    for _ in range(bits):
        r = (r << 1) | (v & 1)
        v >>= 1
    return r


def gen_table(width, poly, refin):
    """Build a 256-entry table for a candidate (width, poly, refin); compare to image."""
    top = 1 << (width - 1)
    mask = (1 << width) - 1
    tbl = []
    for n in range(256):
        if refin:
            c = reflect(n, 8) << (width - 8)
        else:
            c = n << (width - 8)
        for _ in range(8):
            c = ((c << 1) ^ poly) & mask if (c & top) else (c << 1) & mask
        tbl.append(reflect(c, width) if refin else c)
    return tbl


# Well-known polynomials to test (normal form). refin handled separately.
KNOWN = {
    32: [(0x04C11DB7, "CRC-32 / zlib (refl 0xEDB88320)")],
    16: [(0x8005, "CRC-16/ARC (refl 0xA001)"), (0x1021, "CRC-16/CCITT")],
    8:  [(0x2F, "CRC-8/AUTOSAR"), (0x1D, "CRC-8/SAE-J1850"), (0x07, "CRC-8")],
}


def read_table(buf, off, width, little=True):
    sz = width // 8
    fmt = ("<" if little else ">") + {1: "B", 2: "H", 4: "I"}[sz]
    out = []
    for i in range(256):
        p = off + i * sz
        if p + sz > len(buf):
            return None
        out.append(struct.unpack_from(fmt, buf, p)[0])
    return out


def scan(buf, width, base):
    sz = width // 8
    cands = {}
    for poly, name in KNOWN[width]:
        for refin in (True, False):
            t = gen_table(width, poly, refin)
            cands[(poly, refin)] = (tuple(t), name)
    hits = []
    # entry[1] of a CRC table is the poly-derived constant; cheap prefilter.
    for off in range(0, len(buf) - 256 * sz, sz):
        tbl = read_table(buf, off, width)
        if tbl is None or tbl[0] != 0:
            continue
        for (poly, refin), (ref, name) in cands.items():
            if tuple(tbl) == ref:
                hits.append((off, base + off, width, poly, refin, name))
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0x80000000)
    ap.add_argument("--width", default="8,16,32",
                    help="comma list of widths to scan (default 8,16,32)")
    a = ap.parse_args()
    buf = open(a.image, "rb").read()
    widths = [int(w) for w in a.width.split(",")]

    print(f"# scanning {a.image} ({len(buf)} bytes), base {a.base:#x}")
    found = 0
    for w in widths:
        for off, va, width, poly, refin, name in scan(buf, w, a.base):
            found += 1
            print(f"file {off:#08x}  vaddr {va:#010x}  CRC{width}  "
                  f"poly {poly:#x} refin={refin}  -> {name}")
    if not found:
        print("# no standard CRC tables matched; try a wider --width set or a "
              "self-derived poly (extend KNOWN[]).", file=sys.stderr)


if __name__ == "__main__":
    main()
