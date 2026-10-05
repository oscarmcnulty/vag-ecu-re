#!/usr/bin/env python3
"""Drive the ESP8 toward FULL ComM / NM "network-operational" by feeding the 0x36E NM container.

WHAT THIS DOES
  Runs a background restbus stimulus (reuses LockedCAN + Stim from emu_unlock) that transmits
  BOTH a keepalive id (so the bus is seen "alive") AND the NM-container frame carrying a valid
  node-id, then after a warmup it passively sniffs for the module going FULL-operational -- i.e.
  broadcasting its OWN application ids (ESP_01 0x100 / ESP_02 0x101 / 0x103 / ESP_05 0x106 /
  ESP_08 0x11e / 0x08a) beyond the pre-operational 0x060 heartbeat -- and prints the verdict.

  SAFE: transmit + sniff only. No diagnostic session, no SecurityAccess, no key. Read-only w.r.t.
  module state. (Still: do not run while another tool owns the single SM2 J2534 device.)

FRAME BYTE ORDER  (decoded from transport_rx_process @0x689e4 + nm_msg_process @0x40950, BE firmware)
  The 0x36E IpduM container's contained NM sub-PDU header is 0x0600. In the reassembly buffer the
  layout after the 2-byte sub-id is:
        buf+0x10a +0x10b | +0x10c  +0x10d   +0x10e +0x10f
          06     00      | nodeid  control  sig2   sig3
  transport_rx_process builds the NM word  = (P2<<24)|(P1<<16)|(P0<<8)|P3  where
  P0=buf+0x10c, P1=+0x10d, P2=+0x10e, P3=+0x10f, then calls nm_msg_process(&word,1).
  nm_node_lookup matches the node-id as  (word<<16)>>24 == P0 == buf+0x10c == the FIRST data byte
  AFTER the 06 00 header. nm_msg_process's control-byte check is P1 (second data byte) & 0xD6 == 0
  (mask 0x29 ^ 0xff, from 0xbda3e).  tx_gate2 = bit21 of the NM word = bit5 (0x20) of the control
  byte, so control=0x20 both passes the 0xD6 check (0x20 & 0xD6 == 0) AND asserts the TX gate.
  => on a single classic 8-byte CAN frame the payload is:
        06 00 <nodeid> <control> 00 00 00 00
     node-id at byte index 2, control at byte index 3.  (NOT nodeid at byte4 -- that guess is wrong.)
  Default node-id 0x5f is a valid node-table entry (0xbd83c idx0, field1=0x08 in 1..0x19).
  Other valid node-ids seen in the table: 0x9a,0x99,0x98,0x4a (+0xd4 per decompile comment).

CAVEATS (read before trusting a negative result)
  * 0x36E is the internal IpduM CONTAINER id (flash template @0xb575c: container 0x036e ->
    {0x0600 len4, 0xf1a3 len3, 0xf1a4 len8}). It is NOT found in either RX-acceptance filter:
    the module-A/chassis filter @0xafae0 (136 ids, max 0x258, no 0x3xx/0x4xx) and the module-B
    diag filter @0xaea38 (0x5axx/0x440) both lack it. The physical WIRE id that carries this
    container is therefore unconfirmed -- hence --id is a parameter. If 0x36E on the wire is
    dropped by the mailbox filter, the frame never reaches the 0x600 demux. Try --id with the
    real NM wire id if known (VAG chassis NM is classically 0x4xx).
  * The 0x36E NM path is the module-A (suspension/sensor bus) CanNm path. The bench is typically
    wired to module B (diag/ESP bus, pins 26/14) where the module is ALREADY broadcasting /
    operational. Feeding 0x36E on module B will not reach the module-A NM reception. Put this on
    the correct bus/controller for it to matter.
  * Full CanNm "network-active" (state 9) additionally wants a matching 0x04b6 signal word
    (0x408f14==expected 0x408f18) per cannm_state_machine (0x6eba8); a bare NM-alive frame may
    only advance partway. The operational verdict here is observational (did new tx ids appear).

  DO NOT run live from this (sub)agent -- syntax-check only:
    <py311x86>\\python.exe -c "import ast; ast.parse(open('bench/nm_operational.py').read())"
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import ACCEPTED_IDS, HEARTBEAT_ID, crc8_j1850
from emu_unlock import LockedCAN, Stim

# The module's own application broadcasts: seeing any of these (beyond the 0x060 heartbeat) == it
# left pre-operational and is transmitting. (per docs/HANDOFF_uds_dump.md module-B inventory.)
OPERATIONAL_TX_IDS = {0x100, 0x101, 0x103, 0x106, 0x11e, 0x08a, 0x308, 0x392, 0x632, 0x64a, 0x6c3}


def build_nm_payload(nodeid, control):
    """6 data bytes [06 00 nodeid control 00 00]; Stim appends counter(byte6)+CRC(byte7).
    Node-id lands at frame byte index 2, control at index 3 (see module docstring)."""
    return bytes([0x06, 0x00, nodeid & 0xff, control & 0xff, 0x00, 0x00])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secs", type=float, default=8.0, help="total run time (warmup + sniff)")
    ap.add_argument("--warmup", type=float, default=3.0, help="stimulus-only time before sniffing")
    ap.add_argument("--nodeid", type=lambda x: int(x, 0), default=0x5f,
                    help="NM node-id (goes at frame byte 2). Valid: 5f,9a,99,98,4a,d4")
    ap.add_argument("--control", type=lambda x: int(x, 0), default=0x20,
                    help="NM control byte (frame byte 3). must satisfy &0xD6==0; 0x20 also sets tx_gate2")
    ap.add_argument("--id", dest="nm_id", type=lambda x: int(x, 0), default=0x36e,
                    help="wire CAN id carrying the NM container (MEDIUM confidence; see caveats)")
    ap.add_argument("--payload", default="",
                    help="override: full hex data for the NM frame (<=8 bytes), bypasses --nodeid/--control")
    ap.add_argument("--keepalive", type=lambda x: int(x, 0), default=HEARTBEAT_ID,
                    help="id for the plain keepalive frame (default 0x060 heartbeat)")
    ap.add_argument("--hz", type=int, default=8, help="stimulus passes/sec")
    ap.add_argument("--full", action="store_true",
                    help="stimulate the whole accepted-id set (0xafae0) too, not just keepalive+NM")
    a = ap.parse_args()

    if a.control & 0xD6:
        print(f"[!] WARNING: control 0x{a.control:02x} & 0xD6 != 0 -> nm_msg_process will REJECT it")

    if a.payload:
        raw = bytes.fromhex(a.payload.replace(" ", ""))
        nm_body = (raw + b"\x00" * 6)[:6]
        shown = raw.hex(" ")
    else:
        nm_body = build_nm_payload(a.nodeid, a.control)
        shown = nm_body.hex(" ") + " <ctr> <crc>"

    # stimulus id set: keepalive + NM container id (+ optional full accepted set)
    ids = []
    if a.full:
        ids.extend(ACCEPTED_IDS)
    for extra in (a.keepalive, a.nm_id):
        if extra not in ids:
            ids.append(extra)
    payloads = {a.nm_id: nm_body}

    print(f"[*] NM container id=0x{a.nm_id:03x}  frame data = {shown}")
    print(f"[*] node-id=0x{a.nodeid:02x} @byte2  control=0x{a.control:02x} @byte3  "
          f"(tx_gate2={'set' if a.control & 0x20 else 'clear'})")
    print(f"[*] stimulus {len(ids)} id(s) @ {a.hz} Hz, keepalive=0x{a.keepalive:03x}; "
          f"warmup {a.warmup:.1f}s then sniff {max(0.0, a.secs - a.warmup):.1f}s")

    c = LockedCAN()
    stim = Stim(c, a.hz, ids=ids, payloads=payloads)
    stim.start()
    pre, post = set(), set()
    t_end = time.time() + a.secs
    try:
        stim.resume()
        # pre-warmup liveness snapshot (what it already broadcasts before we push NM)
        t0 = time.time()
        while time.time() - t0 < min(1.0, a.warmup):
            r = c.read(20)
            if r and r[0] != HEARTBEAT_ID:
                pre.add(r[0])
        # finish warmup
        while time.time() - t0 < a.warmup:
            c.read(20)
        print(f"[*] pre-NM broadcasts (minus heartbeat): "
              f"{sorted(hex(x) for x in pre) if pre else 'none'}")
        # sniff phase (stimulus incl. NM still running)
        while time.time() < t_end:
            r = c.read(20)
            if r and r[0] != HEARTBEAT_ID:
                if r[0] not in post:
                    post.add(r[0])
                    tag = " <-- OPERATIONAL app-id" if r[0] in OPERATIONAL_TX_IDS else ""
                    print(f"  rx 0x{r[0]:03x}  {r[1].hex(' ')}{tag}")
    finally:
        stim.stop = True
        stim.join(timeout=1.0)
        c.close()

    op_seen = post & OPERATIONAL_TX_IDS
    new_vs_pre = post - pre
    print("\n=== RESULT ===")
    print(f"  broadcast ids during NM push : {sorted(hex(x) for x in post) if post else 'none'}")
    print(f"  known operational app-ids    : {sorted(hex(x) for x in op_seen) if op_seen else 'none'}")
    print(f"  new vs pre-NM snapshot       : {sorted(hex(x) for x in new_vs_pre) if new_vs_pre else 'none'}")
    if op_seen:
        print("  VERDICT: module is broadcasting application ids -> FULL-operational (on THIS bus).")
    elif post:
        print("  VERDICT: some non-heartbeat tx seen but no known app-id; partial / wrong-bus likely.")
    else:
        print("  VERDICT: only heartbeat -> NOT operational here. Check --id / bus / node-id, see caveats.")
    print("  NOTE: operational state does NOT by itself unlock SID 0x23/0x2E (CLASS 0x13 needs the "
          "SecurityAccess key); see GOAL-1 analysis.")


if __name__ == "__main__":
    main()
