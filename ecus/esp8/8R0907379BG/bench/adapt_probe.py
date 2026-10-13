#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — adaptation/calibration channel probe.

Probes the VAG-proprietary KWP2000 adaptation channel protocol in session 0x83
(calibration) with calibration SA unlocked (seed+0x75fb). Also tests in sessions
0x89 and 0x86 for comparison.

VAG KWP adaptation channel ops:
  0xB8 = open/select adaptation channel (channel ID in byte 2)
  0xB9 = read next adaptation value
  0xBA = write/save adaptation value

Also probes:
  - SID 0x21 with extended sub-functions (potential measurement-by-address)
  - SID 0x2E WriteDataByCommonId with F-range DIDs
  - SID 0x3B WriteDataByLocalId
  - SID 0x22 with broader DID sweep
  - Any non-standard VAG KWP ops (0x46-0x50 range from the CLASS table)

Usage (32-bit python, module powered):
  adapt_probe.py                    # full probe in all sessions
  adapt_probe.py --session 83       # probe only session 0x83
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import LockedCAN, Stim, open_quiet, req_sid
from tp20_kwp import kfmt

SA_KEY_CODING = 0x2909
SA_KEY_CALIB  = 0x75fb


def sa_unlock(tp, key_constant, label):
    """SA unlock (27 03/04) with the given key constant."""
    sr = req_sid(tp, b'\x27\x03', tries=3, timeout=2.0)
    tp.keepalive(force=True)
    if not sr or sr[0] != 0x67 or len(sr) < 6:
        print(f"    [!] SA seed failed for {label}: {kfmt(sr)}")
        return False
    seed = int.from_bytes(sr[2:6], 'big')
    key = (seed + key_constant) & 0xFFFFFFFF
    kb = key.to_bytes(4, 'big')
    kr = req_sid(tp, b'\x27\x04' + kb, tries=1, timeout=2.0)
    tp.keepalive(force=True)
    if kr and kr[0] == 0x67:
        print(f"    [*] {label} UNLOCKED")
        return True
    print(f"    [!] {label} key rejected: {kfmt(kr)}")
    return False


def probe_adaptation_channels(tp, session_name):
    """Probe VAG adaptation channel ops 0xB8/0xB9/0xBA.

    Firmware handler at 0x1d7a8 reads TWO data bytes (buf[0x10b], buf[0x10c])
    and constructs a 16-bit channel ID: buf[0x10c] + buf[0x10b] * 0x100.
    Request format: B8 <hi> <lo> (3 bytes total).
    """
    print(f"\n  === Adaptation channels (0xB8/0xB9/0xBA) in {session_name} ===")

    # Determine request format: 2-byte vs 3-byte
    print("    Format detection:")
    for req, label in [
        (bytes([0xB8, 0x00, 0x01]), "B8 00 01 (3-byte, ch=0x0001)"),
        (bytes([0xB8, 0x01, 0x00]), "B8 01 00 (3-byte, ch=0x0100)"),
        (bytes([0xB8, 0x01]),       "B8 01    (2-byte, ch=??)"),
        (bytes([0xB9]),             "B9       (read, no channel open)"),
    ]:
        r = req_sid(tp, req, tries=2, timeout=1.5)
        tp.keepalive(force=True)
        print(f"      {label:40s} -> {kfmt(r)}")

    # Check if 0xB8 is recognized at all
    r_test = req_sid(tp, bytes([0xB8, 0x00, 0x01]), tries=2, timeout=1.5)
    tp.keepalive(force=True)
    if r_test and r_test[0] == 0x7F and r_test[2] == 0x11:
        print(f"    [*] SID 0xB8 not supported in {session_name}")
        return {}

    # Phase 1: sweep single-byte channels 0x00-0xFF (sent as B8 00 xx)
    print(f"\n    Phase 1: Sweeping B8 00 xx (channels 0x0000-0x00FF):")
    results = {}
    positive = 0
    for ch in range(0x100):
        r = req_sid(tp, bytes([0xB8, 0x00, ch]), tries=2, timeout=1.0)
        tp.keepalive(force=True)
        if r and r[0] == 0xF8:
            print(f"      B8 00 {ch:02X} -> POSITIVE [{r.hex(' ')}]")
            results[ch] = r
            positive += 1
            # Read ALL available records from this channel (up to 70)
            for rec in range(70):
                rd = req_sid(tp, bytes([0xB9]), tries=1, timeout=1.0)
                tp.keepalive(force=True)
                if rd and rd[0] == 0xF9:
                    asc = bytes(b if 32 <= b < 127 else 46 for b in rd[1:]).decode()
                    print(f"        B9 rec{rec:2d} -> [{rd.hex(' ')}]  {asc}")
                else:
                    print(f"        B9 rec{rec:2d} -> {kfmt(rd)}  (end)")
                    break
            # Re-open channel, then try a write (0xBA) to see the response format
            req_sid(tp, bytes([0xB8, 0x00, ch]), tries=1, timeout=1.0)
            tp.keepalive(force=True)
            wr = req_sid(tp, bytes([0xBA, 0x00, ch, 0x00, 0x00]), tries=1, timeout=1.0)
            tp.keepalive(force=True)
            print(f"        BA write -> {kfmt(wr)}")
        elif r and r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            if nrc not in (0x31, 0x12):
                print(f"      B8 00 {ch:02X} -> NRC {nrc:#04x} [{r.hex(' ')}]")
                results[ch] = r
        if (ch & 0x3F) == 0x3F:
            print(f"        ... 0x{ch-0x3F:02X}-0x{ch:02X} done ({positive} positive)")

    # Phase 2: probe specific IDs from firmware table at 0xB8D98
    fw_table_ids = [
        0x2B40, 0x002C, 0x0109, 0x52D2, 0x0D22, 0x5A09, 0xD2D2, 0x0A09,
        0x0278, 0x420A, 0x8040, 0xD5D2, 0x3EE0, 0x0C09, 0xADD2, 0x4D09,
    ]
    coding_table_ids = [
        0x82D3, 0x00E1, 0x1109, 0x42D3, 0x0C09, 0x02D3, 0x0708, 0xC2D3,
        0x0208, 0x80D3,
    ]
    extra_ids = sorted(set(fw_table_ids + coding_table_ids))
    print(f"\n    Phase 2: Firmware table IDs ({len(extra_ids)} unique):")
    for ch_id in extra_ids:
        hi = (ch_id >> 8) & 0xFF
        lo = ch_id & 0xFF
        r = req_sid(tp, bytes([0xB8, hi, lo]), tries=2, timeout=1.0)
        tp.keepalive(force=True)
        if r and r[0] == 0xF8:
            print(f"      B8 {hi:02X} {lo:02X} (0x{ch_id:04X}) -> POSITIVE [{r.hex(' ')}]")
            results[ch_id] = r
            positive += 1
            rd = req_sid(tp, bytes([0xB9]), tries=1, timeout=1.0)
            tp.keepalive(force=True)
            if rd:
                print(f"        B9 read -> {kfmt(rd)}")
        elif r and r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            nrc_names = {0x11: "svcNotSupp", 0x12: "subFnNotSupp", 0x22: "condNotCorr",
                         0x31: "outOfRange", 0x33: "secAccDenied"}
            print(f"      B8 {hi:02X} {lo:02X} (0x{ch_id:04X}) -> NRC {nrc_names.get(nrc, hex(nrc))}")
        else:
            print(f"      B8 {hi:02X} {lo:02X} (0x{ch_id:04X}) -> {kfmt(r)}")

    # Phase 3: special channel 0x0FFF (firmware: triggers security_unlock_set(0))
    print(f"\n    Phase 3: Special channels:")
    r = req_sid(tp, bytes([0xB8, 0x0F, 0xFF]), tries=2, timeout=1.5)
    tp.keepalive(force=True)
    print(f"      B8 0F FF (0x0FFF, SA reset) -> {kfmt(r)}")

    print(f"\n    [{session_name}] Adaptation: {positive} positive total")
    return results


def probe_vag_proprietary_sids(tp, session_name):
    """Probe VAG-specific KWP SIDs from the CLASS table (0x46-0x50 range)."""
    print(f"\n  === VAG-proprietary SIDs in {session_name} ===")

    probes = [
        # SID 0x46: CLASS 0x00 (public) for sub 0x01-0x0F
        (b'\x46\x01', "46 01 (CLASS 0x00, public)"),
        (b'\x46\x02', "46 02"),
        (b'\x46\x0F', "46 0F"),
        (b'\x46\x10', "46 10 (CLASS 0x0a)"),
        (b'\x46\x40', "46 40 (CLASS 0x26, high)"),
        # SID 0x47
        (b'\x47\x01', "47 01 (CLASS 0x0a)"),
        (b'\x47\x3F', "47 3F (CLASS 0x25)"),
        (b'\x47\x41', "47 41 (CLASS 0x24)"),
        # SID 0x48-0x4C
        (b'\x48\x01', "48 01 (CLASS 0x0c)"),
        (b'\x49\x01', "49 01 (CLASS 0x0c)"),
        (b'\x4A\x01', "4A 01 (CLASS 0x0c)"),
        (b'\x4A\x50', "4A 50 (CLASS 0x27)"),
        (b'\x4B\x01', "4B 01 (CLASS 0x0c)"),
        (b'\x4C\x01', "4C 01 (CLASS 0x0c)"),
        # SID 0x4D
        (b'\x4D\x01', "4D 01 (CLASS 0x0d)"),
        (b'\x4D\x40', "4D 40 (CLASS 0x0c)"),
        (b'\x4D\x50', "4D 50 (CLASS 0x27)"),
        # SID 0x4E
        (b'\x4E\x01', "4E 01 (CLASS 0x07)"),
        # SID 0x50
        (b'\x50\x01', "50 01 (CLASS 0x23)"),
    ]

    for kwp, label in probes:
        r = req_sid(tp, kwp, tries=2, timeout=1.5)
        tp.keepalive(force=True)
        if r and r[0] != 0x7F:
            print(f"    {label:35s} -> POSITIVE [{r.hex(' ')}]")
        elif r and r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            nrc_names = {0x11: "svcNotSupp", 0x12: "subFnNotSupp", 0x22: "condNotCorr",
                         0x31: "outOfRange", 0x33: "secAccDenied", 0x80: "custom80"}
            print(f"    {label:35s} -> NRC {nrc_names.get(nrc, hex(nrc))}")
        else:
            print(f"    {label:35s} -> {kfmt(r)}")


def probe_did_sweep(tp, session_name):
    """Broader SID 0x22 DID sweep including low-range and calibration DIDs."""
    print(f"\n  === Extended SID 0x22 DID sweep in {session_name} ===")

    # Low-range DIDs that might be measurement/calibration channels
    ranges = list(range(0x0001, 0x0020)) + list(range(0x0100, 0x0120))
    ranges += list(range(0x0200, 0x0210)) + list(range(0x0300, 0x0310))
    ranges += list(range(0x0400, 0x0420))
    # VCDS/ODIS measurement group DIDs
    ranges += list(range(0x2000, 0x2020))
    ranges += list(range(0xF000, 0xF020))
    # Calibration-specific DID ranges
    ranges += list(range(0xFD00, 0xFD20))
    ranges += list(range(0xFE00, 0xFE10))

    positive = 0
    for did in ranges:
        r = req_sid(tp, bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]), tries=2, timeout=1.0)
        tp.keepalive(force=True)
        if r and r[0] == 0x62:
            asc = bytes(b if 32 <= b < 127 else 46 for b in r[3:]).decode()
            print(f"    22 {did:04X} -> POSITIVE [{r.hex(' ')}]  {asc}")
            positive += 1
        elif r and r[0] == 0x7F and r[2] not in (0x31, 0x12, 0x11):
            nrc = r[2]
            print(f"    22 {did:04X} -> NRC {nrc:#04x}")

    print(f"    [{session_name}] Extended DID sweep: {positive} positive")


def probe_measurement_by_address(tp, session_name):
    """Try various approaches to read memory by address through measurement services."""
    print(f"\n  === Measurement-by-address attempts in {session_name} ===")

    # SID 0x21 with sub-functions that might take address parameters
    # Some VAG ECUs use 0x21 F0-FF as "read by address" aliases
    print("  SID 0x21 high sub-functions (0xF0-0xFF):")
    for sub in range(0xF0, 0x100):
        r = req_sid(tp, bytes([0x21, sub]), tries=2, timeout=1.0)
        tp.keepalive(force=True)
        if r and r[0] == 0x61:
            print(f"    21 {sub:02X} -> POSITIVE [{r.hex(' ')}]")

    # SID 0x21 with extra address bytes appended (non-standard extension)
    print("\n  SID 0x21 with address payload (extended format):")
    test_addrs = [
        (b'\x21\x01\x00\x00\x00', "21 01 + addr 000000"),
        (b'\x21\x01\x00\x01\x00', "21 01 + addr 000100"),
        (b'\x21\x01\x40\x00\x00', "21 01 + addr 400000"),
        (b'\x21\xFF\x00\x00\x00\x10', "21 FF + addr 000000 len 10"),
    ]
    for kwp, label in test_addrs:
        r = req_sid(tp, kwp, tries=2, timeout=1.0)
        tp.keepalive(force=True)
        status = f"POSITIVE [{r.hex(' ')}]" if r and r[0] == 0x61 else kfmt(r)
        print(f"    {label:35s} -> {status}")

    # SID 0x2C DynamicallyDefineLocalIdentifier — can define a DID pointing at an address
    print("\n  SID 0x2C DynamicallyDefineLocalIdentifier:")
    # Format: 2C <localId> <defType> <memAddr3> <memSize>
    # defType=01 = defineByMemoryAddress
    test_defs = [
        (b'\x2C\xF0\x01\x00\x01\x00\x10', "2C F0 defByAddr @000100 len=16"),
        (b'\x2C\xF0\x01\x40\x00\x00\x10', "2C F0 defByAddr @400000 len=16"),
        (b'\x2C\xF0\x01\x00\x00\x00\x10', "2C F0 defByAddr @000000 len=16"),
    ]
    for kwp, label in test_defs:
        r = req_sid(tp, kwp, tries=2, timeout=1.5)
        tp.keepalive(force=True)
        status = f"POSITIVE [{r.hex(' ')}]" if r and r[0] == 0x6C else kfmt(r)
        print(f"    {label:40s} -> {status}")
        if r and r[0] == 0x6C:
            # Try reading the newly defined DID
            rd = req_sid(tp, b'\x21\xF0', tries=2, timeout=1.0)
            tp.keepalive(force=True)
            print(f"      -> read 21 F0: {kfmt(rd)}")

    # SID 0x2C defType=02 = defineByIdentifier (point at another DID with offset)
    r = req_sid(tp, b'\x2C\xF1\x02\x01\x01\x04', tries=2, timeout=1.5)
    tp.keepalive(force=True)
    print(f"    2C F1 defByIdent (DID 01, pos 1, sz 4)   -> {kfmt(r)}")


def probe_routine_control(tp, session_name):
    """Sweep SID 0x31 RoutineControl for any data-returning routines."""
    print(f"\n  === SID 0x31 RoutineControl sweep in {session_name} ===")
    positive = 0
    for sub in range(0x01, 0x100):
        r = req_sid(tp, bytes([0x31, sub]), tries=2, timeout=1.5)
        tp.keepalive(force=True)
        if r and r[0] == 0x71:
            print(f"    31 {sub:02X} -> POSITIVE [{r.hex(' ')}]")
            positive += 1
        elif r and r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            if nrc not in (0x31, 0x12):  # skip requestOutOfRange/subFnNotSupported
                print(f"    31 {sub:02X} -> NRC {nrc:#04x}")
        if (sub & 0x3F) == 0x3F:
            print(f"      ... 0x{sub-0x3F:02X}-0x{sub:02X} done ({positive} positive)")
    print(f"    [{session_name}] RoutineControl: {positive} positive")


def probe_io_control(tp, session_name):
    """Probe SID 0x30 InputOutputControlByLocalId."""
    print(f"\n  === SID 0x30 IOControl in {session_name} ===")
    for sub in range(0x01, 0x20):
        r = req_sid(tp, bytes([0x30, sub]), tries=2, timeout=1.0)
        tp.keepalive(force=True)
        if r and r[0] != 0x7F:
            print(f"    30 {sub:02X} -> POSITIVE [{r.hex(' ')}]")
        elif r and r[0] == 0x7F and r[2] not in (0x11, 0x12, 0x31):
            print(f"    30 {sub:02X} -> NRC {r[2]:#04x}")


def run_session(tp, session_id, session_name, sa_key=None, sa_label=None):
    """Run the full probe suite in a given session."""
    print(f"\n{'=' * 70}")
    print(f"SESSION 0x{session_id:02X} ({session_name})")
    print(f"{'=' * 70}")

    # Enter session
    r = req_sid(tp, bytes([0x10, session_id]))
    print(f"  10 {session_id:02X} -> {kfmt(r)}")
    if not (r and r[0] == 0x50):
        print(f"  [!] Session 0x{session_id:02X} refused")
        return

    # SA unlock if needed
    if sa_key is not None:
        sa_unlock(tp, sa_key, sa_label)

    probe_adaptation_channels(tp, session_name)
    probe_vag_proprietary_sids(tp, session_name)
    probe_measurement_by_address(tp, session_name)
    probe_did_sweep(tp, session_name)
    probe_routine_control(tp, session_name)
    probe_io_control(tp, session_name)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="all",
                    help="83|89|86|all (default: all)")
    args = ap.parse_args()

    sessions = []
    if args.session == "all":
        sessions = [
            (0x89, "app", None, None),
            (0x83, "calibration", SA_KEY_CALIB, "calibration SA (+0x75fb)"),
            (0x86, "coding", SA_KEY_CODING, "coding SA (+0x2909)"),
        ]
    else:
        sid = int(args.session, 16)
        if sid == 0x89:
            sessions = [(0x89, "app", None, None)]
        elif sid == 0x83:
            sessions = [(0x83, "calibration", SA_KEY_CALIB, "calibration SA (+0x75fb)")]
        elif sid == 0x86:
            sessions = [(0x86, "coding", SA_KEY_CODING, "coding SA (+0x2909)")]

    print("[*] ESP8 adaptation/calibration channel probe")

    c = LockedCAN()
    stim = Stim(c, hz=50, ids=[0x200])
    stim.start()
    tp = None

    try:
        tp = open_quiet(c, stim)
        if tp is None:
            print("[!] TP2.0 open failed")
            return
        print(f"[*] TP2.0 OPEN TX->0x{tp.tx:03x} RX<-0x{tp.rx:03x}")
        tp.maintain(2.0)

        # Always start with 10 89 to establish a baseline session
        r89 = req_sid(tp, b'\x10\x89')
        print(f"  10 89 (warmup) -> {kfmt(r89)}")
        if not (r89 and r89[0] == 0x50):
            print("[!] Cannot enter app session — is the module awake?")
            return

        for session_id, name, sa_key, sa_label in sessions:
            # Reset to app session between tests
            req_sid(tp, b'\x10\x89')
            tp.keepalive(force=True)
            time.sleep(0.5)

            if session_id == 0x86:
                # 0x86 needs SA before session entry
                sa_unlock(tp, SA_KEY_CODING, "coding SA (+0x2909)")
                run_session(tp, session_id, name)
            elif sa_key is not None:
                # 0x83: enter session first, then SA
                run_session(tp, session_id, name, sa_key, sa_label)
            else:
                run_session(tp, session_id, name)

    finally:
        stim.stop = True
        stim.join(timeout=1.0)
        if tp:
            try:
                tp.close()
            except Exception:
                pass
        c.close()

    print("\n[*] Done.")


if __name__ == "__main__":
    main()
