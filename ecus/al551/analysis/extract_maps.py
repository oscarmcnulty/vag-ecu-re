#!/usr/bin/env python3
"""Regenerate the value-bearing calibration/map CSVs for the AL551 from the firmware image.
These CSVs carry firmware map values (breakpoints, output columns, grid data) and so are
DERIVED WORK (gitignored) -- this committed script regenerates them locally.

Usage: python3 extract_maps.py <firmware.bin>   (default: ../firmware/8R_full_flash.bin)
Writes torque_maps.csv, shift_curves.csv, shift_blocks.csv, cal_axes.csv, cal_ptr_tables.csv
into this directory.
"""
import struct, sys, os, csv, collections
HERE = os.path.dirname(os.path.abspath(__file__))
fw = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "firmware", "8R_full_flash.bin")
d = open(fw, "rb").read()
u16 = lambda o: struct.unpack(">H", d[o:o+2])[0]
u32 = lambda o: struct.unpack(">I", d[o:o+4])[0]
CAL_LO, CAL_HI = 0x190000, 0x1FFD60
W = lambda n: open(os.path.join(HERE, n), "w")

# --- torque-limit Kennfelder: hdr[0,8] + col axis [0 48 102 198 300 402 498 600] ---
with W("torque_maps.csv") as f:
    w = csv.writer(f); w.writerow(["kennfeld_addr","stride","col_axis_Nm","grid_max_Nm","note"])
    o = 0x1b0000; n = 0
    while o < 0x1b3000 - 0xcc:
        if u16(o) == 0 and u16(o+2) == 8 and [u16(o+0x1c+2*i) for i in range(8)] == [0,48,102,198,300,402,498,600]:
            gmax = max(u16(o+0x2c+2*i) for i in range(80))
            w.writerow([f"0x{o:06x}", "0xcc(204B)", "0 48 102 198 300 402 498 600", gmax,
                        "input-torque-limit Kennfeld (10x8), gear x mode selected"]); n += 1; o += 0xcc
        else: o += 2
    print(f"torque_maps.csv: {n} Kennfelder")

# --- shift curves: shared input axis [1340..7500] + output column ---
SIG = [1340,2015,3000,3770,4885,6300,7500]
with W("shift_curves.csv") as f:
    w = csv.writer(f); w.writerow(["record_addr","input_axis","output_col(tunable)","out_max"])
    n = 0
    for o in range(0x1d2000, 0x1e2000-28, 2):
        if [u16(o+2*i) for i in range(7)] == SIG:
            out = [u16(o+0xe+2*i) for i in range(7)]
            w.writerow([f"0x{o:06x}", " ".join(map(str,SIG)), " ".join(map(str,out)), max(out)]); n += 1
    print(f"shift_curves.csv: {n} curves")

# --- shift registry blocks ---
with W("shift_blocks.csv") as f:
    w = csv.writer(f); w.writerow(["registry_slot","block_addr","has_6300","has_7500"])
    reg = 0x5c778; n = 0
    for i in range(114):
        v = u32(reg+i*4)
        if not (0x1d0000 <= v < 0x1e2000): continue
        cells = [u16(v+2*j) for j in range(0x18c//2)]
        w.writerow([i, f"0x{v:06x}", 6300 in cells, 7500 in cells]); n += 1
    print(f"shift_blocks.csv: {n} blocks")

# --- calibration axes (self-describing [0,count,breakpoints]) ---
ref_sites = {}
for o in range(0x040000, 0x17FE00-3, 4):
    v = u32(o)
    if CAL_LO <= v < CAL_HI: ref_sites.setdefault(v, []).append(o)
def is_axis(a):
    if a+4 > CAL_HI or u16(a) != 0: return None
    n = u16(a+2)
    if not (2 <= n <= 32) or a+4+2*n > CAL_HI: return None
    v = [u16(a+4+2*i) for i in range(n)]
    return v if all(v[i] < v[i+1] for i in range(n-1)) else None
def phys(v):
    mx = v[-1]; sv = [x-65536 if x > 32767 else x for x in v]
    if mx <= 110: return "pct/gear/index"
    if any(x < 0 for x in sv) or mx > 60000: return "signed_delta/torque"
    if 400 <= mx <= 8500 and v[-1]-v[0] > 1500: return "speed[rpm]"
    if 8500 < mx <= 16000: return "speed_hi/kmh*100"
    if 16000 < mx <= 32000: return "pressure[mbar]/Nm"
    if mx <= 1600: return "temp/lowspeed"
    return "?"
axes = [(a, is_axis(a)) for a in sorted(ref_sites) if is_axis(a)]
with W("cal_axes.csv") as f:
    w = csv.writer(f); w.writerow(["axis_addr","count","min","max","n_refs","first_ref","phys_guess","breakpoints"])
    for a, v in axes:
        w.writerow([f"0x{a:06x}", len(v), v[0], v[-1], len(ref_sites[a]), f"0x{ref_sites[a][0]:06x}",
                    phys(v), " ".join(map(str, v))])
print(f"cal_axes.csv: {len(axes)} axes")

# --- calibration pointer tables (runs of >=4 word-aligned CAL pointers) ---
with W("cal_ptr_tables.csv") as f:
    w = csv.writer(f); w.writerow(["table_start","table_end","n_ptrs"])
    o = 0x040000; run = []; nt = 0
    while o < 0x17FE00-3:
        v = u32(o)
        if CAL_LO <= v < CAL_HI: run.append(o)
        else:
            if len(run) >= 4: w.writerow([f"0x{run[0]:06x}", f"0x{run[-1]:06x}", len(run)]); nt += 1
            run = []
        o += 4
    if len(run) >= 4: w.writerow([f"0x{run[0]:06x}", f"0x{run[-1]:06x}", len(run)]); nt += 1
    print(f"cal_ptr_tables.csv: {nt} tables")
