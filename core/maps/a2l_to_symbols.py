#!/usr/bin/env python3
"""Adapter: canonical A2L -> Ghidra ApplySymbols CSV (calibration labels).

`simos85.a2l` is the canonical, hand-edited source of truth for calibration
objects. This emits the `address,name,type,comment` CSV that
`core/ghidra/ApplySymbols.java` consumes, so every named cal object lands in the
Ghidra project (and thus in decompiles_r/) as a LABEL with its provenance
description (+ scale/unit) as the plate comment.

A2L CHARACTERISTIC addresses are already ECU vaddr (0x80000000-based), so no offset
math here. Function symbols are NOT sourced from the A2L — those stay in
analysis/symbols_merged.csv (A2L describes cal data, not code).

Usage:
  a2l_to_symbols.py ecus/simos85/maps/simos85.a2l [--out a2l_symbols.csv]
  analyzeHeadless <proj> <name> -process -postScript ApplySymbols.java a2l_symbols.csv
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a2l  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a2l")
    ap.add_argument("--out", default="a2l_symbols.csv")
    args = ap.parse_args()

    model = a2l.load_path(args.a2l)

    rows = []
    for c in model.characteristics:
        a, b = c["scale"]
        sc = a2l.scale_str(a, b)
        note = ""
        if sc != "X":
            note = f' | scale: {sc}'
        if c["unit"]:
            note += f' [{c["unit"]}]'
        comment = c["desc"] + note
        rows.append((f'0x{c["addr"]:08x}', c["name"], "LABEL", comment))

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["address", "name", "type", "comment"])
        w.writerows(rows)
    print(f"{len(rows)} calibration labels -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
