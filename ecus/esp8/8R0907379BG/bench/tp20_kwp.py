#!/usr/bin/env python3
"""ESP8 (8R0907379BG) diagnostics over VAG TP2.0 + KWP2000 — WORKING (2026-10-01).

This B8 ABS is a TP2.0/KWP2000 module, NOT UDS — which is why every UDS/ISO-TP probe (0x6b4 etc.)
was silent. Confirmed working session entry:
  setup 0xC0 -> 0x200 (dest 0x03=ABS)  ->  0x203: 00 d0 00 03 a3 04 01
  channel: we TX -> 0x4a3, we RX <- 0x300   (NB direction: the module RECEIVES on 0x4a3 — it is in
                                             the firmware RX filter; it TRANSMITS the channel on 0x300)
  params A0 -> A1 (a1 0f 8a ff 4a ff)
  KWP 10 89 (StartDiagnosticSession) -> 50 89  POSITIVE

Requires ignition switch ON (module awake/broadcasting). Timing is tight: the channel is dropped if
the parameter request doesn't follow the 0xD0 within ~1s, so A0 is sent the instant the first 0xD0
arrives (and resent on each retransmit). A background channel-test (0xA3) keepalive holds the session.

Data PDU: [op<<4|seq, len_hi, len_lo, kwp...]; op 0x1=last+ACK, 0x0=more, 0xB=ACK, 0xA3=channel test,
0xA0/0xA1=params, 0xA8=disconnect.

Usage (32-bit python, ignition ON):
  tp20_kwp.py                       # open session, run a default KWP probe set
  tp20_kwp.py 1089 1A87 1802FFFF    # open session, then send these KWP requests (hex)
"""
import os
import sys
import time
from ctypes import c_ulong, c_void_p

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN  # noqa: E402

SETUP_ID = 0x200
DEST = 0x03
CLEAR_RX_BUFFER = 0x08
NRC = {0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFnNotSupported",
       0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange", 0x33: "securityAccessDenied",
       0x35: "invalidKey", 0x78: "responsePending"}


class TP20KWP:
    def __init__(self, can):
        self.c = can
        self.tx = None
        self.rx = None
        self.seq = 0
        self._last_ka = 0.0
        try:
            self.c.d.PassThruIoctl.argtypes = [c_ulong, c_ulong, c_void_p, c_void_p]
            self.c.d.PassThruIoctl.restype = c_ulong
        except Exception:
            pass

    def _drain(self):
        try: self.c.d.PassThruIoctl(self.c.ch, CLEAR_RX_BUFFER, None, None)
        except Exception: pass

    def _rd(self, ms):
        t = time.time()
        while (time.time() - t) * 1000 < ms:
            r = self.c.read(2)
            if r:
                return r
        return None

    def open(self, timeout=2.0):
        """Channel setup + parameters. Returns True on an open, parameterised channel."""
        self._drain()
        A0 = bytes([0xA0, 0x0F, 0x8A, 0xFF, 0x32, 0xFF])
        self.c.write(SETUP_ID, bytes([DEST, 0xC0, 0x00, 0x10, 0x00, 0x03, 0x01]))
        t = time.time()
        while time.time() - t < timeout:
            r = self._rd(20)
            if not r:
                continue
            rid, pl = r
            if rid == 0x200 + DEST and len(pl) >= 7 and pl[1] == 0xD0:
                # parse channel ids; this module: we RX = bytes2-3, we TX = bytes4-5
                self.rx = ((pl[3] & 0xF) << 8) | pl[2]
                self.tx = ((pl[5] & 0xF) << 8) | pl[4]
                self.c.write(self.tx, A0)              # instant params, resend on each 0xD0
            elif self.tx is not None and rid == self.rx and pl and pl[0] == 0xA1:
                return True
            elif rid == 0x200 + DEST and len(pl) >= 2 and pl[1] in (0xD6, 0xD7, 0xD8):
                return False
        return False

    def keepalive(self, force=False):
        now = time.time()
        if force or now - self._last_ka > 0.4:
            self._last_ka = now
            self.c.write(self.tx, bytes([0xA3]))

    def request(self, kwp: bytes, timeout=2.0):
        n = len(kwp)
        self.c.write(self.tx, bytes([0x10 | (self.seq & 0xF), (n >> 8) & 0xFF, n & 0xFF]) + kwp)
        self.seq = (self.seq + 1) & 0xF
        data = bytearray()
        total = None
        t = time.time()
        while time.time() - t < timeout:
            r = self._rd(40)
            if not r:
                self.keepalive()
                continue
            rid, pl = r
            if rid != self.rx or not pl:
                continue
            op = pl[0] >> 4
            if op == 0xB:            # ACK of our packet
                continue
            if op in (0x0, 0x1):     # data
                rseq = pl[0] & 0xF
                payload = pl[1:]
                if total is None:
                    total = (payload[0] << 8) | payload[1]
                    data += payload[2:]
                else:
                    data += payload
                self.c.write(self.tx, bytes([0xB0 | ((rseq + 1) & 0xF)]))   # ACK
                if op == 0x1:
                    break
            else:
                self.keepalive()
        return bytes(data[:total]) if total else (bytes(data) or None)

    def close(self):
        try: self.c.write(self.tx, bytes([0xA8]))
        except Exception: pass


def kfmt(r):
    if r is None:
        return "no response"
    if r[0] == 0x7F:
        nrc = r[2] if len(r) > 2 else 0
        return f"7F {NRC.get(nrc, hex(nrc))}  [{r.hex(' ')}]"
    asc = bytes(b if 32 <= b < 127 else 46 for b in r).decode()
    return f"POSITIVE [{r.hex(' ')}]  {asc}"


def main():
    args = sys.argv[1:]
    reqs = [bytes.fromhex(a) for a in args] if args else None
    c = RawCAN()
    tp = TP20KWP(c)
    try:
        if not tp.open():
            print("[!] could not open TP2.0 channel — is the ignition switch ON?")
            return
        print(f"[*] TP2.0 channel OPEN: we TX->0x{tp.tx:03x}, we RX<-0x{tp.rx:03x}")
        # always start a diagnostic session first
        print(f"  StartDiagnosticSession 10 89 -> {kfmt(tp.request(bytes.fromhex('1089')))}")
        if reqs is None:
            # default probe set: VAG KWP identification + DTC read
            reqs = [bytes.fromhex(h) for h in
                    ("1A86", "1A87", "1A9B", "1A91", "1A94", "1802FFFF", "2110")]
        for kwp in reqs:
            print(f"  {kwp.hex().upper():12s} -> {kfmt(tp.request(kwp))}")
            tp.keepalive(force=True)
    finally:
        tp.close()
        c.close()


if __name__ == "__main__":
    main()
