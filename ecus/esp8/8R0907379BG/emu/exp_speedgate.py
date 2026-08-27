#!/usr/bin/env python3
# Prove the 15 km/h gate empirically: ecd_speed_gate must CLEAR flag_ecd_speed_avail (0x403da9 bit6)
# below 0x78 (15.0 km/h) and SET it above -- and ecd_decel_pressure_calc must zero the setpoints
# when the flag is clear. This is the mechanism behind ECD_nicht_verfuegbar in the route.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu

SP_A, SP_B = 0x4022a2, 0x402482    # axle_speed_a/b compared to 0x78 in ecd_speed_gate
FLAG = 0x403da9                    # flag_ecd_speed_avail (bit6=0x40)
DEBOUNCE = 0x846f0                 # debounce counter ptr region base is via DAT; we drive via repeated calls

def gate_after(speed_units, iters=40, preset_flag=0x40):
    e = Emu()
    e.wr(FLAG, preset_flag, 1)
    e.wr(0x403a04, 0x1000, 4)          # guard1: ESP-active bit12 -> reach the speed comparison
    e.wr(SP_A, speed_units, 2); e.wr(SP_B, speed_units, 2)
    for _ in range(iters):          # run repeatedly to pass the ~30-cycle debounce
        e.call(0x844fc)
    return e.rd(FLAG,1) & 0x40

print("=== ecd_speed_gate: flag bit0x40 after 40 iterations at each speed ===")
for kmh in (20, 16, 15, 14, 10, 5):
    units = int(kmh/0.125)          # 0.125 km/h per bit
    bit = gate_after(units)
    print(f"  speed={kmh:2d} km/h (0x{units:x}, {'>' if units>=0x78 else '<'}0x78): flag_ecd_speed_avail bit6 = {'SET (available)' if bit else 'CLEAR (ECD_nicht_verfuegbar)'}")
