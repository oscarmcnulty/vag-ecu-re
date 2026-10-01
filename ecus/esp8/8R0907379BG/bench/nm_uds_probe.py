#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — drive NM/network stimulus AND probe UDS on ONE raw-CAN channel.

CONTEXT (2026-10-01): the module is already OPERATIONAL on the bench (broadcasting ESP_01..08 with
valid E2E), yet UDS is silent on every addressing mode (uds_discover.py). So the pre-operational wake
tools (wake_container.py / nm_probe.py) target a gate that is ALREADY satisfied. This tool tests the
remaining hypothesis directly: does establishing/holding a NETWORK-MANAGEMENT state unlock the Dcm?

It continuously injects, at high rate on one never-closed channel:
  * the 0x40c wake container with the 0x600 sub-PDU byte1 bit5 set (tx_gate2), cycling NM node-ids
    {0x4a,0x5f,0x98,0x99,0x9a,0xd4} (from nm_msg_process 0x40950 / wake_container.py), and
  * direct NM frames on the module-B NM-range ids (0x44x = 0x400+node, and 0x441/0x395 seen in the
    rx filter) with control byte 0x00/0x42,
while every --probe-ms it sends a UDS request on the diag pair and watches ALL rx ids for a reply.

Outcomes reported:
  [UDS]   a 7E/7F reply            -> the gate was network-state; we have the live pair + NRC
  [TXNEW] a new broadcast id       -> the stimulus changed ECU state (partial progress)
  (none)  silent + no new ids      -> network-state is NOT the Dcm gate either (rules it out)

Run with 32-bit Python:
  <py311x86>\\python.exe bench/nm_uds_probe.py --secs 40
  ...\\python.exe bench/nm_uds_probe.py --secs 60 --diag-req 0x6b4 --diag-rx 0x6b8
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, crc8_j1850, HEARTBEAT_ID, module_alive  # noqa: E402

NM_NODES = [0x4a, 0x5f, 0x98, 0x99, 0x9a, 0xd4]
NM_CTRLS = [0x00, 0x42]
CONTAINER_ID = 0x40c
NM_DIRECT_IDS = [0x441, 0x395]            # module-B NM-range ids from rx_filter_map (handler 0x12729)

# UDS probes cycled on the diag pair
UDS_PROBES = [bytes.fromhex("3E00"), bytes.fromhex("1003"), bytes.fromhex("22F187")]


def container_frames(node):
    """0x40c container, 0x600 sub-PDU = [node, 0x20, 0,0] (byte1 bit5 -> tx_gate2). Multi-frame."""
    s6 = bytes([node, 0x20, 0x00, 0x00])
    body = bytes([0x07]) + bytes([0x06, 0x00]) + s6 + bytes([0x06, 0xf1, 0xa3, 0, 0, 0]) \
        + bytes([0x0b, 0xf1, 0xa4, 0, 0, 0, 0, 0, 0, 0, 0])
    return body[:23].ljust(23, b"\0")


def send_container(c, payload):
    n = len(payload)
    c.write(CONTAINER_ID, bytes([0x10, n & 0xff]) + payload[:6])
    idx, sn = 6, 1
    while idx < n:
        c.write(CONTAINER_ID, bytes([0x20 | (sn & 0xf)]) + payload[idx:idx + 7].ljust(7, b"\0"))
        idx += 7
        sn += 1


def send_nm_direct(c, node, ctrl):
    """Direct NM frame: node-id in data byte2 (per nm_msg_process), on id 0x400+node and the
    rx-filter NM-range ids."""
    frame = bytes([0x00, 0x00, node, 0x00, 0x00, 0x00, ctrl, 0x00])
    c.write(0x400 + node, frame)
    for nid in NM_DIRECT_IDS:
        c.write(nid, frame)


def iso_tp_sf(payload):
    return bytes([len(payload)]) + payload + b"\xAA" * (8 - 1 - len(payload))


def is_reply(payload, req_sid):
    if not payload:
        return False
    if payload[0] == 0x7F and len(payload) >= 2 and payload[1] == req_sid:
        return True
    return payload[0] == (req_sid + 0x40)


def decode_sf(payload):
    if not payload:
        return None
    if (payload[0] >> 4) == 0:
        return payload[1:1 + (payload[0] & 0xF)]
    if (payload[0] >> 4) == 1:
        return payload[2:]
    return None


NRC = {0x10: "generalReject", 0x11: "serviceNotSupported", 0x22: "conditionsNotCorrect",
       0x31: "requestOutOfRange", 0x33: "securityAccessDenied", 0x78: "responsePending",
       0x7E: "subFnNotSuppInActiveSession", 0x7F: "svcNotSuppInActiveSession"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=None)
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--secs", type=float, default=40.0)
    ap.add_argument("--stim-ms", type=int, default=20, help="NM stimulus period (<=20 => >=50Hz)")
    ap.add_argument("--probe-ms", type=int, default=250, help="UDS probe period")
    ap.add_argument("--diag-req", type=lambda s: int(s, 0), default=0x6B4)
    ap.add_argument("--diag-rx", type=lambda s: int(s, 0), default=0x6B8)
    a = ap.parse_args()

    c = RawCAN(dll=a.dll, baud=a.baud) if a.dll else RawCAN(baud=a.baud)

    # baseline broadcast ids (so we can detect NEW ones)
    base = set()
    t = time.time()
    while time.time() - t < 1.5:
        r = c.read(10)
        if r:
            base.add(r[0])
    print(f"[*] baseline broadcast ids: {sorted(hex(x) for x in base)}")
    if not (base - {HEARTBEAT_ID}):
        print("[!] module is SILENT at start (asleep/powered down). NM stimulus here is meant to wake")
        print("    it, but note: if it stays silent AND no UDS reply appears, the result is about")
        print("    wake-ability, not the Dcm gate. A power cycle may be required first.")
    print(f"[*] driving NM stimulus (container 0x40c + direct NM) every {a.stim_ms}ms, "
          f"UDS probe on 0x{a.diag_req:03x}->0x{a.diag_rx:03x} every {a.probe_ms}ms, {a.secs:.0f}s")

    t0 = time.time()
    last_stim = last_probe = 0.0
    ni = pi = 0
    uds_hits = []
    tx_new = {}
    try:
        while time.time() - t0 < a.secs:
            now = time.time()
            if (now - last_stim) * 1000 >= a.stim_ms:
                last_stim = now
                node = NM_NODES[ni % len(NM_NODES)]
                ctrl = NM_CTRLS[(ni // len(NM_NODES)) % len(NM_CTRLS)]
                send_container(c, container_frames(node))
                send_nm_direct(c, node, ctrl)
                ni += 1
            if (now - last_probe) * 1000 >= a.probe_ms:
                last_probe = now
                req = UDS_PROBES[pi % len(UDS_PROBES)]
                pi += 1
                c.write(a.diag_req, iso_tp_sf(req))
                # drain replies for a short window
                tw = time.time()
                while (time.time() - tw) * 1000 < 80:
                    r = c.read(10)
                    if not r:
                        continue
                    rid, pl = r
                    if rid not in base and rid != HEARTBEAT_ID and rid not in tx_new:
                        tx_new[rid] = pl.hex()
                        print(f"  [TXNEW] new broadcast id 0x{rid:03x} = {pl.hex()}  (t={now-t0:.1f}s)")
                    uds = decode_sf(pl)
                    if uds and is_reply(uds, req[0]):
                        kind = (f"7F {NRC.get(uds[2], hex(uds[2]))}" if uds[0] == 0x7F else "POSITIVE")
                        print(f"  [UDS] req {req.hex()} -> rx0x{rid:03x}: {kind}  [{uds.hex(' ')}]")
                        uds_hits.append((rid, req.hex(), bytes(uds)))
            else:
                r = c.read(2)
                if r and r[0] not in base and r[0] != HEARTBEAT_ID and r[0] not in tx_new:
                    tx_new[r[0]] = r[1].hex()
                    print(f"  [TXNEW] new broadcast id 0x{r[0]:03x} = {r[1].hex()}  (t={now-t0:.1f}s)")
    finally:
        c.close()

    print("\n=== SUMMARY ===")
    if uds_hits:
        print(f"UDS RESPONDED under NM stimulus ({len(uds_hits)} reply/replies): network state WAS the gate.")
        for rid, req, uds in uds_hits:
            print(f"  0x{rid:03x}  req {req}: {uds.hex(' ')}")
    elif tx_new:
        print(f"No UDS reply, but stimulus produced NEW broadcast ids {sorted(hex(x) for x in tx_new)}")
        print("=> stimulus changed ECU state but did not open diagnostics; iterate the NM content.")
    else:
        print("No UDS reply and NO new broadcast ids under NM stimulus.")
        print("=> network-management state is NOT the Dcm gate either (consistent with the module")
        print("   already being operational). The gate is diagnostic-subsystem-specific - next look")
        print("   at a different physical diag bus (module A pins 37/24), 29-bit ISO-TP addressing,")
        print("   or a TX-sanity check that our frames reach the module.")


if __name__ == "__main__":
    main()
