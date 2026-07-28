#!/usr/bin/env python3
"""Resolve the function-pointer dispatch tables that the decompiler leaves unrecovered.

Ghidra emits "Could not recover jumptable ... Too many branches" when a computed call goes
through a function-pointer array it cannot enumerate (rendered as `(*(code *)(&PTR_x_ADDR)[i])()`).
The table itself is plain data in the bin, so we recover it directly: for every degraded
jumptable function, pull the table base out of the `PTR_<name>_<addr>` symbol, walk the 32-bit
LE pointer array in the firmware until it stops looking like code, and emit the resolved targets.

Outputs (both under analysis/, regenerable):
  dispatch_tables.csv        function,site_c_line,table_base,n_entries,target  (one row per target)
  dispatch_targets_new.txt   resolved targets that are NOT yet in function_entries.txt

Usage: resolve_dispatch_tables.py <ecu_dir>   (e.g. ecus/simos85)
"""
import csv, os, re, struct, sys

BASE = 0x80000000
CODE_LO, CODE_HI = 0x80020000, 0x80200000        # plausible .text range for a real handler
MAX_ENTRIES = 128                                 # table walk safety cap

def is_code_ptr(p):
    return CODE_LO <= (p & 0xfffffffe) < CODE_HI

def main(ecu):
    bin_path = os.path.join(ecu, 'firmware', '8R0907551F_Original.bin')
    man_path = os.path.join(ecu, 'analysis', 'decompiles_r.manifest.csv')
    dec_dir  = os.path.join(ecu, 'analysis', 'decompiles_r')
    ent_path = os.path.join(ecu, 'analysis', 'function_entries.txt')
    fw = open(bin_path, 'rb').read()

    def rd32(va):
        o = va - BASE
        if o < 0 or o + 4 > len(fw):
            return None
        return struct.unpack_from('<I', fw, o)[0]

    # degraded jumptable functions, from the manifest
    jt_fns = [r['addr'] for r in csv.DictReader(open(man_path))
              if r['status'] == 'degraded' and r['reason'] == 'could-not-recover-jumptable']

    # the pointer-table base is the trailing hex group of the PTR_<name>_<hex8> symbol that is
    # immediately array-indexed at the dispatch site: (&PTR_foo_80091094)[iVar4]
    site_re = re.compile(r'&(?:PTR|DAT)_[A-Za-z0-9_]*?_([0-9a-fA-F]{8})\)\s*\[')

    rows = []
    seen_tables = set()
    for a in jt_fns:
        f = os.path.join(dec_dir, a + '.c')
        if not os.path.exists(f):
            continue
        for m in site_re.finditer(open(f).read()):
            base = int(m.group(1), 16)
            if not (CODE_LO <= base < CODE_HI) or base in seen_tables:
                continue
            # walk the table
            targets = []
            va = base
            while len(targets) < MAX_ENTRIES:
                p = rd32(va)
                if p is None or not is_code_ptr(p):
                    break
                targets.append(p & 0xfffffffe)
                va += 4
            if not targets:
                continue
            seen_tables.add(base)
            for i, t in enumerate(targets):
                rows.append((a, hex(base), i, len(targets), hex(t)))

    out_csv = os.path.join(ecu, 'analysis', 'dispatch_tables.csv')
    with open(out_csv, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['function', 'table_base', 'index', 'n_entries', 'target'])
        w.writerows(rows)

    # which resolved targets are not yet known function entries?
    known = set()
    if os.path.exists(ent_path):
        for ln in open(ent_path):
            ln = ln.strip()
            if ln and not ln.startswith('#'):
                known.add(int(ln.replace('0x', ''), 16))
    targets = sorted({int(r[4], 16) for r in rows})
    new = [t for t in targets if t not in known]
    out_new = os.path.join(ecu, 'analysis', 'dispatch_targets_new.txt')
    with open(out_new, 'w') as fh:
        for t in new:
            fh.write('0x%08x\n' % t)

    print(f"dispatch tables resolved: {len(seen_tables)}")
    print(f"  functions with a table:  {len({r[0] for r in rows})}")
    print(f"  total target entries:    {len(rows)}  ({len(targets)} distinct)")
    print(f"  targets already known:   {len(targets)-len(new)}")
    print(f"  NEW targets (not entries): {len(new)}  -> {out_new}")
    print(f"  -> {out_csv}")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'ecus/simos85')
