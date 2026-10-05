#!/usr/bin/env python3
"""Sniff module A (the ESP8's 2nd CAN bus) on the SM2 Pro's SECOND CAN channel = CAN_PS on OBD pins
3(H)/11(L), wired to module A T38a 37(H)/24(L). Confirms the CAN2 wiring/termination before building
the dual-bus emulation. Pin-selectable CAN (CAN_PS) needs the J1962_PINS config; the exact SConfig
param id is probed empirically (SM2-specific), then we pass-all and list every id (expect 0x060).

Run: tools\\py311x86\\python.exe bench\\can2_sniff.py [--secs N]
"""
import argparse, collections, ctypes, time
from ctypes import (POINTER, Structure, byref, c_char_p, c_ubyte, c_ulong, c_void_p,
                    create_string_buffer, pointer)

DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
CAN, CAN_PS = 5, 0x8004
PASS_FILTER, SET_CONFIG = 1, 0x03
TX_MSG_TYPE = 0x0001

class MSG(Structure):
    _fields_ = [("ProtocolID", c_ulong), ("RxStatus", c_ulong), ("TxFlags", c_ulong),
                ("Timestamp", c_ulong), ("DataSize", c_ulong), ("ExtraDataIndex", c_ulong),
                ("Data", c_ubyte * 4128)]
class SCONFIG(Structure):
    _fields_ = [("Parameter", c_ulong), ("Value", c_ulong)]
class SCONFIG_LIST(Structure):
    _fields_ = [("NumOfParams", c_ulong), ("ConfigPtr", POINTER(SCONFIG))]

d = ctypes.WinDLL(DLL)
for n, a in [("PassThruOpen", [c_char_p, POINTER(c_ulong)]), ("PassThruClose", [c_ulong]),
             ("PassThruConnect", [c_ulong, c_ulong, c_ulong, c_ulong, POINTER(c_ulong)]),
             ("PassThruDisconnect", [c_ulong]),
             ("PassThruReadMsgs", [c_ulong, POINTER(MSG), POINTER(c_ulong), c_ulong]),
             ("PassThruStartMsgFilter", [c_ulong, c_ulong, POINTER(MSG), POINTER(MSG), POINTER(MSG), POINTER(c_ulong)]),
             ("PassThruIoctl", [c_ulong, c_ulong, c_void_p, c_void_p]),
             ("PassThruGetLastError", [c_char_p])]:
    f = getattr(d, n); f.argtypes = a; f.restype = c_ulong

def err():
    b = create_string_buffer(160); d.PassThruGetLastError(b); return b.value.decode("latin-1", "replace")
def mk(cid):
    m = MSG(); m.ProtocolID = CAN_PS; data = cid.to_bytes(4, "big"); m.DataSize = 4
    for i, x in enumerate(data): m.Data[i] = x
    return m

def set_pins(ch):
    """Probe the SM2's J1962_PINS SConfig id + value encoding for CAN2 = pins 3(H)/11(L)."""
    for pid in (0x1C, 0x1B, 0x1D, 0x1E, 0x1A, 0x1F, 0x20, 0x21, 0x22):
        for val in (0x030B, 0x0B03):   # (H<<8)|L  or  (L<<8)|H
            sc = SCONFIG(pid, val); scl = SCONFIG_LIST(1, pointer(sc))
            rc = d.PassThruIoctl(ch, SET_CONFIG, byref(scl), None)
            if rc == 0:
                print(f"  [pins set] J1962_PINS id=0x{pid:02x} val=0x{val:04x} OK"); return True
    print("  [!] could not set J1962_PINS via any candidate id/val"); return False

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--secs", type=float, default=4.0); a = ap.parse_args()
    dev = c_ulong(0)
    assert d.PassThruOpen(None, byref(dev)) == 0, "PassThruOpen failed"
    ch = c_ulong(0)
    rc = d.PassThruConnect(dev, CAN_PS, 0, 500000, byref(ch))
    print(f"PassThruConnect(CAN_PS) rc={rc} {'' if rc==0 else err()}")
    if rc != 0:
        d.PassThruClose(dev); return
    set_pins(ch)
    mask, patt = mk(0), mk(0); fid = c_ulong(0)
    d.PassThruStartMsgFilter(ch, PASS_FILTER, byref(mask), byref(patt), None, byref(fid))
    print(f"=== sniff CAN2 (module A, pins 3/11) {a.secs}s ===")
    seen = collections.Counter(); sample = {}
    t0 = time.time()
    while time.time() - t0 < a.secs:
        rx = MSG(); cnt = c_ulong(1)
        if d.PassThruReadMsgs(ch, byref(rx), byref(cnt), 100) == 0 and cnt.value and rx.DataSize >= 4:
            if rx.RxStatus & TX_MSG_TYPE: continue
            cid = int.from_bytes(bytes(rx.Data[:4]), "big")
            seen[cid] += 1; sample.setdefault(cid, bytes(rx.Data[4:rx.DataSize]).hex(" "))
    print(f"CAN2 sniff: {sum(seen.values())} frames, {len(seen)} unique ids")
    for cid in sorted(seen):
        print(f"  0x{cid:03x} x{seen[cid]:<5d} {sample[cid]}")
    d.PassThruDisconnect(ch); d.PassThruClose(dev)

if __name__ == "__main__":
    main()
