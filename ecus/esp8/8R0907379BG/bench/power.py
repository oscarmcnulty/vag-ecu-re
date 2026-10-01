#!/usr/bin/env python3
"""ESP8 bench power control via the Scanmatik J2534 programmable-voltage (FEPS) output.

Scriptable switchable +12V for precise power-cycling / driving terminal-15 (ignition), using the
standard J2534 call PassThruSetProgrammingVoltage(DeviceID, PinNumber, Voltage_mV).

VERIFIED on this device (Scanmatik 2 Pro, FW1070, smj2534.dll 1.0.0.124):
  - Accepted PinNumber values: 6, 8, 9, 11, 12, 13, 14 (and 0). Pin 25/AUX = ERR_PIN_INVALID.
  - FEPS range per Scanmatik: 5000-24000 mV. Voltage=0xFFFFFFFF (VOLTAGE_OFF) turns the pin off;
    0xFFFFFFFE = SHORT_TO_GROUND.
  - !!! OBD/J1962 pin 6 = CAN-H and pin 14 = CAN-L. NEVER put voltage on 6 or 14 — it will corrupt
    the bus / can damage transceivers. This tool REFUSES 6 and 14. Use a spare pin (8/9/11/12/13),
    whichever your pigtail breaks out to the lead you wired to term15 / switchable VCC.

Battery (term30) is expected to be hardwired always-on; this controls only the switchable FEPS lead.

Usage (32-bit Python that loads smj2534.dll):
  power.py probe --pin 9            # energize pin 9 to 12V for a few s so you can find the lead w/ a DMM
  power.py on    --pin 9            # 12V on
  power.py off   --pin 9            # off
  power.py cycle --pin 9 --off-ms 1500   # off -> wait -> on (power-cycle)

Import for use inside other bench scripts:
  from power import Power; p = Power(); p.on(9); ... ; p.off(9); p.close()
"""
import argparse
import ctypes
import time
from ctypes import c_char_p, c_ulong, POINTER, byref, create_string_buffer

DEFAULT_DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
VOLTAGE_OFF = 0xFFFFFFFF
SHORT_TO_GROUND = 0xFFFFFFFE
CAN_PINS = {6, 14}            # J1962 CAN-H/CAN-L — never energize
VALID_PINS = {8, 9, 11, 12, 13}   # safe FEPS pins (6/14 excluded; 0 ambiguous)


class Power:
    def __init__(self, dll=DEFAULT_DLL):
        self.d = ctypes.WinDLL(dll)
        self.d.PassThruOpen.argtypes = [c_char_p, POINTER(c_ulong)]; self.d.PassThruOpen.restype = c_ulong
        self.d.PassThruClose.argtypes = [c_ulong]; self.d.PassThruClose.restype = c_ulong
        self.d.PassThruSetProgrammingVoltage.argtypes = [c_ulong, c_ulong, c_ulong]
        self.d.PassThruSetProgrammingVoltage.restype = c_ulong
        self.d.PassThruGetLastError.argtypes = [c_char_p]; self.d.PassThruGetLastError.restype = c_ulong
        self.dev = c_ulong(0)
        rc = self.d.PassThruOpen(None, byref(self.dev))
        if rc != 0:
            raise RuntimeError(f"PassThruOpen failed rc={rc}")

    def _err(self):
        b = create_string_buffer(160); self.d.PassThruGetLastError(b)
        return b.value.decode("latin-1", "replace")

    def _set(self, pin, voltage, allow_can=False):
        if pin in CAN_PINS and not allow_can:
            raise ValueError(f"pin {pin} is CAN-H/CAN-L — refusing to energize (use --force-dangerous to override)")
        rc = self.d.PassThruSetProgrammingVoltage(self.dev, pin, voltage)
        if rc != 0:
            raise RuntimeError(f"SetProgrammingVoltage(pin={pin}, V={voltage:#x}) rc={rc} ({self._err()})")
        return rc

    def on(self, pin, mv=12000, allow_can=False):
        self._set(pin, mv, allow_can); return mv

    def off(self, pin, allow_can=False):
        self._set(pin, VOLTAGE_OFF, allow_can)

    def cycle(self, pin, off_ms=1500, mv=12000):
        self.off(pin); time.sleep(off_ms / 1000.0); self.on(pin, mv)

    def close(self):
        try:
            for p in VALID_PINS:
                try: self.d.PassThruSetProgrammingVoltage(self.dev, p, VOLTAGE_OFF)
                except Exception: pass
        finally:
            self.d.PassThruClose(self.dev)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["on", "off", "cycle", "probe"])
    ap.add_argument("--dll", default=DEFAULT_DLL)
    ap.add_argument("--pin", type=int, required=True)
    ap.add_argument("--mv", type=int, default=12000, help="output millivolts (5000-24000)")
    ap.add_argument("--off-ms", type=int, default=1500, help="cycle: off duration")
    ap.add_argument("--secs", type=float, default=5.0, help="probe: how long to hold 12V")
    ap.add_argument("--force-dangerous", action="store_true", help="allow CAN pins 6/14 (DO NOT)")
    a = ap.parse_args()
    if a.pin in CAN_PINS and not a.force_dangerous:
        print(f"[!] pin {a.pin} is CAN-H/CAN-L — refusing. Use 8/9/11/12/13.")
        return
    if a.pin not in VALID_PINS and not a.force_dangerous:
        print(f"[!] pin {a.pin} not in known-safe FEPS pins {sorted(VALID_PINS)}; proceeding anyway is on you.")

    p = Power(a.dll)
    try:
        if a.cmd == "on":
            p.on(a.pin, a.mv, a.force_dangerous); print(f"pin {a.pin} = {a.mv} mV (ON)")
        elif a.cmd == "off":
            p.off(a.pin, a.force_dangerous); print(f"pin {a.pin} = OFF")
        elif a.cmd == "cycle":
            print(f"pin {a.pin}: OFF {a.off_ms}ms ...")
            p.cycle(a.pin, a.off_ms, a.mv); print(f"pin {a.pin} = {a.mv} mV (ON) — power-cycled")
        elif a.cmd == "probe":
            print(f"pin {a.pin}: energizing {a.mv} mV for {a.secs:.0f}s — measure the pigtail leads with a DMM now")
            p.on(a.pin, a.mv, a.force_dangerous)
            time.sleep(a.secs)
            p.off(a.pin, a.force_dangerous)
            print(f"pin {a.pin} = OFF")
    finally:
        p.close()


if __name__ == "__main__":
    main()
