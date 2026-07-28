#!/usr/bin/env python3
"""Recover return types for the decompiler-degraded functions from their disasm.

Ghidra guts ~174 functions (division/CSFR idioms -> the "space" restart) and types
them `void`, even the getters. But we have their disassembly (analysis/disasm_r/).
This decides, per function, whether it returns a value and in which register, by
combining two signals:

  1. intra-function: is d2 / d2d3 (data) or a2 (pointer) written by a value-producing
     instruction (i.e. a result register is live) -- from disasm_r/<addr>.asm
  2. inter-function: does ANY caller consume the return -- i.e. `= <name>(` appears
     in decompiles_r (Ghidra shows the assignment at the call site even for a
     void-typed callee). This is the decisive "it really returns something" signal.

Emits analysis/recovered_returns.csv (addr,name,ret_type,ret_reg,caller_consumed,evidence)
for ApplyReturns.java to consume. Return-type only -- params are left dynamic (low risk).
"""
import csv, os, re, sys, glob

ANALYSIS = sys.argv[1] if len(sys.argv) > 1 else "ecus/simos85/analysis"
DIS = os.path.join(ANALYSIS, "disasm_r")
DEC = os.path.join(ANALYSIS, "decompiles_r")
OUT = os.path.join(ANALYSIS, "recovered_returns.csv")

# instructions that do NOT produce a result value in their first operand
NON_RESULT = re.compile(r"^(st\.|cmp|j|ret|nop|disable|enable|loop|isync|dsync|debug|dsvnc|mtcr|trapv|rslcx|svlcx|bisr)")
REG = re.compile(r"^(d\d+(?:/d\d+)?|a\d+)$")


def dest_reg(mnem_operands):
    """First operand of a TriCore insn is the destination (dN, aN, or dN/dM pair)."""
    parts = mnem_operands.split(None, 1)
    if len(parts) < 2:
        return None, parts[0]
    mnem = parts[0]
    first = parts[1].split(",")[0].strip()
    return (first if REG.match(first) else None), mnem


def analyze_disasm(path):
    """Return (has_d2_result, has_a2_result) from a function's disasm."""
    d2 = a2 = False
    for line in open(path, encoding="latin-1"):
        line = line.strip()
        if not line or line.startswith(";") or ":" not in line:
            continue
        body = line.split(":", 1)[1].strip()          # drop "addr:"
        if not body:
            continue
        reg, mnem = dest_reg(body)
        if reg is None or NON_RESULT.match(mnem):
            continue
        if reg == "d2" or reg == "d2/d3":
            d2 = True
        elif reg == "a2":
            a2 = True
    return d2, a2


def build_caller_index():
    """Map every function-name -> whether its return is consumed as an rvalue anywhere."""
    consumed = {}
    # scan all decompiles once; record `<lhs> = <name>(` occurrences
    pat = re.compile(r"=\s*([A-Za-z_]\w*)\s*\(")
    for f in glob.glob(os.path.join(DEC, "*.c")):
        try:
            txt = open(f, encoding="latin-1").read()
        except Exception:
            continue
        for m in pat.finditer(txt):
            consumed[m.group(1)] = True
    return consumed


def main():
    consumed = build_caller_index()
    rows = []
    for path in sorted(glob.glob(os.path.join(DIS, "*.asm"))):
        addr = "0x" + os.path.basename(path)[:-4]
        header = open(path, encoding="latin-1").readline()
        m = re.search(r";\s*(\S+)\s*@", header)
        name = m.group(1) if m else os.path.basename(path)[:-4]
        d2, a2 = analyze_disasm(path)
        is_consumed = consumed.get(name, False)
        # decision: a function "returns" iff a caller consumes it. storage from disasm.
        if is_consumed and d2:
            ret_type, ret_reg, ev = "undefined4", "d2", "d2-result+caller"
        elif is_consumed and a2 and not d2:
            ret_type, ret_reg, ev = "void *", "a2", "a2-result+caller"
        elif is_consumed:
            ret_type, ret_reg, ev = "undefined4", "d2", "caller-only(default d2)"
        else:
            ret_type, ret_reg, ev = "", "", "void(no consumer)"
        rows.append((addr, name, ret_type, ret_reg, is_consumed, ev))

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["addr", "name", "ret_type", "ret_reg", "caller_consumed", "evidence"])
        w.writerows(rows)

    # Consume the analysis where these functions are actually READ: annotate the
    # disasm_r header (the decompiler can't type them, so put the recovered sig here).
    annotated = 0
    for addr, name, ret_type, ret_reg, consumed, ev in rows:
        path = os.path.join(DIS, addr[2:] + ".asm")
        if not os.path.exists(path):
            continue
        lines = open(path, encoding="latin-1").read().splitlines()
        lines = [ln for ln in lines if not ln.startswith("; RECOVERED")]   # idempotent
        note = (f"; RECOVERED: returns {ret_type} in {ret_reg} (a caller consumes the result; "
                f"decompiler mis-typed void)") if ret_type else \
               "; RECOVERED: void (no caller consumes a return)"
        ins = next((i for i, ln in enumerate(lines) if ln.startswith("; stored return")), 0)
        lines.insert(ins + 1, note)
        open(path, "w", encoding="latin-1").write("\n".join(lines) + "\n")
        annotated += 1

    n_ret = sum(1 for r in rows if r[2])
    print(f"{len(rows)} degraded fns analyzed -> {OUT}")
    print(f"  returns a value: {n_ret}   void: {len(rows) - n_ret}   disasm headers annotated: {annotated}")


if __name__ == "__main__":
    main()
