#!/usr/bin/env python3
"""ESP8 (8R0907379BG) XCP/CCP probe over J2534 raw CAN.

Sends XCP CONNECT and CCP CONNECT commands to the ECU on the bench,
checking for protocol responses. Uses the stimulus thread to keep
the module operational (same as prog_session / emu_unlock).

  Phase 1 — CCP on standard CAN:
    CRO to 0x1E1 (the CAN inventory's CCP_MOS_CRO_01) with station
    addresses 0x0000..0x00FF, listening for DTO on 0x1E8 or any new ID.

  Phase 2 — XCP on standard CAN:
    CONNECT (0xFF 0x00) to a selection of the ECU's accepted RX IDs,
    listening for any response frame.

  Phase 3 — XCP on extended CAN (29-bit):
    CONNECT to the hypothesised VAG XCP address 0x1BFC0300 (formula:
    0x1BFC0000 + TP2.0_logical_addr<<8, ABS=0x03), listening for
    response on 0x1BFC0304.  Also tries nearby offsets.

Run with the 32-bit Python:
  tools\\py311x86\\python.exe bench\\xcp_ccp_probe.py [--phase 1|2|3|all]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, MSG, CAN, PASS_FILTER, TX_MSG_TYPE, crc8_j1850
from ctypes import byref, c_ulong, c_ubyte
import threading

CAN_29BIT_ID = 0x00000100


class ExtCAN(RawCAN):
    """RawCAN with thread-safe locking and extended-frame support.
    connect_ext: if True, PassThruConnect with CAN_29BIT_ID flag
    (needed if the DLL doesn't honour per-message TxFlags)."""
    def __init__(self, *a, connect_ext=False, **k):
        self._connect_ext = connect_ext
        super().__init__(*a, **k)
        self._lk = threading.Lock()
        if connect_ext:
            # re-connect with the extended flag
            self.d.PassThruDisconnect(self.ch)
            rc = self.d.PassThruConnect(self.dev, CAN, CAN_29BIT_ID,
                                        500000, byref(self.ch))
            if rc != 0:
                raise RuntimeError("Connect(CAN,29BIT) rc=%d %s" %
                                   (rc, self._err()))
            self._pass_all()

    def read(self, timeout_ms=100):
        with self._lk:
            rx = MSG()
            cnt = c_ulong(1)
            rc = self.d.PassThruReadMsgs(self.ch, byref(rx), byref(cnt), timeout_ms)
            if rc != 0 or cnt.value == 0 or rx.DataSize < 4:
                return None
            if rx.RxStatus & TX_MSG_TYPE:
                return None
            cid = int.from_bytes(bytes(rx.Data[:4]), "big")
            extended = bool(rx.RxStatus & CAN_29BIT_ID)
            payload = bytes(rx.Data[4:rx.DataSize])
            return cid, payload, extended

    def write(self, cid, payload, extended=False):
        with self._lk:
            m = MSG()
            m.ProtocolID = CAN
            if extended:
                m.TxFlags = CAN_29BIT_ID
            data = cid.to_bytes(4, "big") + payload
            m.DataSize = len(data)
            for i, x in enumerate(data):
                m.Data[i] = x
            n = c_ulong(1)
            rc = self.d.PassThruWriteMsgs(self.ch, byref(m), byref(n), 50)
            return rc == 0


class Stim(threading.Thread):
    """Background stimulus — sends a single accepted CAN ID to keep the module awake."""
    def __init__(self, can, hz=50, cid=0x200):
        super().__init__(daemon=True)
        self.c = can
        self._period = 1.0 / hz
        self.cid = cid
        self.stop = False
        self.paused = False
        self.ctr = 0

    def run(self):
        while not self.stop:
            if self.paused:
                time.sleep(0.005)
                continue
            t = time.time()
            self.ctr = (self.ctr + 1) & 0xFF
            body = bytes([0, 0, 0, 0, 0, 0x08, self.ctr])
            frame = body + bytes([crc8_j1850(body)])
            self.c.write(self.cid, frame)
            end = t + self._period
            while time.time() < end and not self.stop:
                time.sleep(0.003)

    def pause(self):
        self.paused = True
        time.sleep(0.02)

    def resume(self):
        self.paused = False


def collect_baseline(can, secs=3.0):
    """Collect all CAN IDs the module transmits during normal operation."""
    baseline = set()
    t0 = time.time()
    while time.time() - t0 < secs:
        r = can.read(50)
        if r:
            baseline.add(r[0])
    return baseline


def listen(can, timeout_ms=200, ignore=None):
    """Listen for CAN frames not in the ignore set."""
    if ignore is None:
        ignore = set()
    hits = []
    t0 = time.time()
    while time.time() - t0 < timeout_ms / 1000:
        r = can.read(15)
        if r and r[0] not in ignore:
            hits.append(r)
    return hits


def drain(can, ms=100):
    t0 = time.time()
    while time.time() - t0 < ms / 1000:
        can.read(10)


def phase1_ccp(can, baseline):
    """CCP CONNECT on 0x1E1, sweep station addresses."""
    print("\n=== Phase 1: CCP CONNECT on 0x1E1 ===")
    print("Sweeping station addresses 0x0000..0x00FF")

    hits = []
    for station in range(0x100):
        payload = bytes([0x01, 0x01, station & 0xFF, (station >> 8) & 0xFF,
                         0x00, 0x00, 0x00, 0x00])
        drain(can, 30)
        can.write(0x1E1, payload)
        resps = listen(can, timeout_ms=80, ignore=baseline)
        if resps:
            for cid, data, ext in resps:
                print(f"  [HIT] station=0x{station:04X} -> "
                      f"CAN 0x{cid:03X} {data.hex(' ')} ext={ext}")
                hits.append((station, cid, data))
        if station % 64 == 63:
            print(f"    ...0x{station-63:02X}..0x{station:02X} done, "
                  f"{len(hits)} hits")

    if not hits:
        print("[--] No CCP response.")
    return hits


def phase2_xcp_std(can, baseline):
    """XCP CONNECT on standard 11-bit CAN IDs."""
    print("\n=== Phase 2: XCP CONNECT on standard CAN IDs ===")

    candidates = list(range(0x200, 0x259))
    candidates += [0x1E1, 0x1E8]
    candidates += list(range(0x550, 0x560))
    candidates += list(range(0x5F0, 0x600))
    candidates += list(range(0x600, 0x610))
    candidates += list(range(0x6F0, 0x700))
    candidates += list(range(0x700, 0x7F0))
    candidates += [0x7FC, 0x7FD, 0x7FE, 0x7FF]
    candidates = sorted(set(candidates))

    xcp_connect = bytes([0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    hits = []
    for i, cid in enumerate(candidates):
        drain(can, 20)
        can.write(cid, xcp_connect)
        resps = listen(can, timeout_ms=60, ignore=baseline)
        if resps:
            for rcid, data, ext in resps:
                print(f"  [HIT] TX 0x{cid:03X} -> "
                      f"CAN 0x{rcid:03X} {data.hex(' ')} ext={ext}")
                hits.append((cid, rcid, data))
        if (i + 1) % 80 == 0:
            print(f"    ...{i+1}/{len(candidates)} done, {len(hits)} hits")

    print(f"[*] Probed {len(candidates)} standard IDs, {len(hits)} hits.")
    return hits


def phase3_xcp_ext(can, baseline):
    """XCP CONNECT on extended 29-bit CAN IDs."""
    print("\n=== Phase 3: XCP CONNECT on extended 29-bit CAN IDs ===")

    candidates = [
        (0x1BFC0300, "ABS logical=0x03 (primary hypothesis)"),
        (0x1BFC0304, "ABS RX (try as TX too)"),
        (0x1BFC0600, "addr=0x06"),
        (0x1BFC0C00, "addr=0x0C"),
        (0x1BFC1800, "addr=0x18"),
        (0x1BFC1C00, "EPS=0x1C (shared IDs)"),
        (0x1BFC0000, "base+0"),
        (0x1BFCFF00, "broadcast 0xFF"),
        (0x18DA0300, "ISO15765 phys 03->00"),
        (0x18DA00F1, "ISO15765 phys F1->00"),
        (0x18DAF103, "ISO15765 phys 03->F1"),
        (0x18DB33F1, "ISO15765 functional"),
    ]

    xcp_connect = bytes([0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    hits = []
    for tx, desc in candidates:
        drain(can, 40)
        ok = can.write(tx, xcp_connect, extended=True)
        if not ok:
            print(f"  [ERR] 0x{tx:08X} ({desc}) — write failed")
            continue

        resps = listen(can, timeout_ms=150, ignore=baseline)
        if resps:
            for rcid, data, ext in resps:
                marker = "EXT" if ext else "STD"
                print(f"  [HIT] TX 0x{tx:08X} ({desc}) -> "
                      f"{marker}:0x{rcid:08X} {data.hex(' ')}")
                hits.append((tx, rcid, data, ext, desc))
        else:
            print(f"  [  ] 0x{tx:08X} ({desc}) — silent")

    if not hits:
        print("[--] No XCP response on extended IDs.")
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="all",
                    help="1=CCP, 2=XCP-std, 3=XCP-ext, all=all three")
    ap.add_argument("--stim-hz", type=int, default=50,
                    help="stimulus frequency (default 50)")
    ap.add_argument("--ext-connect", action="store_true",
                    help="reconnect CAN channel in 29-bit mode for phase 3")
    a = ap.parse_args()

    phases = [1, 2, 3] if a.phase == "all" else [int(a.phase)]

    print("[*] XCP/CCP probe for ESP8 8R0907379BG")

    # Standard-mode channel for stimulus + phases 1&2
    can = ExtCAN(connect_ext=False)

    stim = Stim(can, hz=a.stim_hz)
    stim.start()

    print("[*] Stimulus running (0x200 @ %d Hz), waiting for module..." % a.stim_hz)
    time.sleep(1.0)

    baseline = collect_baseline(can, secs=3.0)
    if not baseline:
        print("[!!] No CAN frames — module not responding. Check power.")
        stim.stop = True
        can.close()
        return

    print(f"[OK] Module alive — baseline IDs: "
          f"{sorted(hex(x) for x in baseline)}")

    all_hits = []

    if 1 in phases:
        all_hits += phase1_ccp(can, baseline)
    if 2 in phases:
        all_hits += phase2_xcp_std(can, baseline)

    if 3 in phases:
        # Phase 3 needs extended CAN. The SM2 Pro doesn't mix 11/29-bit on
        # one channel, so: stop stimulus, disconnect, reconnect in 29-bit mode,
        # and probe before the module goes dormant (~5s operational timeout).
        print("\n[*] Switching to 29-bit CAN mode for Phase 3...")
        stim.stop = True
        stim.join(timeout=1.0)
        can.close()
        time.sleep(0.2)

        can29 = ExtCAN(connect_ext=True)
        all_hits += phase3_xcp_ext(can29, baseline)
        can29.close()
    else:
        stim.stop = True
        stim.join(timeout=1.0)
        can.close()

    print("\n" + "=" * 60)
    if all_hits:
        print("RESULT: %d hit(s) found!" % len(all_hits))
        for h in all_hits:
            print("  ", h)
    else:
        print("RESULT: No XCP or CCP response detected.")
        print("  Confirms firmware analysis: ESP8 does not implement XCP/CCP.")
        print("  Access path remains: KWP2000 over TP2.0 (SA2 flash unlock).")


if __name__ == "__main__":
    main()
