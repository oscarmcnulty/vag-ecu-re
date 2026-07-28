#!/usr/bin/env python3
"""3-way binary diff for ECU images (Original vs Stage1 vs Stage2).

Reproduces the manual 3-file calibration diff from the Simos8.5 RE: finds the
byte ranges that differ between tunes, which localize the modified maps. Works
on any equal-length raw images; no Ghidra needed.

Usage:
    diff3.py ORIGINAL.bin STAGE1.bin [STAGE2.bin] \
        [--base 0x80000000] [--region 0x40000:0x80000] [--gap 16]
"""
import argparse, sys


def load(path):
    with open(path, "rb") as f:
        return f.read()


def parse_int(s):
    return int(s, 0)


def diff_ranges(images, names, region, gap):
    lo, hi = region
    hi = min(hi, min(len(b) for b in images))
    diffs = [i for i in range(lo, hi) if len({b[i] for b in images}) > 1]
    if not diffs:
        return []
    # coalesce adjacent differing offsets, merging across gaps <= `gap`
    ranges, start, prev = [], diffs[0], diffs[0]
    for off in diffs[1:]:
        if off - prev <= gap:
            prev = off
        else:
            ranges.append((start, prev + 1))
            start = prev = off
    ranges.append((start, prev + 1))
    return ranges


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="2 or 3 equal-length .bin images")
    ap.add_argument("--base", type=parse_int, default=0x80000000,
                    help="load vaddr base (default 0x80000000)")
    ap.add_argument("--region", default="0x0:0x200000",
                    help="file-offset window lo:hi (default whole 2MB; cal is 0x40000:0x80000)")
    ap.add_argument("--gap", type=int, default=16,
                    help="merge differing offsets separated by <= GAP bytes")
    a = ap.parse_args()

    imgs = [load(p) for p in a.images]
    if len({len(b) for b in imgs}) != 1:
        print(f"sizes differ: {[len(b) for b in imgs]}", file=sys.stderr)
        sys.exit(1)
    lo, hi = (parse_int(x) for x in a.region.split(":"))
    ranges = diff_ranges(imgs, a.images, (lo, hi), a.gap)

    total = sum(e - s for s, e in ranges)
    print(f"# {len(imgs)}-way diff over [{lo:#x}:{hi:#x}], gap<= {a.gap}")
    print(f"# images: {', '.join(a.images)}")
    print(f"# {len(ranges)} changed blocks, {total} bytes total\n")
    print(f"{'file_off':>10} {'vaddr':>12} {'len':>6}   bytes (per image, first 8)")
    for s, e in ranges:
        cols = "  ".join(imgs[k][s:min(s + 8, e)].hex() for k in range(len(imgs)))
        print(f"{s:#10x} {a.base + s:#12x} {e - s:6d}   {cols}")


if __name__ == "__main__":
    main()
