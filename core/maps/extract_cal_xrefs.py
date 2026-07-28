#!/usr/bin/env python3
"""Cross-reference: which functions reference which calibration addresses.

TriCore code addresses calibration data by constant address. The cal region on
Simos8.5 is vaddr 0x80040000-0x80070000, often reached via the uncached mirror
0xA00xxxxx (same physical). This scans every decompiled function (<addr>.c) for
constant cal-region literals and builds:
  cal_xref.csv   cal_vaddr, n_refs, functions (addr:name; the code that reads it)

This is the backbone for map/constant identification: join it against the tuner
diff (performance maps) or a target constant's value (cruise min speed, etc.).

Usage:
  extract_cal_xrefs.py --decompiles DIR --symbols merged.csv \
      [--lo 0x80040000] [--hi 0x80070000] [--out cal_xref.csv]
"""
import argparse, csv, glob, os, re, collections

HEX = re.compile(r"0x([89aAbB]00[0-9a-fA-F]{5})")  # 0x8/0xA segment, 8 hex digits


def norm(v):
    # fold the 0xA0/0xB0 uncached mirror down to the 0x80 cached vaddr
    return (v & 0x8FFFFFFF) | 0x80000000


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decompiles", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--lo", type=lambda s: int(s, 0), default=0x80040000)
    ap.add_argument("--hi", type=lambda s: int(s, 0), default=0x80070000)
    ap.add_argument("--out", default="cal_xref.csv")
    a = ap.parse_args()

    names = {}
    for r in csv.DictReader(open(a.symbols)):
        names[r["address"].lower().replace("0x", "")] = r["name"]

    xref = collections.defaultdict(set)  # cal_vaddr -> {(func_addr, name)}
    for path in glob.glob(os.path.join(a.decompiles, "*.c")):
        faddr = os.path.splitext(os.path.basename(path))[0].lower()
        fname = names.get(faddr, "FUN_" + faddr)
        text = open(path, errors="replace").read()
        for m in set(HEX.findall(text)):
            v = norm(int(m, 16))
            if a.lo <= v < a.hi:
                xref[v].add((faddr, fname))

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cal_vaddr", "n_refs", "functions"])
        for v in sorted(xref):
            refs = sorted(xref[v])
            w.writerow([f"0x{v:08x}", len(refs),
                        "; ".join(f"{fa}:{fn}" for fa, fn in refs)])
    print(f"{len(xref)} distinct cal addresses referenced -> {a.out}")
    # quick texture
    multi = sum(1 for v in xref if len(xref[v]) > 1)
    print(f"  {multi} addresses referenced by >1 function")


if __name__ == "__main__":
    main()
