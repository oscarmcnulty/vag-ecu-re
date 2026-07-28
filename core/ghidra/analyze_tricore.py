#!/usr/bin/env python3
"""Headless Ghidra import + auto-analysis for a TriCore ECU image.

Wrapper that invokes Ghidra's analyzeHeadless with the right language/base for
VAG TriCore ECUs. Requires Ghidra installed and $GHIDRA_HOME set (or --ghidra).

    analyze_tricore.py IMAGE.bin --base 0x80000000 --proj /path/proj --name Simos85
    # processor defaults to tricore:LE:32:tc176x (Simos8.5/18, MED17).
    # For MD1/MG1 Aurix use --proc tricore:LE:32:default and the TC1.6 variant.

NOTE: not yet run here — Ghidra is not installed in this environment. Install
Ghidra (>=11.x has solid TriCore) and set GHIDRA_HOME, then this is a one-liner.
"""
import argparse, os, subprocess, sys


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--base", default="0x80000000")
    ap.add_argument("--proc", default="tricore:LE:32:tc176x")
    ap.add_argument("--proj", required=True, help="Ghidra project directory")
    ap.add_argument("--name", required=True, help="Ghidra project/program name")
    ap.add_argument("--ghidra", default=os.environ.get("GHIDRA_HOME"),
                    help="Ghidra install dir (or set $GHIDRA_HOME)")
    ap.add_argument("--post", help="optional postScript (e.g. apply_symbols)")
    a = ap.parse_args()

    if not a.ghidra:
        sys.exit("set --ghidra or $GHIDRA_HOME to your Ghidra install dir")
    headless = os.path.join(a.ghidra, "support", "analyzeHeadless")
    os.makedirs(a.proj, exist_ok=True)

    cmd = [headless, a.proj, a.name,
           "-import", a.image,
           "-processor", a.proc,
           "-loader", "BinaryLoader",
           "-loader-baseAddr", a.base,
           "-scriptPath", os.path.dirname(os.path.abspath(__file__))]
    if a.post:
        cmd += ["-postScript", a.post]
    print("+", " ".join(cmd))
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
