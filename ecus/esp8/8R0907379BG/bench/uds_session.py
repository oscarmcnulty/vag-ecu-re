#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — enter a UDS diagnostic session the VW_Flash (Simos18 flasher) way.

Implements a proper ISO-TP (ISO 15765-2) client over RAW CAN — single frame, first frame + flow
control + consecutive frames both directions — interleaved with the NM wake stimulus on ONE channel
(the module boots dormant and re-sleeps within seconds; we must hold it awake the whole time).

Then runs the VW_Flash session-entry sequence (lib/flash_uds.py):
    3E 00                 TesterPresent
    10 03                 DiagnosticSessionControl: extendedDiagnosticSession
    3E 00
    31 01 02 03           RoutineControl start: programming-precondition check (routine 0x0203)
    10 02                 DiagnosticSessionControl: programmingSession
    3E 00
    27 11                 SecurityAccess requestSeed (level 0x11 / SA2) -> print seed

Default diag pair is the firmware's 0x6b4/0x6b8; --pair to try others (e.g. 0x713:0x77d, 0x7e0:0x7e8).
Any response at all (positive or 7F) means we finally reached the Dcm. 7F 31/33/22 on later steps is
expected without security; the point here is to get PAST silence on 10 03.

Run with 32-bit Python:
  <py311x86>\\python.exe bench/uds_session.py
  ...\\python.exe bench/uds_session.py --pair 0x713:0x77d --no-wake
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, module_alive  # noqa: E402
from nm_uds_probe import container_frames, send_container, send_nm_direct, NM_NODES  # noqa: E402

NRC = {0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFnNotSupported",
       0x13: "wrongLength", 0x22: "conditionsNotCorrect", 0x24: "requestSequenceError",
       0x31: "requestOutOfRange", 0x33: "securityAccessDenied", 0x35: "invalidKey",
       0x7E: "subFnNotSuppInActiveSession", 0x7F: "svcNotSuppInActiveSession",
       0x78: "responsePending"}


class IsoTp:
    """Minimal ISO-TP over raw CAN with an optional background wake-pump."""
    def __init__(self, can, txid, rxid, wake=True, stmin=0.0):
        self.can = can
        self.txid = txid
        self.rxid = rxid
        self.wake = wake
        self.stmin = stmin
        self._wni = 0
        self._last_wake = 0.0

    def pump_wake(self):
        if not self.wake:
            return
        now = time.time()
        if (now - self._last_wake) * 1000 < 20:
            return
        self._last_wake = now
        node = NM_NODES[self._wni % len(NM_NODES)]
        send_container(self.can, container_frames(node))
        send_nm_direct(self.can, node, 0x00)
        self._wni += 1

    def _read(self, timeout_ms):
        """Read one CAN frame addressed from rxid within timeout; pump wake meanwhile."""
        t0 = time.time()
        while (time.time() - t0) * 1000 < timeout_ms:
            self.pump_wake()
            r = self.can.read(5)
            if r and r[0] == self.rxid:
                return r[1]
        return None

    def request(self, payload, timeout_ms=1500):
        """Send a UDS payload via ISO-TP, return the reassembled response (bytes) or None."""
        # --- send request ---
        if len(payload) <= 7:
            self.can.write(self.txid, bytes([len(payload)]) + payload + b"\xAA" * (7 - len(payload)))
        else:
            # First Frame + wait for Flow Control, then Consecutive Frames
            n = len(payload)
            self.can.write(self.txid, bytes([0x10 | (n >> 8), n & 0xFF]) + payload[:6])
            fc = self._read(1000)
            if not fc or (fc[0] & 0xF0) != 0x30:
                return None  # no flow control
            idx, sn = 6, 1
            while idx < n:
                self.can.write(self.txid, bytes([0x20 | (sn & 0xF)]) + payload[idx:idx + 7].ljust(7, b"\xAA"))
                idx += 7
                sn = (sn + 1) & 0xF
                if self.stmin:
                    time.sleep(self.stmin)
        # --- receive response (handle responsePending 0x78 by waiting longer) ---
        deadline = time.time() + timeout_ms / 1000.0 + 5.0
        while time.time() < deadline:
            first = self._read(timeout_ms)
            if first is None:
                return None
            pci = first[0] >> 4
            if pci == 0:                      # single frame
                data = first[1:1 + (first[0] & 0xF)]
            elif pci == 1:                    # first frame -> send FC, collect CFs
                total = ((first[0] & 0xF) << 8) | first[1]
                data = bytearray(first[2:8])
                self.can.write(self.txid, bytes([0x30, 0x00, 0x00]) + b"\xAA" * 5)
                while len(data) < total:
                    cf = self._read(1000)
                    if cf is None:
                        break
                    if (cf[0] & 0xF0) == 0x20:
                        data += cf[1:]
                data = bytes(data[:total])
            else:
                continue
            # keep waiting through responsePending
            if len(data) >= 3 and data[0] == 0x7F and data[2] == 0x78:
                continue
            return data
        return None


def fmt(resp):
    if resp is None:
        return "SILENT (no response)"
    if resp[0] == 0x7F:
        nrc = resp[2] if len(resp) > 2 else 0
        return f"7F {NRC.get(nrc, hex(nrc))}  [{resp.hex(' ')}]"
    return f"POSITIVE  [{resp.hex(' ')}]"


def run_sequence(tp, label):
    print(f"\n=== VW_Flash session entry on {label} (tx0x{tp.txid:03x}/rx0x{tp.rxid:03x}) ===")
    steps = [
        ("TesterPresent",            bytes.fromhex("3E00")),
        ("Extended session 10 03",   bytes.fromhex("1003")),
        ("TesterPresent",            bytes.fromhex("3E00")),
        ("Routine 0203 (31 01)",     bytes.fromhex("310102 03".replace(" ", ""))),
        ("Programming 10 02",        bytes.fromhex("1002")),
        ("TesterPresent",            bytes.fromhex("3E00")),
        ("SecurityAccess seed 27 11", bytes.fromhex("2711")),
    ]
    any_resp = False
    for name, pl in steps:
        resp = tp.request(pl)
        print(f"  {name:28s} -> {fmt(resp)}")
        if resp is not None:
            any_resp = True
        if name.startswith("Extended") and resp is None:
            print("  (10 03 silent — module not entering a session on this pair; skipping rest)")
            break
    return any_resp


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=None)
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--pair", action="append", default=None,
                    help="diag pair 'req:rx' (repeatable); default tries 0x6b4:0x6b8 then 0x713:0x77d")
    ap.add_argument("--no-wake", action="store_true", help="do not feed NM wake stimulus")
    a = ap.parse_args()

    pairs = [(0x6B4, 0x6B8), (0x713, 0x77D)]
    if a.pair:
        pairs = [tuple(int(x, 0) for x in p.split(":")) for p in a.pair]

    can = RawCAN(dll=a.dll, baud=a.baud) if a.dll else RawCAN(baud=a.baud)
    try:
        # wake + verify operational
        if not a.no_wake:
            print("[*] waking module (NM stimulus)...")
            tmp = IsoTp(can, 0, 0, wake=True)
            alive = set()
            t = time.time()
            while time.time() - t < 10 and not alive:
                for _ in range(10):
                    tmp.pump_wake()
                    time.sleep(0.002)
                alive = module_alive(can, 0.6)
            print(f"[*] module {'AWAKE: ' + str(sorted(hex(x) for x in alive)) if alive else 'STILL SILENT'}")
            if not alive:
                print("[!] could not wake module — power-cycle and retry.")
        any_any = False
        for req, rx in pairs:
            tp = IsoTp(can, req, rx, wake=not a.no_wake)
            if run_sequence(tp, f"pair 0x{req:03x}/0x{rx:03x}"):
                any_any = True
        print("\n=== RESULT ===")
        print("Reached the Dcm (got a response)." if any_any else
              "Still fully silent through a proper ISO-TP session-entry sequence + wake.")
    finally:
        can.close()


if __name__ == "__main__":
    main()
