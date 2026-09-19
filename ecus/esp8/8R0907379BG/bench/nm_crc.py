#!/usr/bin/env python3
"""ESP8 (8R0907379BG) CAN 0x060 heartbeat E2E CRC — reversed + generator.

The ECU's only pre-operational broadcast is CAN 0x060 (TX mailbox 0xfff7e5f0):
    byte0..4 = 00 00 00 00 00
    byte5    = 08            (constant)
    byte6    = CTR           (rolling counter 0..0xFF)
    byte7    = CRC           (E2E checksum over byte0..6)

Reversed from 8 on-bench samples (session 2): the checksum is a plain
**CRC-8 / SAE-J1850** over the first 7 bytes:
    poly=0x1D  init=0xFF  xorout=0xFF  refin=False  refout=False
(no per-message data-id; equivalent solution init=0x6C/xorout=0x00 also fits
the samples, but init=0xFF/xorout=0xFF is the AUTOSAR-standard Crc_CalculateCRC8
form and is the canonical identification).

Observed samples reproduced exactly:
    CTR 0->7  =>  CRC 50 4d 6a 77 24 39 1e 03

This is the E2E profile the ECU applies to its own status TX; partner RX frames
on the chassis/sensor CAN likely use the same CRC-8 (a per-message data-id may
be prepended for those — verify against a real captured partner frame before
trusting it for injection).

Usage:
    python nm_crc.py --selftest
    python nm_crc.py --frame 5          # print full 8-byte 0x060 frame for CTR=5
    python nm_crc.py --crc 00 00 00 00 00 08 05
"""
import argparse

POLY, INIT, XOROUT = 0x1D, 0xFF, 0xFF

# on-bench CTR -> CRC samples (byte0..4=0, byte5=0x08, byte6=CTR)
SAMPLES = {0: 0x50, 1: 0x4d, 2: 0x6a, 3: 0x77,
           4: 0x24, 5: 0x39, 6: 0x1e, 7: 0x03}


def crc8_j1850(data: bytes, poly=POLY, init=INIT, xorout=XOROUT) -> int:
    """CRC-8/SAE-J1850 (AUTOSAR Crc_CalculateCRC8), MSB-first, no reflection."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc ^ xorout


def frame_060(ctr: int) -> bytes:
    body = bytes([0, 0, 0, 0, 0, 0x08, ctr & 0xFF])
    return body + bytes([crc8_j1850(body)])


def _selftest() -> bool:
    ok = True
    for ctr, exp in SAMPLES.items():
        got = crc8_j1850(bytes([0, 0, 0, 0, 0, 0x08, ctr]))
        flag = "ok" if got == exp else "MISMATCH"
        if got != exp:
            ok = False
        print(f"  CTR {ctr}: crc={got:02x} expected={exp:02x}  {flag}")
    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--frame", type=lambda s: int(s, 0),
                    help="print the full 8-byte 0x060 frame for this counter")
    ap.add_argument("--crc", nargs="+",
                    help="hex bytes to CRC (e.g. 00 00 00 00 00 08 05)")
    a = ap.parse_args()
    if a.selftest or (not a.frame and a.frame != 0 and not a.crc):
        _selftest()
    if a.frame is not None:
        f = frame_060(a.frame)
        print(f.hex(" "))
    if a.crc:
        data = bytes(int(x, 16) for x in a.crc)
        print(f"{crc8_j1850(data):02x}")


if __name__ == "__main__":
    main()
