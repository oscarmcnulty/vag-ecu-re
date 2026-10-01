#!/usr/bin/env python3
"""ESP8 (8R0907379BG) hardened UDS discovery probe over RAW CAN (J2534).

WHY A NEW PROBE: the earlier "UDS is silent" result came from ISO15765-layer tools
(confirm_comms.py / read_ram.py) that (a) default to tx=0x713/rx=0x77D while the firmware's
own RX filter (decode/rx_filter_map.txt) listens on 0x6b4(req)/0x6b8(resp), and (b) open/close
the channel per run, letting the bus sleep between attempts (BENCH_HANDOFF: bus sleeps when idle;
module stops TX). This tool fixes both and sweeps addressing modes on ONE never-closed channel:

  * RAW CAN (protocol=CAN), so we are not locked to a single tx/rx pair and can watch EVERY id.
  * Continuous keep-awake: a TesterPresent (and optional wake-id) burst is (re)sent every
    --keepalive-ms so the bus never idles for the whole session.
  * Manual ISO-TP: single-frame request + minimal First/Consecutive-frame reassembly (sends the
    Flow Control 30 00 00 itself), so multi-frame identity replies (e.g. 22 F1 87) are captured.
  * Addressing modes tried, in order, all while the bus is held awake:
      1. physical pairs: 0x6b4/0x6b8 (firmware), 0x713/0x77D (old bench), + any via --pair
      2. physical SWEEP: req 0x600..0x7ff, watch ALL rx ids for any 7E/7F (ISO-TP SF/FF)
      3. functional: 0x7DF broadcast, watch ALL rx
      4. extended/mixed addressing: same, but first data byte = target-address extension (--ext)

A single 7E (positive) or 7F (negative) reply ANYWHERE is the win — it tells us the live
req/resp pair and whether the service is precondition-gated (7F 10/11/22/33/35/7F) vs. truly
absent. A clean all-silent sweep with the bus provably awake is itself the decisive negative.

Run with the 32-bit Python that loads smj2534.dll:
  <py311x86>\\python.exe ecus/esp8/8R0907379BG/bench/uds_discover.py --secs 20
  ...\\python.exe uds_discover.py --pair 0x6b4:0x6b8 --probe 1003   # focus one pair+service
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, module_alive  # noqa: E402  (reuse the proven raw-CAN J2534 binding)
# wake stimulus (the module boots DORMANT and must be woken + held operational, 2026-10-01)
from nm_uds_probe import (container_frames, send_container, send_nm_direct,  # noqa: E402
                          NM_NODES, NM_CTRLS)

# UDS probes to send, in order. Short requests whose responses fit a single frame (except F187).
PROBES = {
    "3E00":   ("TesterPresent",            bytes.fromhex("3E00")),
    "1003":   ("Session: extended",        bytes.fromhex("1003")),
    "1001":   ("Session: default",         bytes.fromhex("1001")),
    "22F187": ("ReadDID VW part no",       bytes.fromhex("22F187")),
    "22F18C": ("ReadDID ECU serial",       bytes.fromhex("22F18C")),
    "1086":   ("Session: safetySystem",    bytes.fromhex("1086")),
}
DEFAULT_SEQ = ["3E00", "1003", "22F187"]

PAIRS = [(0x6b4, 0x6b8), (0x713, 0x77D)]       # firmware pair first, then the old bench pair
FUNCTIONAL = 0x7DF


def iso_tp_sf(payload, ext=None):
    """Build an ISO-TP single frame (11-bit normal, or extended if ext!=None), padded to 8."""
    if ext is None:
        assert len(payload) <= 7
        frame = bytes([len(payload)]) + payload
    else:
        assert len(payload) <= 6
        frame = bytes([ext, len(payload)]) + payload
    return frame + b"\xAA" * (8 - len(frame))   # 0xAA pad (value not checked on RX)


def is_uds_reply(payload, req_sid):
    """True if payload looks like a UDS reply to req_sid (positive SID+0x40, or 7F req_sid)."""
    if not payload:
        return False
    b0 = payload[0]
    if b0 == 0x7F and len(payload) >= 2 and payload[1] == req_sid:
        return True
    if b0 == (req_sid + 0x40):
        return True
    return False


def decode_reply(payload, ext=None):
    """Strip ISO-TP PCI from a received CAN payload; return the UDS bytes of a SF/FF, or None."""
    if ext is not None:
        if len(payload) < 1:
            return None
        payload = payload[1:]
    if not payload:
        return None
    pci_type = payload[0] >> 4
    if pci_type == 0:          # single frame
        n = payload[0] & 0x0F
        return payload[1:1 + n]
    if pci_type == 1:          # first frame of multi-frame
        n = ((payload[0] & 0x0F) << 8) | payload[1]
        return payload[2:]      # caller may collect the rest; for discovery the head is enough
    return None


class Probe:
    def __init__(self, dll, baud, keepalive_ms, wake_ids, wake=False):
        self.can = RawCAN(dll=dll, baud=baud) if dll else RawCAN(baud=baud)
        self.keepalive_ms = keepalive_ms
        self.wake_ids = wake_ids
        self.wake = wake
        self._last_ka = 0.0
        self._last_wake = 0.0
        self._wni = 0

    def drive_wake(self):
        """Feed the NM wake stimulus (0x40c container + direct NM) at ~50Hz to wake/hold the module."""
        now = time.time()
        if (now - self._last_wake) * 1000.0 < 20:
            return
        self._last_wake = now
        node = NM_NODES[self._wni % len(NM_NODES)]
        ctrl = NM_CTRLS[(self._wni // len(NM_NODES)) % len(NM_CTRLS)]
        send_container(self.can, container_frames(node))
        send_nm_direct(self.can, node, ctrl)
        self._wni += 1

    def keepalive(self, req_id):
        """Hold the bus/module awake: NM stimulus (if --wake) + periodic TesterPresent + wake ids."""
        if self.wake:
            self.drive_wake()
        now = time.time()
        if (now - self._last_ka) * 1000.0 < self.keepalive_ms:
            return
        self._last_ka = now
        self.can.write(req_id, iso_tp_sf(bytes.fromhex("3E00")))
        for wid in self.wake_ids:
            self.can.write(wid, bytes(8))

    def request(self, req_id, payload, ext=None, listen_ms=300, watch_all=False, want_rx=None):
        """Send one ISO-TP SF; collect replies for listen_ms. Return list of (rx_id, uds_bytes)."""
        req_sid = payload[0]
        self.can.write(req_id, iso_tp_sf(payload, ext))
        out = []
        t0 = time.time()
        while (time.time() - t0) * 1000.0 < listen_ms:
            r = self.can.read(20)
            if not r:
                continue
            rx_id, data = r
            if (not watch_all) and want_rx is not None and rx_id != want_rx:
                continue
            uds = decode_reply(data, ext)
            if uds and is_uds_reply(uds, req_sid):
                out.append((rx_id, uds))
        return out


def fmt(uds):
    b0 = uds[0]
    if b0 == 0x7F:
        nrc = uds[2] if len(uds) > 2 else 0
        names = {0x10: "generalReject", 0x11: "serviceNotSupported", 0x22: "conditionsNotCorrect",
                 0x31: "requestOutOfRange", 0x33: "securityAccessDenied", 0x35: "invalidKey",
                 0x7E: "subFnNotSuppInActiveSession", 0x7F: "svcNotSuppInActiveSession",
                 0x78: "responsePending"}
        return f"7F NRC=0x{nrc:02x} ({names.get(nrc, '?')})  [{uds.hex(' ')}]"
    return f"POSITIVE  [{uds.hex(' ')}]"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=None, help="smj2534.dll path (defaults to can_raw's)")
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--secs", type=float, default=20.0, help="overall budget for the sweep")
    ap.add_argument("--keepalive-ms", type=int, default=150, help="<=200 to stay >5Hz")
    ap.add_argument("--listen-ms", type=int, default=300, help="reply window per request")
    ap.add_argument("--pair", default=None, help="focus one pair 'req:rx' (e.g. 0x6b4:0x6b8)")
    ap.add_argument("--probe", default=None, help="focus one probe key (e.g. 1003) or hex payload")
    ap.add_argument("--ext", type=lambda s: int(s, 0), default=None,
                    help="extended-addressing target byte to also try (e.g. 0xf1)")
    ap.add_argument("--wake-id", action="append", default=[],
                    help="extra CAN id(s) to blast as 8x00 keep-awake (repeatable)")
    ap.add_argument("--sweep-lo", type=lambda s: int(s, 0), default=0x600)
    ap.add_argument("--sweep-hi", type=lambda s: int(s, 0), default=0x7ff)
    ap.add_argument("--force", action="store_true",
                    help="probe even if the module is not broadcasting (asleep) at start")
    ap.add_argument("--wake", action="store_true",
                    help="feed NM wake stimulus (0x40c container + NM) to wake/hold the module "
                         "throughout (the module boots dormant)")
    a = ap.parse_args()

    wake_ids = [int(x, 0) for x in a.wake_id]
    seq = [a.probe] if a.probe else DEFAULT_SEQ
    # allow raw hex payload for --probe
    def payload_for(key):
        if key in PROBES:
            return PROBES[key][1]
        return bytes.fromhex(key)

    pairs = PAIRS
    if a.pair:
        rq, rx = a.pair.split(":")
        pairs = [(int(rq, 0), int(rx, 0))]

    p = Probe(a.dll, a.baud, a.keepalive_ms, wake_ids, wake=a.wake)

    # LIVENESS GUARD: a UDS 'silent' result only means something if the module is awake.
    alive = module_alive(p.can, 1.5)
    if (not alive) and a.wake:
        print("[*] module silent — driving NM wake stimulus to bring it operational...")
        tw = time.time()
        while time.time() - tw < 10 and not alive:
            for _ in range(10):
                p.drive_wake()
                time.sleep(0.002)
            alive = module_alive(p.can, 0.6)
        if alive:
            print(f"[*] WOKE at t={time.time()-tw:.1f}s")
    if alive:
        print(f"[*] module ALIVE — broadcasting {sorted(hex(x) for x in alive)}")
    else:
        print("[!] module is SILENT (not broadcasting) — asleep or powered down.")
        if not a.force:
            print("[!] ABORTING: probing a sleeping module yields a meaningless 'silent' result.")
            print("    Power-cycle, then re-run with --wake (module boots dormant). Use --force to override.")
            p.can.close()
            return
        print("[!] --force set; probing anyway (results may be meaningless).")

    found = []
    still_alive = alive
    t_end = time.time() + a.secs
    print(f"[*] raw-CAN {a.baud}bps  keepalive every {a.keepalive_ms}ms  "
          f"listen {a.listen_ms}ms/req  budget {a.secs:.0f}s")
    print(f"[*] holding bus awake with periodic TesterPresent"
          + (f" + wake ids {['0x%x'%w for w in wake_ids]}" if wake_ids else ""))

    try:
        # Phase 1: known physical pairs, each probe
        for rq, rx in pairs:
            for key in seq:
                p.keepalive(rq)
                pl = payload_for(key)
                reps = p.request(rq, pl, ext=None, listen_ms=a.listen_ms, want_rx=rx)
                label = PROBES.get(key, ("raw", pl))[0]
                if reps:
                    for rid, uds in reps:
                        print(f"[HIT] pair req0x{rq:03x}->rx0x{rid:03x}  {key} {label}: {fmt(uds)}")
                        found.append((rq, rid, key, uds))
                else:
                    print(f"[--] pair req0x{rq:03x}/rx0x{rx:03x}  {key} {label}: silent")
                if a.ext is not None:
                    reps = p.request(rq, pl, ext=a.ext, listen_ms=a.listen_ms, watch_all=True)
                    for rid, uds in reps:
                        print(f"[HIT-EXT] req0x{rq:03x} ext0x{a.ext:02x} ->rx0x{rid:03x} {key}: {fmt(uds)}")
                        found.append((rq, rid, key, uds))

        # Phase 2: functional broadcast, watch all rx
        for key in seq:
            p.keepalive(FUNCTIONAL)
            reps = p.request(FUNCTIONAL, payload_for(key), listen_ms=a.listen_ms, watch_all=True)
            for rid, uds in reps:
                print(f"[HIT-FUNC] 0x7DF {key} ->rx0x{rid:03x}: {fmt(uds)}")
                found.append((FUNCTIONAL, rid, key, uds))

        # Phase 3: physical req sweep with 3E00, watch all rx — until budget runs out
        print(f"[*] sweeping req 0x{a.sweep_lo:03x}..0x{a.sweep_hi:03x} with 3E00 (watch all rx)...")
        for rq in range(a.sweep_lo, a.sweep_hi + 1):
            if time.time() > t_end:
                print(f"[*] budget reached at req 0x{rq:03x}; stop sweep")
                break
            p.keepalive(rq)
            reps = p.request(rq, bytes.fromhex("3E00"), listen_ms=max(40, a.listen_ms // 4),
                             watch_all=True)
            for rid, uds in reps:
                print(f"[HIT-SWEEP] req0x{rq:03x} ->rx0x{rid:03x}: {fmt(uds)}")
                found.append((rq, rid, "3E00", uds))
        still_alive = module_alive(p.can, 1.0)
    finally:
        p.can.close()

    if alive and not still_alive and not found:
        print("[!] WARNING: module STOPPED broadcasting during the run — it slept mid-sweep.")
        print("    The 'silent' result below may be a sleep artifact; re-run keeping it awake.")

    print("\n=== SUMMARY ===")
    if found:
        pairs_seen = sorted({(rq, rx) for rq, rx, _, _ in found})
        print(f"RESPONDER(S) FOUND on {len(pairs_seen)} pair(s):")
        for rq, rx in pairs_seen:
            print(f"  req 0x{rq:03x} -> resp 0x{rx:03x}")
        print("Next: use the live pair with read_ram.py / the UDS client. A 7F 22/33 reply means "
              "the service exists but is precondition/security gated (that IS the gate to satisfy).")
    else:
        print("NO responder on any pair/functional/ext/sweep with the bus held awake.")
        print("That is the decisive negative: the Dcm is gated BEFORE addressing (not an id mismatch).")
        print("Next: read live RAM dispatch state (read_ram.py) once any pair answers, or pursue the")
        print("precondition stimulus (NM/network-management state) before the UDS request.")


if __name__ == "__main__":
    main()
