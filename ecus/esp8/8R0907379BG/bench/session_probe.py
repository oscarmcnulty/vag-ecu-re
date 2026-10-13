#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — comprehensive KWP2000 session & service probe.

Probes all 4 diagnostic sessions and documents what services are available in each.
Phases 1-3 run in one power cycle; phase 4 requires a fresh power-cycle.

  Phase 1: session 0x89 (application) — measurement block sweep (SID 0x21)
  Phase 2: session 0x83 (calibration) — measurement blocks + calibration SA (seed+0x75fb)
  Phase 3: session 0x86 (coding)      — SA unlock (seed+0x2909) + measurement blocks
  Phase 4: session 0x85 (programming) — ReadMemoryByAddress sweep (SID 0x23)

Usage (32-bit python, module power-cycled to state A):
  session_probe.py                    # phases 1-3 (app sessions, one run)
  session_probe.py --phase 4          # phase 4 only (programming, needs fresh power-cycle)
  session_probe.py --phase all        # all phases (will need power-cycle between 3 and 4)
  session_probe.py --phase 1          # just session 0x89 baseline
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import LockedCAN, Stim, open_quiet, req_sid
from sa2_unlock import Sa2SeedKey, SA2_TAPE
from tp20_kwp import kfmt

SA_KEY_CODING = 0x2909
SA_KEY_CALIB  = 0x75fb


def probe_measurement_blocks(tp, session_name, block_range=range(0x01, 0x100)):
    """Sweep SID 0x21 ReadDataByLocalId across block IDs. Returns {block: response}."""
    print(f"\n  --- SID 0x21 ReadDataByLocalId sweep in {session_name} ---")
    results = {}
    positive = 0
    for blk in block_range:
        r = req_sid(tp, bytes([0x21, blk]), tries=2, timeout=1.5)
        tp.keepalive(force=True)
        if r and r[0] == 0x61:
            data = r[2:] if len(r) > 2 else b''
            print(f"    21 {blk:02X} -> POSITIVE [{r.hex(' ')}]")
            results[blk] = r
            positive += 1
        elif r and r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            results[blk] = r
        else:
            results[blk] = r

        if (blk & 0x3F) == 0x3F:
            print(f"    ... 0x{blk-0x3F:02X}-0x{blk:02X} done ({positive} positive so far)")

    print(f"  [{session_name}] SID 0x21: {positive} positive out of {len(block_range)} probed")
    return results


def probe_common_ids(tp, session_name):
    """Sweep SID 0x22 ReadDataByCommonId with selected DIDs."""
    print(f"\n  --- SID 0x22 ReadDataByCommonId in {session_name} ---")
    dids = [
        0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0010, 0x0020,
        0x0100, 0x0200, 0x0300, 0x0400, 0x0500,
        0xF100, 0xF17C, 0xF187, 0xF189, 0xF191, 0xF197, 0xF1A3, 0xF1AA, 0xF1DF,
    ]
    results = {}
    for did in dids:
        r = req_sid(tp, bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]), tries=2, timeout=1.5)
        tp.keepalive(force=True)
        if r and r[0] == 0x62:
            asc = bytes(b if 32 <= b < 127 else 46 for b in r[3:]).decode()
            print(f"    22 {did:04X} -> POSITIVE [{r.hex(' ')}]  {asc}")
        elif r and r[0] == 0x7F:
            nrc_val = r[2] if len(r) > 2 else 0
            NRC_NAMES = {0x11: "serviceNotSupported", 0x12: "subFnNotSupported",
                         0x31: "requestOutOfRange", 0x33: "securityAccessDenied"}
            print(f"    22 {did:04X} -> NRC {NRC_NAMES.get(nrc_val, hex(nrc_val))}")
        results[did] = r
    return results


def probe_services(tp, session_name):
    """Probe which SIDs are supported in this session."""
    print(f"\n  --- Service availability in {session_name} ---")
    probes = [
        (b'\x10\x89', "10 89 StartDiagSession(app)"),
        (b'\x12\x01', "12 01 ReadFreezeFrame"),
        (b'\x14\xff\x00', "14 FF00 ClearDTC"),
        (b'\x18\x02\xff\xff', "18 02FFFF ReadDTC"),
        (b'\x1a\x87', "1A 87 ReadEcuIdent(partNo)"),
        (b'\x1a\x91', "1A 91 ReadEcuIdent(hwNo)"),
        (b'\x21\x01', "21 01 ReadDataByLocalId"),
        (b'\x22\x00\x01', "22 0001 ReadDataByCommonId"),
        (b'\x23\x00\x01\x00\x10', "23 000100 10 ReadMemByAddr"),
        (b'\x27\x03', "27 03 SA seed request"),
        (b'\x2e\x00\x01\x00', "2E 0001 WriteDataByCommonId"),
        (b'\x30\x01', "30 01 IOControl(sub1)"),
        (b'\x30\x02', "30 02 IOControl(sub2)"),
        (b'\x31\x01', "31 01 RoutineControl(std)"),
        (b'\x31\xd0', "31 D0 RoutineControl(high)"),
        (b'\x32\x01', "32 01 StopRoutine"),
        (b'\x33\x01', "33 01 ReqRoutineResults"),
        (b'\x34\x01', "34 01 RequestDownload"),
        (b'\x35\x01', "35 01 RequestUpload"),
        (b'\x36\x01', "36 01 TransferData"),
        (b'\x37', "37 RequestTransferExit"),
        (b'\x3b\x01\x00', "3B 01 WriteDataByLocalId"),
        (b'\x3d\x00\x01\x00\x01\x00', "3D WriteMemByAddr"),
        (b'\x3e', "3E TesterPresent"),
    ]
    for kwp, label in probes:
        r = req_sid(tp, kwp, tries=2, timeout=1.5)
        tp.keepalive(force=True)
        status = "POSITIVE" if r and r[0] != 0x7F else kfmt(r)
        print(f"    {label:40s} -> {status}")


def try_sa_key(tp, key_constant, label):
    """Request SA seed (27 03) and send key = seed + constant (27 04)."""
    print(f"\n  --- SecurityAccess: {label} (key = seed + 0x{key_constant:04X}) ---")
    sr = req_sid(tp, b'\x27\x03', tries=3, timeout=2.0)
    tp.keepalive(force=True)
    print(f"    27 03 -> {kfmt(sr)}")
    if not sr or sr[0] != 0x67 or len(sr) < 6:
        if sr and sr[0] == 0x7F and len(sr) > 2 and sr[2] == 0x36:
            print(f"    [!] LOCKED OUT (0x36) — cannot attempt SA")
        return False

    seed = int.from_bytes(sr[2:6], 'big')
    key = (seed + key_constant) & 0xFFFFFFFF
    kb = key.to_bytes(4, 'big')
    print(f"    seed = 0x{seed:08X}  key = 0x{key:08X} ({kb.hex(' ')})")

    kr = req_sid(tp, b'\x27\x04' + kb, tries=1, timeout=2.0)
    tp.keepalive(force=True)
    print(f"    27 04 -> {kfmt(kr)}")

    if kr and kr[0] == 0x67:
        print(f"    *** {label} UNLOCKED ***")
        return True
    else:
        print(f"    [!] {label} key rejected")
        return False


def probe_sa_subfunctions(tp, session_name):
    """Probe which SA subfunctions (seed requests) are available."""
    print(f"\n  --- SA subfunctions in {session_name} ---")
    for sf in (0x01, 0x03, 0x05, 0x07, 0x09, 0x0b, 0x0d, 0x0f, 0x11, 0x13, 0x15, 0x19, 0x21, 0x41, 0x61):
        r = req_sid(tp, bytes([0x27, sf]), tries=2, timeout=1.5)
        tp.keepalive(force=True)
        if r and r[0] == 0x67 and len(r) >= 6:
            print(f"    27 {sf:02X} -> SEED {r[2:6].hex(' ')}")
        elif r and r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            nrc_names = {0x12: "subFnNotSupported", 0x22: "conditionsNotCorrect",
                         0x33: "securityAccessDenied", 0x36: "exceedAttempts"}
            print(f"    27 {sf:02X} -> NRC {nrc_names.get(nrc, hex(nrc))}")
        else:
            print(f"    27 {sf:02X} -> {kfmt(r)}")


def phase1_app_session(tp):
    """Phase 1: session 0x89 (application) baseline."""
    print("\n" + "=" * 70)
    print("PHASE 1: Session 0x89 (application) — baseline")
    print("=" * 70)

    r = req_sid(tp, b'\x10\x89')
    print(f"  10 89 -> {kfmt(r)}")
    if not (r and r[0] == 0x50):
        print("  [!] session 0x89 refused")
        return None

    probe_services(tp, "0x89")
    probe_sa_subfunctions(tp, "0x89")
    meas_89 = probe_measurement_blocks(tp, "0x89")
    probe_common_ids(tp, "0x89")
    return meas_89


def phase2_cal_session(tp, meas_89=None):
    """Phase 2: session 0x83 (calibration) — measurement + calibration SA."""
    print("\n" + "=" * 70)
    print("PHASE 2: Session 0x83 (calibration)")
    print("=" * 70)

    r = req_sid(tp, b'\x10\x83')
    print(f"  10 83 -> {kfmt(r)}")
    if not (r and r[0] == 0x50):
        print("  [!] session 0x83 refused")
        return None

    probe_services(tp, "0x83")
    probe_sa_subfunctions(tp, "0x83")
    meas_83 = probe_measurement_blocks(tp, "0x83")
    probe_common_ids(tp, "0x83")

    # Compare with 0x89 baseline
    if meas_89:
        diff_blocks = []
        new_blocks = []
        for blk in range(0x01, 0x100):
            r89 = meas_89.get(blk)
            r83 = meas_83.get(blk)
            pos89 = r89 and r89[0] == 0x61
            pos83 = r83 and r83[0] == 0x61
            if pos83 and not pos89:
                new_blocks.append(blk)
            elif pos83 and pos89 and r83 != r89:
                diff_blocks.append(blk)

        if new_blocks:
            print(f"\n  [*] Blocks available in 0x83 but NOT in 0x89: "
                  f"{[f'0x{b:02X}' for b in new_blocks]}")
        if diff_blocks:
            print(f"  [*] Blocks with DIFFERENT data in 0x83 vs 0x89: "
                  f"{[f'0x{b:02X}' for b in diff_blocks]}")
        if not new_blocks and not diff_blocks:
            print(f"\n  [*] No difference in SID 0x21 between 0x89 and 0x83")

    # Try calibration SA key
    try_sa_key(tp, SA_KEY_CALIB, "calibration SA (seed+0x75fb)")

    # After calibration SA, re-probe services to see if anything new opened
    print("\n  --- Re-probing after calibration SA ---")
    for kwp, label in [
        (b'\x21\x01', "21 01 ReadDataByLocalId"),
        (b'\x22\x00\x01', "22 0001 ReadDataByCommonId"),
        (b'\x2e\x00\x01\x00', "2E WriteDataByCommonId"),
        (b'\x23\x00\x01\x00\x10', "23 ReadMemByAddr"),
        (b'\x34\x01', "34 RequestDownload"),
        (b'\x31\xd0', "31 D0 RoutineControl(high)"),
    ]:
        r = req_sid(tp, kwp, tries=2, timeout=1.5)
        tp.keepalive(force=True)
        print(f"    {label:40s} -> {kfmt(r)}")

    return meas_83


def phase3_coding_session(tp, meas_89=None):
    """Phase 3: session 0x86 (coding) — needs SA unlock first."""
    print("\n" + "=" * 70)
    print("PHASE 3: Session 0x86 (coding)")
    print("=" * 70)

    # Must be in a base session first, then SA unlock, then 10 86
    r = req_sid(tp, b'\x10\x89')
    print(f"  10 89 (reset to app) -> {kfmt(r)}")

    # SA unlock for coding (seed+0x2909)
    ok = try_sa_key(tp, SA_KEY_CODING, "coding SA (seed+0x2909)")
    if not ok:
        print("  [!] coding SA failed — cannot enter session 0x86")
        return None

    r = req_sid(tp, b'\x10\x86')
    print(f"  10 86 -> {kfmt(r)}")
    if not (r and r[0] == 0x50):
        print("  [!] session 0x86 refused (SA bit not set or consumed?)")
        return None

    probe_services(tp, "0x86")
    meas_86 = probe_measurement_blocks(tp, "0x86")

    # Compare with 0x89
    if meas_89:
        new_blocks = []
        for blk in range(0x01, 0x100):
            r89 = meas_89.get(blk)
            r86 = meas_86.get(blk)
            pos89 = r89 and r89[0] == 0x61
            pos86 = r86 and r86[0] == 0x61
            if pos86 and not pos89:
                new_blocks.append(blk)
        if new_blocks:
            print(f"\n  [*] Blocks available in 0x86 but NOT in 0x89: "
                  f"{[f'0x{b:02X}' for b in new_blocks]}")

    return meas_86


def phase4_prog_session(dry_run=False):
    """Phase 4: session 0x85 (programming) — ReadMemoryByAddress sweep.
    Requires a fresh power-cycle (state A)."""
    print("\n" + "=" * 70)
    print("PHASE 4: Session 0x85 (programming) — ReadMemoryByAddress")
    print("=" * 70)

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

        r89 = req_sid(tp, b'\x10\x89')
        print(f"  10 89 -> {kfmt(r89)}")

        # Probe SID 0x23 in app session first (expect NRC)
        print("\n  --- SID 0x23 in app session (0x89) ---")
        r = req_sid(tp, bytes.fromhex('2300010010'), tries=2)
        tp.keepalive(force=True)
        print(f"    23 @000100 len=0x10 -> {kfmt(r)}")

        # Descend to programming session
        r85 = req_sid(tp, b'\x10\x85')
        print(f"\n  10 85 -> {kfmt(r85)}")
        if not (r85 and r85[0] == 0x50 and len(r85) > 1 and r85[1] == 0x85):
            print("  [!] programming session refused (need fresh power-cycle)")
            return

        # Try SID 0x23 on the same channel (before SBOOT handoff)
        print("\n  --- SID 0x23 on same channel (pre-SBOOT?) ---")
        for label, hx in [
            ("23 @000100 len=0x10", "2300010010"),
            ("23 @400000 len=0x10", "2340000010"),
        ]:
            r = req_sid(tp, bytes.fromhex(hx), tries=2, timeout=1.5)
            tp.keepalive(force=True)
            print(f"    {label:30s} -> {kfmt(r)}")

        # Reconnect for SBOOT
        stim.pause()
        time.sleep(0.3)
        tp.close()
        tp = open_quiet(c, stim, keep_quiet=True)
        if tp is None:
            for attempt in range(3):
                time.sleep(0.5)
                tp = open_quiet(c, stim, keep_quiet=True)
                if tp is not None:
                    break
                print(f"  [*] reconnect attempt {attempt + 2} ...")
        if tp is None:
            print("[!] TP2.0 reconnect failed after descent")
            return
        print(f"  [*] TP2.0 reconnected (SBOOT) TX->0x{tp.tx:03x} RX<-0x{tp.rx:03x}")

        # Probe SID 0x23 in SBOOT before SA
        print("\n  --- SID 0x23 in SBOOT (before SA) ---")
        for label, hx in [
            ("23 @000100 len=0x10", "2300010010"),
            ("23 @000100 len=0x04", "2300010004"),
        ]:
            r = req_sid(tp, bytes.fromhex(hx), tries=2, timeout=1.5)
            tp.keepalive(force=True)
            print(f"    {label:30s} -> {kfmt(r)}")

        # Flash SA unlock (SGO SA2)
        if dry_run:
            print("\n  [dry-run] skipping SA2 unlock — re-run with --unlock for full probe")
            return

        print("\n  --- Flash SA2 unlock ---")
        tp._drain()
        sr = tp.request(b'\x27\x01')
        print(f"    27 01 -> {kfmt(sr)}")
        if not sr or sr[0] != 0x67 or len(sr) < 6:
            if sr and sr[0] == 0x7F and len(sr) > 2 and sr[2] == 0x36:
                print("    [!] LOCKED OUT — wait for NVM timer")
            return

        seed = int.from_bytes(sr[2:6], 'big')
        key = Sa2SeedKey(SA2_TAPE, seed).execute()
        kb = key.to_bytes(4, 'big')
        kr = tp.request(b'\x27\x02' + kb, timeout=3.0)
        print(f"    seed = 0x{seed:08X}  SA2 key = 0x{key:08X}")
        print(f"    27 02 -> {kfmt(kr)}")

        if not (kr and kr[0] == 0x67):
            print("    [!] Flash SA2 rejected")
            return
        print("    *** FLASH SA UNLOCKED ***")

        # Now sweep ReadMemoryByAddress (SID 0x23)
        print("\n  --- SID 0x23 ReadMemoryByAddress sweep (after flash SA) ---")

        # Try different request formats
        print("\n  Format probing:")
        formats = [
            ("23 addr3=000100 len1=10",            "2300010010"),
            ("23 addr3=000100 len2=0010",           "230001000010"),
            ("23 addr4=00000100 len1=10",           "230000010010"),
            ("23 ALFID=14 addr4 len1",              "23140000010010"),
            ("23 ALFID=24 addr3 len2",              "23240001000010"),
            ("23 ALFID=22 addr2 len2",              "2322010010"),
            ("23 ALFID=44 addr4 len4",              "234400000100000010"),
            ("23 addr3=000000 len1=01",             "2300000001"),
        ]
        working_fmt = None
        for label, hx in formats:
            r = req_sid(tp, bytes.fromhex(hx), tries=3, timeout=2.0)
            tp.keepalive(force=True)
            tag = "POSITIVE" if r and r[0] == 0x63 else kfmt(r)
            print(f"    {label:38s} -> {tag}")
            if r and r[0] == 0x63 and working_fmt is None:
                working_fmt = hx
                try:
                    fwp = os.path.join(os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__))), "firmware", "8R0907379BG_0030.bin")
                    known = open(fwp, "rb").read()[0x100:0x110]
                    got = r[1:]
                    print(f"      known flash @0x100: {known.hex(' ')}")
                    print(f"      got response data:  {got.hex(' ')}")
                except Exception:
                    pass

        if working_fmt:
            print(f"\n  Working format found: {working_fmt}")
        else:
            print(f"\n  [!] No SID 0x23 format produced a positive response")
            # Also try SID 0x3D WriteMemoryByAddress to see format
            print("\n  --- SID 0x3D WriteMemoryByAddress format probe ---")
            for label, hx in [
                ("3D addr3=400000 len1=01 data=00", "3D40000001" + "00"),
                ("3D addr3=400000 len2=0001 data=00", "3D4000000001" + "00"),
            ]:
                r = req_sid(tp, bytes.fromhex(hx), tries=2, timeout=1.5)
                tp.keepalive(force=True)
                print(f"    {label:42s} -> {kfmt(r)}")
            return

        # Address range sweep using the working format
        print("\n  --- Address range sweep ---")
        # Build the read function based on the working format
        def read_mem(addr, length):
            """Build a SID 0x23 request and return the data or None."""
            # Use 3-byte addr + 1-byte length (the simplest format)
            kwp = bytes([0x23,
                         (addr >> 16) & 0xFF,
                         (addr >> 8) & 0xFF,
                         addr & 0xFF,
                         length & 0xFF])
            r = req_sid(tp, kwp, tries=2, timeout=2.0)
            tp.keepalive(force=True)
            if r and r[0] == 0x63:
                return r[1:]
            return None

        regions = [
            # Flash regions
            ("Flash start",       0x000000, 0x10),
            ("Flash @0x100",      0x000100, 0x10),
            ("Flash @0x1000",     0x001000, 0x10),
            ("Flash @0x10000",    0x010000, 0x10),
            ("Flash @0x40000",    0x040000, 0x10),
            ("Flash @0x80000",    0x080000, 0x10),
            ("Flash @0xC0000",    0x0C0000, 0x10),
            ("Flash end-16",      0x0FFFF0, 0x10),
            # SBOOT region (if separate)
            ("SBOOT? @0x100000",  0x100000, 0x10),
            ("SBOOT? @0x1FC000",  0x1FC000, 0x10),
            # RAM
            ("RAM start",         0x400000, 0x10),
            ("RAM @0x401000",     0x401000, 0x10),
            ("RAM @0x404000",     0x404000, 0x10),
            ("RAM @0x405316",     0x405310, 0x10),  # session flags area
            ("RAM @0x408000",     0x408000, 0x10),
            ("RAM @0x40B000",     0x40B000, 0x10),
            ("RAM @0x40BFFC",     0x40BFF0, 0x10),  # sec_unlock_marker
            ("RAM end-16",        0x40FFF0, 0x10),
            # Beyond RAM
            ("@0x410000",         0x410000, 0x10),
            ("@0x500000",         0x500000, 0x10),
            # Peripheral registers
            ("HECC1 mbox RAM",    0xFFF7E400, 0x10),
            ("HECC1 ctrl",        0xFFF7E800, 0x10),
            ("HECC2 mbox RAM",    0xFFF7E600, 0x10),
            ("HECC2 ctrl",        0xFFF7EA00, 0x10),
            ("SYS module",        0xFFFFFF00, 0x10),
            ("Flash ctrl (F035)", 0xFFE88000, 0x10),
        ]

        for label, addr, length in regions:
            # For addresses > 0xFFFF, need 4-byte address format
            if addr > 0xFFFFFF:
                kwp = bytes([0x23,
                             (addr >> 24) & 0xFF,
                             (addr >> 16) & 0xFF,
                             (addr >> 8) & 0xFF,
                             addr & 0xFF,
                             length & 0xFF])
            else:
                kwp = bytes([0x23,
                             (addr >> 16) & 0xFF,
                             (addr >> 8) & 0xFF,
                             addr & 0xFF,
                             length & 0xFF])
            r = req_sid(tp, kwp, tries=2, timeout=2.0)
            tp.keepalive(force=True)
            if r and r[0] == 0x63:
                data = r[1:]
                print(f"    {label:22s} @{addr:08X} -> OK  {data.hex(' ')}")
            else:
                print(f"    {label:22s} @{addr:08X} -> {kfmt(r)}")

        # Max transfer size probe
        print("\n  --- Max transfer size probe ---")
        for size in [0x10, 0x20, 0x40, 0x80, 0xFE, 0xFF]:
            kwp = bytes([0x23, 0x00, 0x01, 0x00, size])
            r = req_sid(tp, kwp, tries=2, timeout=3.0)
            tp.keepalive(force=True)
            if r and r[0] == 0x63:
                print(f"    len=0x{size:02X} ({size:3d} bytes) -> OK  ({len(r)-1} bytes returned)")
            else:
                print(f"    len=0x{size:02X} ({size:3d} bytes) -> {kfmt(r)}")

        # Also probe WriteMemoryByAddress (SID 0x3D) format — READ-ONLY probe
        print("\n  --- SID 0x3D WriteMemoryByAddress format probe ---")
        print("  (testing with harmless RAM write to scratch area)")
        # Read current value first, write same value back (idempotent)
        scratch_addr = 0x40FFF0  # end of RAM, likely unused
        rd = read_mem(scratch_addr, 1)
        if rd:
            print(f"    current @{scratch_addr:06X} = {rd.hex(' ')}")
            # Try writing the SAME byte back (idempotent)
            for label, hx in [
                ("3D addr3 len1 data", f"3D{scratch_addr:06X}01{rd[0]:02X}"),
                ("3D addr3+len data",  f"3D{scratch_addr:06X}{rd[0]:02X}"),
            ]:
                r = req_sid(tp, bytes.fromhex(hx), tries=2, timeout=2.0)
                tp.keepalive(force=True)
                print(f"    {label:30s} [{hx}] -> {kfmt(r)}")
        else:
            print(f"    cannot read scratch area @{scratch_addr:06X}")

    finally:
        if stim is not None:
            stim.stop = True
            stim.join(timeout=1.0)
        if tp is not None:
            try:
                tp.close()
            except Exception:
                pass
        c.close()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="1-3",
                    help="1|2|3|4|1-3|all (default: 1-3)")
    ap.add_argument("--unlock", action="store_true",
                    help="send SA keys (costs lockout attempts)")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="(default) skip flash SA in phase 4")
    args = ap.parse_args()

    if args.unlock:
        args.dry_run = False

    # Parse phases
    if args.phase == "all":
        phases = [1, 2, 3, 4]
    elif "-" in args.phase:
        lo, hi = args.phase.split("-")
        phases = list(range(int(lo), int(hi) + 1))
    else:
        phases = [int(args.phase)]

    print("[*] ESP8 session & service probe")
    print(f"    phases: {phases}")
    print(f"    SA keys: {'LIVE (--unlock)' if not args.dry_run else 'dry-run (add --unlock to send keys)'}")

    # Phases 1-3 share one TP2.0 session
    if any(p in phases for p in [1, 2, 3]):
        c = LockedCAN()
        stim = Stim(c, hz=50, ids=[0x200])
        stim.start()
        tp = None

        try:
            tp = open_quiet(c, stim)
            if tp is None:
                print("[!] TP2.0 open failed — is the module powered?")
                return
            print(f"[*] TP2.0 OPEN TX->0x{tp.tx:03x} RX<-0x{tp.rx:03x}")
            tp.maintain(2.0)

            meas_89 = None
            if 1 in phases:
                meas_89 = phase1_app_session(tp)
            if 2 in phases:
                phase2_cal_session(tp, meas_89)
            if 3 in phases:
                if not args.dry_run:
                    phase3_coding_session(tp, meas_89)
                else:
                    print("\n" + "=" * 70)
                    print("PHASE 3: Session 0x86 (coding) — SKIPPED (needs --unlock)")
                    print("=" * 70)

        finally:
            stim.stop = True
            stim.join(timeout=1.0)
            if tp:
                try:
                    tp.close()
                except Exception:
                    pass
            c.close()

    # Phase 4 needs its own power cycle and TP2.0 session
    if 4 in phases:
        if any(p in phases for p in [1, 2, 3]):
            print("\n[*] Phase 4 requires a fresh power-cycle.")
            print("    Power-cycle the module now, then press Enter.")
            input("    >>> ")
        phase4_prog_session(dry_run=args.dry_run)

    print("\n[*] Done.")


if __name__ == "__main__":
    main()
