#!/usr/bin/env python3
"""Test whether the TriCore base register `a9` points to a *flash* const pointer-table.

Context: on MED17.1.1, `a9` is a base register Ghidra never resolved (SetBaseRegs pinned
a0/a1/a8 only). The ACC path dereferences it as `*(a9+off)` struct/cal pointers. This tool
harvests every pointer-dereferenced `a9+off` offset from the decompiled corpus and scans the
firmware image for a base X such that X+off holds a valid pointer for (nearly) all offsets.

Result on 8R0907115N_0006: the only all-valid bases are decoys whose targets are ALL in CODE
(function-pointer tables) or ALL in CAL (the cal-object table @0x80103468) -- none point to
RAM. Since the ACC structs at *(a9+0x3ec) have writable fields, `a9` must point to RAM, whose
contents are not in the flash image. Conclusion: `a9` is a RAM (per-task) base, resolved at
boot -- see ecus/med17/maps/a9_resolution.md. This tool documents/repro's that negative result
(and would positively locate the base on an ECU that DID keep the table in flash).

Usage:
  python3 core/maps/find_a9_base.py <firmware.bin> --decompiles <dir> [--loadbase 0x80000000]
"""
import argparse, glob, os, re, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("firmware")
    ap.add_argument("--decompiles", required=True, help="dir of <addr>.c decompiles")
    ap.add_argument("--loadbase", default="0x80000000")
    ap.add_argument("--reg", default="a9")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()
    try:
        import numpy as np
    except ImportError:
        sys.exit("needs numpy")

    base = int(args.loadbase, 16)
    d = np.frombuffer(open(args.firmware, "rb").read(), dtype="<u4")
    N = len(d)

    # harvest pointer-deref offsets: *(<type> *)(a9 + 0xNNN)  (4-byte aligned only)
    pat = re.compile(r"\*\(\w[\w ]*\*\)\(" + re.escape(args.reg) + r" \+ (0x[0-9a-f]+)\)")
    offs = set()
    for f in glob.glob(os.path.join(args.decompiles, "*.c")):
        s = open(f, errors="ignore").read()
        if args.reg + " +" not in s:
            continue
        for m in pat.finditer(s):
            o = int(m.group(1), 16)
            if o % 4 == 0:
                offs.add(o)
    offw = sorted(o // 4 for o in offs)
    if not offw:
        sys.exit("no pointer-deref offsets harvested")

    w = d
    def inrange(lo, hi): return (w >= lo) & (w < hi)
    validRAM  = inrange(0xd0000000, 0xd0100000) | inrange(0xd4000000, 0xd4010000)
    validCAL  = inrange(0x80380000, 0x80400000)
    validCODE = inrange(0x80000000, 0x80380000)
    validANY  = validRAM | validCAL | validCODE | inrange(0xa0000000, 0xa0400000)

    def score(mask):
        s = np.zeros(N, dtype=np.int32)
        for ow in offw:
            s[:N - ow] += mask[ow:].astype(np.int32)
        return s
    sANY, sRAM, sCAL = score(validANY), score(validRAM), score(validCAL)

    frac = validANY.sum() / N
    print(f"offsets harvested: {len(offw)}   random-expected all-valid score ~ {frac*len(offw):.1f}")
    full = np.where(sANY == len(offw))[0]
    print(f"bases with all-{len(offw)} valid pointers: {len(full)}")
    order = full[np.argsort(sRAM[full])[::-1]] if len(full) else np.argsort(sANY)[::-1]
    print(f"\ntop {args.top} bases (by RAM-pointer count among all-valid):")
    for j in order[:args.top]:
        code = len(offw) - sRAM[j] - sCAL[j]
        print(f"  {args.reg}=0x{base + j*4:08x}  RAM={int(sRAM[j])} CAL={int(sCAL[j])} CODE={int(code)}")
    if len(full) and sRAM[order[0]] == 0:
        print("\nVERDICT: best all-valid base points to NO RAM -> a9 table is NOT flash-resident")
        print("         (decoys are function-pointer / cal-object tables). a9 is a RAM base;")
        print("         resolve via emulation or a bench RAM read -- see maps/a9_resolution.md.")

if __name__ == "__main__":
    main()
