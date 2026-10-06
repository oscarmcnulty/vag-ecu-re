#!/usr/bin/env python3
# Settle the ESP_05 status->sig map: apply captured RAM image, seed esp05_status_src (0x405f68),
# run com_signal_compose (0x6b00), observe which esp05_sig bytes (0x405e81..0x405e98) change.
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

RAMCSV=os.path.join(os.path.dirname(__file__),'..','analysis','ram_bases.csv')
STATUS=0x405f68   # esp05_status_src (+0..+6 read by com_signal_compose)
SIG0,SIG1=0x405e81,0x405e99  # esp05 sig storage range

def apply_ram(e):
    with open(RAMCSV) as f:
        for row in csv.DictReader(f):
            e.wr(int(row['ram_addr'],16), int(row['value'],16), 4)

def run(seed_status):
    e=Emu()
    apply_ram(e)
    # seed status struct bytes
    for i,b in enumerate(seed_status):
        e.wr(STATUS+i, b, 1)
    # snapshot sig region before
    before=[e.rd(a,1) for a in range(SIG0,SIG1)]
    r=e.call(0x6b00, maxinsn=2000000)
    after=[e.rd(a,1) for a in range(SIG0,SIG1)]
    return r, before, after

print("=== com_signal_compose with esp05_status_src = all 0x00 then all 0xFF ===")
r0,b0,a0=run([0x00]*8)
rF,bF,aF=run([0xFF]*8)
print("call(0x00)->",r0[0], " call(0xFF)->",rF[0])
print("addr      zero  ff   (sig byte after compose)")
for idx,a in enumerate(range(SIG0,SIG1)):
    z=a0[idx]; f=aF[idx]
    mark=" <-- CHANGES with status" if z!=f else ""
    print(f"0x{a:08x}  0x{z:02x}  0x{f:02x}{mark}")
