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

    A1 = bytes([0xA1, 0x0F, 0x8A, 0xFF, 0x32, 0xFF])

    def _handle_ctrl(self, pl):
        """Answer the ECU's channel-test (0xA3 -> reply 0xA1). Returns True if frame was control."""
        if not pl:
            return False
        if pl[0] == 0xA3:                 # ECU channel test -> must reply 0xA1 or it drops us
            self.c.write(self.tx, self.A1)
            return True
        if pl[0] in (0xA1,):              # reply to our own test
            return True
        return False

    def keepalive(self, force=False):
        now = time.time()
        if force or now - self._last_ka > 0.4:
            self._last_ka = now
            self.c.write(self.tx, bytes([0xA3]))

    def maintain(self, secs):
        """Idle between requests: keep the channel alive (send our 0xA3, answer the ECU's)."""
        t = time.time()
        while time.time() - t < secs:
            self.keepalive()
            r = self.c.read(10)
            if r and r[0] == self.rx:
                self._handle_ctrl(r[1])

    def _send_frames(self, kwp):
        """TP2.0 data TX, multi-frame safe. First frame carries the 2-byte length + up to 5 KWP
        bytes; subsequent frames carry up to 7 each. Non-last frames use op0 (more, ACK-expected)
        and we wait for the ECU's 0xB ACK before the next; last frame uses op1 (last, ACK)."""
        n = len(kwp)
        chunks = [kwp[:5]]
        rest = kwp[5:]
        while rest:
            chunks.append(rest[:7]); rest = rest[7:]
        for idx, ch in enumerate(chunks):
            last = idx == len(chunks) - 1
            op = 1 if last else 0
            if idx == 0:
                frame = bytes([(op << 4) | (self.seq & 0xF), (n >> 8) & 0xFF, n & 0xFF]) + ch
            else:
                frame = bytes([(op << 4) | (self.seq & 0xF)]) + ch
            self.c.write(self.tx, frame)
            self.seq = (self.seq + 1) & 0xF
            if not last:                      # wait for the ECU's TP ACK before next frame
                t = time.time()
                while time.time() - t < 0.5:
                    rr = self._rd(40)
                    if not rr:
                        continue
                    rid, pl = rr
                    if rid == self.rx and pl and (pl[0] >> 4) == 0xB:
                        break
                    if rid == self.rx:
                        self._handle_ctrl(pl)

    def request(self, kwp: bytes, timeout=2.0, pending_max=8.0):
        self._send_frames(kwp)
        data = bytearray()
        total = None
        t = time.time()
        hard = time.time() + pending_max   # overall cap across responsePending (0x78) repeats
        while time.time() - t < timeout and time.time() < hard:
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
            if op in (0x0, 0x1, 0x2, 0x3):   # data: 0/2=more, 1/3=last; 0/1=ACK-expected
                rseq = pl[0] & 0xF
                payload = pl[1:]
                if total is None:
                    if len(payload) >= 2:
                        total = (payload[0] << 8) | payload[1]
                        data += payload[2:]
                    else:
                        data += payload       # malformed/short first frame; keep what we got
                else:
                    data += payload
                if op in (0x0, 0x1):          # sender is waiting for an ACK
                    self.c.write(self.tx, bytes([0xB0 | ((rseq + 1) & 0xF)]))
                if op in (0x1, 0x3):          # last packet of a response
                    resp = bytes(data[:total]) if total else bytes(data)
                    if len(resp) >= 3 and resp[0] == 0x7F and resp[2] == 0x78:
                        # responsePending: ECU is busy (e.g. descending to boot loader) -> keep
                        # waiting for the real response (reset assembly, extend the per-response window)
                        data = bytearray(); total = None; t = time.time()
                        self.keepalive()
                        continue
                    break
            else:
                self._handle_ctrl(pl)      # answer ECU channel-test etc.
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
