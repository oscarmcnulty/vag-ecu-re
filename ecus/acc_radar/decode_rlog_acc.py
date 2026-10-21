#!/usr/bin/env python3
"""Decode the ACC-radar TP2.0/KWP diagnostic traffic from an openpilot rlog.

Pairs with the in-branch poller (opendbc .../volkswagen/tp20diag.py), which TX's the
diagnostic frames on panda bus 2; the radar's replies are captured in the rlog. This
reads them back offline.

PROBE stage: prints the TP2.0 channel-setup response (D0) so you can read the radar-
assigned channel ids (ECU_TX / TESTER_TX) and confirm bus-2 reachability.
POLL stage: reassembles the KWP measuring-block responses and decodes each field with
the self-describing VAG formula table (same as op_acc_blocks.py).

Usage:  <openpilot-venv-python> decode_rlog_acc.py <rlog.zst> [--bus 2]
"""
import argparse
import sys

sys.path.insert(0, "/home/om/openpilot")
from openpilot.tools.lib.logreader import LogReader  # noqa: E402

# VAG self-describing measuring-block formulas (first byte of a 3-byte field)
def decode_field(f, a, b):
    w = a * 256 + b
    if f == 0x06: return f"{a*b*0.001:.2f} V"
    if f == 0x1a: return f"{b-a} degC"
    if f == 0x70: return f"{(b-128)*a*0.001:+.3f} deg"
    if f == 0x77: return f"{a*b*0.01:.2f} %"
    if f in (0x4b, 0x59, 0xa1, 0x25, 0x36): return f"{w}" + (" (none)" if w == 0xffff else "")
    return f"a={a} b={b} (fmt 0x{f:02x}?)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rlog")
    ap.add_argument("--bus", type=int, default=2, help="panda bus the radar is on (default 2)")
    ap.add_argument("--setup-resp", default="0x20b", help="TP2.0 setup-response CAN id")
    ap.add_argument("--ecu-tx", default="0x300", help="ECU->tester channel id (from the probe)")
    args = ap.parse_args()
    setup_resp = int(args.setup_resp, 0)
    ecu_tx = int(args.ecu_tx, 0)

    lr = LogReader(args.rlog)
    setups = set()
    frames = []  # (ts, data) on ecu_tx, in order
    n = 0
    for msg in lr:
        if msg.which() != "can":
            continue
        for c in msg.can:
            if c.src != args.bus:
                continue
            if c.address == setup_resp and len(c.dat) >= 6 and c.dat[1] == 0xD0:
                d = bytes(c.dat)
                ids = (d[2] | (d[3] << 8), d[4] | (d[5] << 8))
                if d.hex() not in setups:
                    setups.add(d.hex())
                    print(f"[SETUP D0] {setup_resp:#05x}: {d.hex()}  -> "
                          f"ECU_TX={ids[0]:#05x}  TESTER_TX={ids[1]:#05x}")
            if c.address == ecu_tx:
                frames.append(bytes(c.dat))
        n += 1

    # Reassemble TP2.0 data frames on ecu_tx into KWP responses (opcode 0x2X consec / 0x1X last)
    print(f"\n{len(frames)} frame(s) on ECU_TX {ecu_tx:#05x}; reassembling KWP responses…")
    chunks, exp = [], None
    for d in frames:
        if not d:
            continue
        op = d[0]
        if (op & 0xF0) in (0x00, 0x10, 0x20, 0x30):
            if not chunks:
                if len(d) >= 3:
                    exp = (d[1] << 8) | d[2]
                    chunks.append(d[3:])
            else:
                chunks.append(d[1:])
            if (op & 0xF0) in (0x10, 0x30):     # last frame
                full = b"".join(chunks)
                resp = full[:exp] if exp else full
                if resp and resp[0] == 0x61:    # readMeasuringBlock response
                    grp = resp[1]
                    body = resp[2:]
                    fields = [decode_field(body[i], body[i+1], body[i+2]) for i in range(0, len(body)-2, 3)] \
                        if len(body) % 3 == 0 and len(body) <= 12 else [f"raw {body.hex()}"]
                    print(f"  group {grp:3}: " + " | ".join(fields))
                chunks, exp = [], None


if __name__ == "__main__":
    main()
