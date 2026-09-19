#!/usr/bin/env python3
"""ESP8 (8R0907379BG) bench comms confirmation over J2534.

Handoff step 4: prove the SM2 Pro talks to the ABS on the bench.
Physical req 0x713 / resp 0x77D, ISO15765 500 kbps (per BENCH_HANDOFF.md).

Default run is read-only / non-state-changing:
  1) TesterPresent (0x3E 00)              -> liveness
  2) ReadDataByIdentifier part no (F187)  -> confirms it is this ECU
  3) a few more identity DIDs (F190 VIN, F189 SW ver, F191 HW no)

Options:
  --scan               sweep tester IDs 0x700..0x7FF with 0x3E00 (if silent)
  --baud 100000        fallback bitrate (handoff: retry 100k if 500k silent)
  --programming-session  ALSO send 0x10 0x02 (the handoff's documented probe).
                       This changes ECU session state; opt-in, run when ready.

Run with the 32-bit Python that can load smj2534.dll, e.g.:
  <py311x86>\\python.exe ecus/esp8/8R0907379BG/bench/confirm_comms.py \\
      --dll "C:/Program Files (x86)/Scanmatik/smj2534.dll"
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "core", "uds"))
from j2534_transport import J2534IsoTpTransport, J2534Error  # noqa: E402
from uds_client import UDS, NegativeResponse                 # noqa: E402

DEFAULT_DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"

IDENT_DIDS = [
    (0xF187, "VW spare part number"),
    (0xF189, "VW ASW version"),
    (0xF191, "VW ECU HW part number"),
    (0xF190, "VIN"),
    (0xF18C, "ECU serial number"),
]


def _txt(b):
    try:
        s = b.decode("latin-1").strip("\x00 ")
        return s if s.isprintable() else b.hex(" ")
    except Exception:
        return b.hex(" ")


def probe(dll, tx, rx, baud, timeout, do_programming):
    print(f"[*] open {dll}")
    print(f"[*] ISO15765 {baud} bps  tx={tx:#05x} rx={rx:#05x}  "
          f"timeout={timeout}ms")
    with J2534IsoTpTransport(dll, tx, rx, baud, timeout_ms=timeout) as t:
        uds = UDS(t)

        # 1) liveness — TesterPresent, no state change
        try:
            resp = t.request(b"\x3e\x00")
            print(f"[OK] TesterPresent -> {resp.hex(' ')}  "
                  f"(ECU IS ALIVE at {rx:#05x})")
        except J2534Error as e:
            print(f"[--] TesterPresent: no answer ({e})")
            return False

        # 2/3) identity DIDs — read-only
        for did, label in IDENT_DIDS:
            try:
                val = uds.read_did(did)
                print(f"[OK] DID {did:#06x} {label:<24} = "
                      f"{_txt(val)}   [{val.hex(' ')}]")
            except NegativeResponse as e:
                print(f"[  ] DID {did:#06x} {label:<24} : {e}")
            except J2534Error as e:
                print(f"[--] DID {did:#06x} {label:<24} : {e}")

        # optional: the handoff's documented programmingSession probe
        if do_programming:
            print("[*] --programming-session: sending 0x10 0x02 "
                  "(changes session state)")
            try:
                resp = t.request(b"\x10\x02")
                print(f"[OK] DiagSessionControl(programming) -> "
                      f"{resp.hex(' ')}")
            except NegativeResponse as e:
                print(f"[  ] programmingSession rejected: {e}")
            except J2534Error as e:
                print(f"[--] programmingSession: {e}")
    return True


def scan(dll, baud, timeout):
    print(f"[*] scanning tester IDs 0x700..0x7FF @ {baud} bps "
          "(resp = req+0x6A, VAG convention)")
    hits = []
    for tx in range(0x700, 0x800):
        rx = tx + 0x6A  # 0x713 -> 0x77D
        try:
            with J2534IsoTpTransport(dll, tx, rx, baud,
                                     timeout_ms=timeout) as t:
                resp = t.request(b"\x3e\x00")
                print(f"[HIT] tx={tx:#05x} rx={rx:#05x} -> {resp.hex(' ')}")
                hits.append((tx, rx))
        except Exception:
            pass
    if not hits:
        print("[--] no response across the range")
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=DEFAULT_DLL)
    ap.add_argument("--tx", default="0x713")
    ap.add_argument("--rx", default="0x77D")
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--timeout", type=int, default=2000)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--programming-session", action="store_true")
    a = ap.parse_args()

    if a.scan:
        scan(a.dll, a.baud, a.timeout)
        return
    ok = probe(a.dll, int(a.tx, 0), int(a.rx, 0), a.baud, a.timeout,
               a.programming_session)
    if not ok:
        print("\n[hint] silent at this bitrate. Check power sequence "
              "(term30 B+ first, then term15), then try:")
        print(f"       --baud 100000        (handoff fallback)")
        print(f"       --scan               (sweep 0x700..0x7FF)")
        sys.exit(1)


if __name__ == "__main__":
    main()
