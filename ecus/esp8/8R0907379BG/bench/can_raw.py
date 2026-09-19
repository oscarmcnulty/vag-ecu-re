#!/usr/bin/env python3
"""ESP8 (8R0907379BG) raw-CAN bench tool over J2534: sniff + replay/watch.

Runs with the 32-bit Python that can load smj2534.dll (the DLL is 32-bit).
Chassis/sensor CAN, 500 kbps, pins 37(H)/24(L) per bench_harness_pinout.md.

Subcommands:
  sniff [--secs N]              passive: list every RX id + count + a sample.
  wake  [--secs N] [--hz H]     transmit the ECU's accepted RX ids (from the
                                firmware receive filter 0xafae0, hard-coded
                                below) as counter+CRC frames while watching for
                                the ECU to leave pre-operational state (any tx
                                id other than the 0x060 heartbeat).

The counter/CRC content follows the ECU's own 0x060 E2E scheme (CRC-8/SAE-J1850
over bytes 0..6, counter in byte6) — see nm_crc.py. This is a best-effort
"network is alive" stimulus; messages the ECU E2E-checks with a per-id data-id
will still be rejected, which is itself an informative result.

Example:
  <py311x86>\\python.exe can_raw.py sniff --secs 4
  <py311x86>\\python.exe can_raw.py wake  --secs 12 --hz 10
"""
import argparse
import collections
import ctypes
import time
from ctypes import (POINTER, Structure, byref, c_char_p, c_ubyte, c_ulong,
                    create_string_buffer)

DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
CAN = 5
PASS_FILTER = 1
TX_MSG_TYPE = 0x0001
HEARTBEAT_ID = 0x060

# ECU accepted RX ids, decoded from the firmware receive filter @0xafae0
# (big-endian u32 array). 225 ids, max 0x258 — NB there is NO 0x4xx NM-range id.
ACCEPTED_IDS = [
    0x1,0x2,0x3,0x4,0x5,0x6,0x8,0x9,0xa,0xb,0x21,0x23,0x24,0x25,0x26,0x27,0x3c,
    0x3d,0x3e,0x3f,0x43,0x45,0x47,0x48,0x49,0x4a,0x4b,0x4c,0x4d,0x4e,0x4f,0x52,
    0x53,0x54,0x56,0x57,0x58,0x59,0x5a,0x62,0x65,0x66,0x67,0x68,0x69,0x6a,0x6b,
    0x6c,0x6d,0x6e,0x70,0x74,0x75,0x76,0x77,0x78,0x79,0x7a,0x7b,0x7c,0x80,0x81,
    0x82,0x83,0x84,0x85,0x8c,0x90,0x91,0x92,0x95,0x96,0x98,0x99,0x9a,0x9b,0x9d,
    0x9e,0x9f,0xa0,0xa3,0xa4,0xa5,0xa6,0xa7,0xa8,0xa9,0xaa,0xab,0xac,0xae,0xaf,
    0xb0,0xb1,0xb3,0xba,0xbb,0xbc,0xbd,0xc0,0xc1,0xc2,0xe0,0xec,0xf7,0xf8,0xf9,
    0xfa,0xfb,0xfc,0xfd,0xfe,0xff,0x100,0x101,0x102,0x103,0x104,0x105,0x106,0x107,
    0x108,0x109,0x10a,0x10b,0x10c,0x111,0x112,0x113,0x114,0x115,0x116,0x125,0x126,
    0x127,0x128,0x12b,0x12c,0x12f,0x130,0x131,0x13d,0x167,0x168,0x169,0x16a,0x16b,
    0x16c,0x16d,0x16e,0x16f,0x170,0x171,0x172,0x178,0x17c,0x17f,0x180,0x181,0x182,
    0x183,0x184,0x185,0x186,0x18c,0x191,0x192,0x1ac,0x1ad,0x1ae,0x1af,0x1b0,0x1b4,
    0x1b5,0x1b6,0x1b7,0x1b8,0x1c3,0x1c4,0x1c7,0x1c9,0x1cb,0x1cd,0x1cf,0x1d1,0x1d3,
    0x1d5,0x1d7,0x1d9,0x1db,0x1dc,0x1de,0x1df,0x1e0,0x1e1,0x1e2,0x1e3,0x1e4,0x1e5,
    0x1e6,0x1e8,0x1f2,0x1f3,0x1f6,0x200,0x201,0x204,0x20e,0x20f,0x212,0x21c,0x21d,
    0x21f,0x229,0x22a,0x22b,0x22c,0x22d,0x241,0x253,0x254,0x255,0x256,0x257,0x258,
]


def crc8_j1850(data, poly=0x1D, init=0xFF, xorout=0xFF):
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc ^ xorout


class MSG(Structure):
    _fields_ = [("ProtocolID", c_ulong), ("RxStatus", c_ulong),
                ("TxFlags", c_ulong), ("Timestamp", c_ulong),
                ("DataSize", c_ulong), ("ExtraDataIndex", c_ulong),
                ("Data", c_ubyte * 4128)]


class RawCAN:
    def __init__(self, dll=DLL, baud=500000):
        self.d = ctypes.WinDLL(dll)
        for n, a in [
            ("PassThruOpen", [c_char_p, POINTER(c_ulong)]),
            ("PassThruClose", [c_ulong]),
            ("PassThruConnect", [c_ulong, c_ulong, c_ulong, c_ulong, POINTER(c_ulong)]),
            ("PassThruDisconnect", [c_ulong]),
            ("PassThruReadMsgs", [c_ulong, POINTER(MSG), POINTER(c_ulong), c_ulong]),
            ("PassThruWriteMsgs", [c_ulong, POINTER(MSG), POINTER(c_ulong), c_ulong]),
            ("PassThruStartMsgFilter", [c_ulong, c_ulong, POINTER(MSG),
                                        POINTER(MSG), POINTER(MSG), POINTER(c_ulong)]),
            ("PassThruGetLastError", [c_char_p]),
        ]:
            f = getattr(self.d, n)
            f.argtypes = a
            f.restype = c_ulong
        self.dev = c_ulong(0)
        self.ch = c_ulong(0)
        assert self.d.PassThruOpen(None, byref(self.dev)) == 0, "PassThruOpen failed"
        rc = self.d.PassThruConnect(self.dev, CAN, 0, baud, byref(self.ch))
        if rc != 0:
            raise RuntimeError("Connect(CAN) rc=%d %s" % (rc, self._err()))
        self._pass_all()

    def _err(self):
        b = create_string_buffer(160)
        self.d.PassThruGetLastError(b)
        return b.value.decode("latin-1", "replace")

    def _mk(self, cid, payload=b""):
        m = MSG()
        m.ProtocolID = CAN
        data = cid.to_bytes(4, "big") + payload
        m.DataSize = len(data)
        for i, x in enumerate(data):
            m.Data[i] = x
        return m

    def _pass_all(self):
        mask = self._mk(0)
        patt = self._mk(0)
        fid = c_ulong(0)
        self.d.PassThruStartMsgFilter(self.ch, PASS_FILTER, byref(mask),
                                      byref(patt), None, byref(fid))

    def read(self, timeout_ms=100):
        rx = MSG()
        cnt = c_ulong(1)
        rc = self.d.PassThruReadMsgs(self.ch, byref(rx), byref(cnt), timeout_ms)
        if rc != 0 or cnt.value == 0 or rx.DataSize < 4:
            return None
        if rx.RxStatus & TX_MSG_TYPE:
            return None
        cid = int.from_bytes(bytes(rx.Data[:4]), "big")
        return cid, bytes(rx.Data[4:rx.DataSize])

    def write(self, cid, payload):
        m = self._mk(cid, payload)
        n = c_ulong(1)
        self.d.PassThruWriteMsgs(self.ch, byref(m), byref(n), 50)

    def close(self):
        try:
            self.d.PassThruDisconnect(self.ch)
        finally:
            self.d.PassThruClose(self.dev)


def sniff(secs):
    c = RawCAN()
    seen = collections.Counter()
    sample = {}
    t0 = time.time()
    while time.time() - t0 < secs:
        r = c.read(100)
        if not r:
            continue
        cid, pl = r
        seen[cid] += 1
        sample.setdefault(cid, pl.hex())
    c.close()
    print("sniff %.1fs: %d frames, %d unique ids" % (secs, sum(seen.values()), len(seen)))
    for cid in sorted(seen):
        print("  0x%03x x%-5d %s" % (cid, seen[cid], sample[cid]))
    return set(seen) - {HEARTBEAT_ID}


def wake(secs, hz):
    c = RawCAN()
    ids = ACCEPTED_IDS
    period = 1.0 / hz
    ctr = 0
    new_ids = set()
    t0 = time.time()
    last_tx = 0.0
    print("wake: replaying %d accepted ids @ %d Hz for %ds, watching for operational tx..."
          % (len(ids), hz, secs))
    while time.time() - t0 < secs:
        now = time.time()
        if now - last_tx >= period:
            last_tx = now
            ctr = (ctr + 1) & 0xFF
            for cid in ids:
                body = bytes([0, 0, 0, 0, 0, 0x08, ctr])
                c.write(cid, body + bytes([crc8_j1850(body)]))
        r = c.read(2)
        if r:
            cid, pl = r
            if cid != HEARTBEAT_ID and cid not in new_ids:
                new_ids.add(cid)
                print("  [!] NEW tx id 0x%03x  %s  (t=%.1fs)" % (cid, pl.hex(), now - t0))
    c.close()
    if new_ids:
        print("RESULT: ECU emitted new ids %s — went (partly) operational."
              % sorted(hex(x) for x in new_ids))
    else:
        print("RESULT: still only 0x060 — full accepted-id replay did NOT wake it "
              "(consistent with per-message E2E content being required).")
    return new_ids


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sniff")
    s.add_argument("--secs", type=float, default=4.0)
    w = sub.add_parser("wake")
    w.add_argument("--secs", type=float, default=12.0)
    w.add_argument("--hz", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "sniff":
        sniff(a.secs)
    elif a.cmd == "wake":
        wake(a.secs, a.hz)


if __name__ == "__main__":
    main()
