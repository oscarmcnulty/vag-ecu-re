#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — feed the module's full expected VEHICLE-CONTEXT RX set, then probe UDS.

Hypothesis (2026-10-01): the ABS receives diag requests but never answers (uds_session.py) even with a
proper ISO-TP VW_Flash sequence + NM wake. The module is the gateway-connected diag node, so its Dcm
may only activate when it sees a plausible vehicle environment (partner ECUs + gateway/enable frames),
not just NM. This tool continuously transmits EVERY CAN id module B is configured to receive (from
decode/rx_filter_map.txt, excluding the module's own TX and the diag ids) with counter+CRC content,
alongside the NM wake, then probes UDS and watches for the Dcm to come alive.

Win = any 7E/7F on a diag pair. Also reports any NEW broadcast id (state change).

Run with 32-bit Python:
  <py311x86>\\python.exe bench/vehicle_context.py --secs 45
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, crc8_j1850, module_alive, HEARTBEAT_ID  # noqa: E402
from nm_uds_probe import container_frames, send_container, send_nm_direct, NM_NODES  # noqa: E402

# module-B RX ids (handler!=0) minus own-TX and diag — the vehicle frames it expects to receive.
CONTEXT_IDS = [0x019, 0x062, 0x085, 0x086, 0x08b, 0x09f, 0x102, 0x104, 0x105, 0x110, 0x114,
               0x117, 0x11d, 0x203, 0x394, 0x395, 0x441, 0x4a3, 0x641, 0x6c0, 0x6c7, 0x6d0,
               0x6ff, 0x7e0]
# NM-range ids are already driven by the NM wake; drop to avoid clobbering it
CONTEXT_IDS = [c for c in CONTEXT_IDS if c not in (0x395, 0x441)]

DIAG_PAIRS = [(0x6B4, 0x6B8), (0x713, 0x77D)]
UDS_PROBES = [bytes.fromhex("3E00"), bytes.fromhex("1003")]
NRC = {0x11: "serviceNotSupported", 0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange",
       0x33: "securityAccessDenied", 0x78: "responsePending", 0x7F: "svcNotSuppInActiveSession",
       0x7E: "subFnNotSuppInActiveSession", 0x12: "subFnNotSupported"}


def ctx_frame(cid, ctr):
    body = bytes([0, 0, 0, 0, 0, 0x08, ctr & 0xFF])
    return body + bytes([crc8_j1850(body)])


def iso_sf(payload):
    return bytes([len(payload)]) + payload + b"\xAA" * (7 - len(payload))


def is_reply(uds, sid):
    if not uds:
        return False
    if uds[0] == 0x7F and len(uds) >= 2 and uds[1] == sid:
        return True
    return uds[0] == (sid + 0x40)


def decode_sf(pl):
    if pl and (pl[0] >> 4) in (0, 1):
        return pl[2:] if (pl[0] >> 4) == 1 else pl[1:1 + (pl[0] & 0xF)]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=None)
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--secs", type=float, default=45.0)
    ap.add_argument("--ctx-hz", type=int, default=20, help="rate to cycle the context set")
    a = ap.parse_args()

    can = RawCAN(dll=a.dll, baud=a.baud) if a.dll else RawCAN(baud=a.baud)
    base = set()
    hits = []
    txnew = {}
    try:
        # wake
        print("[*] waking + establishing vehicle context...")
        wni = 0
        t = time.time()
        while time.time() - t < 8 and not base:
            for i in range(10):
                send_container(can, container_frames(NM_NODES[i % 6]))
                send_nm_direct(can, NM_NODES[i % 6], 0)
            base = module_alive(can, 0.5)
        print(f"[*] module {'AWAKE ' + str(sorted(hex(x) for x in base)) if base else 'SILENT (will keep driving)'}")

        print(f"[*] feeding {len(CONTEXT_IDS)} context ids @~{a.ctx_hz}Hz + NM wake, probing UDS, {a.secs:.0f}s")
        t0 = time.time()
        last_ctx = last_nm = last_probe = 0.0
        ctr = 0
        pi = 0
        while time.time() - t0 < a.secs:
            now = time.time()
            if (now - last_nm) * 1000 >= 20:
                last_nm = now
                send_container(can, container_frames(NM_NODES[wni % 6]))
                send_nm_direct(can, NM_NODES[wni % 6], 0)
                wni += 1
            if (now - last_ctx) * 1000 >= (1000 / a.ctx_hz):
                last_ctx = now
                ctr += 1
                for cid in CONTEXT_IDS:
                    can.write(cid, ctx_frame(cid, ctr))
            if (now - last_probe) * 1000 >= 300:
                last_probe = now
                for rq, rx in DIAG_PAIRS:
                    req = UDS_PROBES[pi % len(UDS_PROBES)]
                    can.write(rq, iso_sf(req))
                pi += 1
                tw = time.time()
                while (time.time() - tw) * 1000 < 60:
                    r = can.read(10)
                    if not r:
                        continue
                    rid, pl = r
                    if rid not in base and rid != HEARTBEAT_ID and rid not in CONTEXT_IDS and rid not in txnew:
                        txnew[rid] = pl.hex()
                        print(f"  [TXNEW] 0x{rid:03x} = {pl.hex()} (t={now-t0:.1f}s)")
                    uds = decode_sf(pl)
                    for rq, rxexp in DIAG_PAIRS:
                        for probe in UDS_PROBES:
                            if uds and is_reply(uds, probe[0]):
                                kind = (f"7F {NRC.get(uds[2], hex(uds[2]))}" if uds[0] == 0x7F else "POSITIVE")
                                print(f"  [UDS] rx0x{rid:03x}: {kind}  [{uds.hex(' ')}]")
                                hits.append((rid, bytes(uds)))
    finally:
        can.close()

    print("\n=== RESULT ===")
    if hits:
        print(f"Dcm RESPONDED with vehicle context present ({len(hits)} reply/replies): the gate was context.")
        for rid, uds in hits:
            print(f"  rx0x{rid:03x}: {uds.hex(' ')}")
    else:
        print("Still SILENT with the full module-B vehicle-context RX set fed + NM wake.")
        if txnew:
            print(f"  (but new broadcast ids appeared: {sorted(hex(x) for x in txnew)} — partial state change)")
        print("  => the Dcm enable is not satisfied by these partner frames alone. Likely needs the real")
        print("     gateway (routing-active / diagnostics-enable), a specific frame value we didn't guess,")
        print("     or a KL15 hard-wire input. Next: gateway in the loop, or trace the island diag gate.")


if __name__ == "__main__":
    main()
