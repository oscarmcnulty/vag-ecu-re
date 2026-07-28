#!/usr/bin/env python3
"""Project the canonical A2L into a flat CSV catalog of calibration objects.

`simos85.a2l` is the canonical, hand-edited source of truth. This is the
human/reference projection the map docs cite: one row per object with name, data
address, dims, cell width, axis addresses, scaling and unit.

With --bin it verifies each object's x-axis breakpoint array is monotonic in the
image (the address-transfer sanity check): A2L addresses are ECU vaddr, so the
file offset is (addr - base), base default 0x80000000.

Usage:
  a2l_catalog.py ecus/simos85/maps/simos85.a2l [--bin IMAGE.bin] [--out a2l_catalog.csv]
"""
import argparse
import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a2l  # noqa: E402


def read_axis(buf, addr, bits, npts, base):
    off = addr - base
    sz = bits // 8
    out = []
    for i in range(npts):
        p = off + i * sz
        if p < 0 or p + sz > len(buf):
            return None
        if sz == 1:
            out.append(buf[p])
        elif sz == 2:
            out.append(struct.unpack_from("<H", buf, p)[0])
        else:
            out.append(struct.unpack_from("<I", buf, p)[0])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a2l")
    ap.add_argument("--bin")
    ap.add_argument("--base", default="0x80000000")
    ap.add_argument("--out", default="a2l_catalog.csv")
    args = ap.parse_args()

    base = int(args.base, 16)
    model = a2l.load_path(args.a2l)
    buf = open(args.bin, "rb").read() if args.bin else None

    rows = []
    for c in model.characteristics:
        # A2L axis order is x first, then y (AXIS_DESCR order in each CHARACTERISTIC).
        ax = [model.axis_pts.get(n) for n in c["axes"]]
        xax = ax[0] if len(ax) >= 1 and ax[0] else None
        yax = ax[1] if len(ax) >= 2 and ax[1] else None
        cols = xax["npts"] if xax else 1
        rows_ct = yax["npts"] if yax else 1
        a, b = c["scale"]

        mono = ""
        if buf is not None and xax is not None:
            vals = read_axis(buf, xax["addr"], xax["bits"], xax["npts"], base)
            mono = "mono" if (vals and vals == sorted(vals)
                              and len(set(vals)) == len(vals)) else "CHECK"

        rows.append({
            "name": c["name"],
            "kind": c["kind"],
            "data_addr": f'0x{c["addr"]:08x}',
            "rows": rows_ct,
            "cols": cols,
            "cellbits": c["bits"],
            "x_axis": f'0x{xax["addr"]:08x}' if xax else "",
            "y_axis": f'0x{yax["addr"]:08x}' if yax else "",
            "scaling": a2l.scale_str(a, b),
            "unit": c["unit"],
            "axis_mono": mono,
        })

    cols = ["name", "kind", "data_addr", "rows", "cols", "cellbits",
            "x_axis", "y_axis", "scaling", "unit", "axis_mono"]
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} calibration objects -> {args.out}", file=sys.stderr)
    for r in rows:
        print(f"  {r['data_addr']} {r['rows']}x{r['cols']} {r['cellbits']}b "
              f"{r['axis_mono']:5} {r['name'][:56]}", file=sys.stderr)


if __name__ == "__main__":
    main()
