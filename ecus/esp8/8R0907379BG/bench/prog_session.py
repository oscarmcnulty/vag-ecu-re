#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — ODIS-proven programming-session entry + memory dump via 0x23.

Replicates the exact sequence captured from a real ODIS flash session (2026-10-10,
captures/20a2-0001-20261010-153902.pcap):

    1.  1-msg stimulus (id 0x200, counter+CRC) to clear the operational gate
    2.  TP2.0 channel open (ABS logical addr 0x03)
    3.  10 89 StartDiagnosticSession (application)
    4.  10 85 StartDiagnosticSession (programming)  -> module descends to bootloader
    5.  TP2.0 reconnect (quiet bus — bootloader doesn't monitor restbus)
    6.  27 01 / 27 02 back-to-back SA2 unlock (SGO bytecode, BE/BE, ~40 ms gap)
    7.  23 ReadMemoryByAddress is now unlocked

SAFE BY DEFAULT: the --dry-run flag (default) does everything EXCEPT sending the SA key
(27 02), so it costs zero lockout attempts. --unlock sends the key (costs one attempt).
--read and --dump imply --unlock.

PREREQUISITE: the flash-SA lockout must be cleared. Check with fbl_check.py first; if
it shows 0x36 (exceedNumberOfAttempts), wait for the NVM time-delay to clear it.

Usage (32-bit python, module power-cycled to state A):
  prog_session.py                             # dry-run: full sequence, stop before key
  prog_session.py --unlock                    # send the SA2 key (uses one attempt)
  prog_session.py --read 0x000100 0x10        # unlock + read 16 bytes at 0x000100
  prog_session.py --dump 0x0 0x100 out.bin    # unlock + dump 256 bytes to file
  prog_session.py --dump 0x8000 0xB8000 asw.bin   # dump the full ASW (753664 bytes)
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import LockedCAN, Stim, open_quiet, req_sid
from sa2_unlock import Sa2SeedKey, SA2_TAPE
from tp20_kwp import kfmt


# ---------------------------------------------------------------------------
# KWP 0x23 ReadMemoryByAddress — layout variants to probe
# ---------------------------------------------------------------------------
# The KWP2000 spec allows several address/length encodings. The ESP8's table-B handler
# for SID 0x23 may expect a specific one. We try all plausible layouts against known
# flash content and use whichever returns a 0x63 positive response.

def _rmba_variants(addr, length):
    """Yield (label, KWP bytes) for each plausible ReadMemoryByAddress encoding."""
    # VAG KWP2000 most common: 23 <addr_hi> <addr_mid> <addr_lo> <len>  (3-byte addr, 1-byte len)
    if addr <= 0xFFFFFF and length <= 0xFF:
        yield ("addr3+len1",
               bytes([0x23]) + addr.to_bytes(3, 'big') + length.to_bytes(1, 'big'))
    # 3-byte addr, 2-byte len (for reads >255 bytes)
    if addr <= 0xFFFFFF:
        yield ("addr3+len2",
               bytes([0x23]) + addr.to_bytes(3, 'big') + length.to_bytes(2, 'big'))
    # 4-byte addr, 1-byte len
    if length <= 0xFF:
        yield ("addr4+len1",
               bytes([0x23]) + addr.to_bytes(4, 'big') + length.to_bytes(1, 'big'))
    # 4-byte addr, 2-byte len
    yield ("addr4+len2",
           bytes([0x23]) + addr.to_bytes(4, 'big') + length.to_bytes(2, 'big'))
    # With ALFID byte (addressAndLengthFormatIdentifier): 0x14 = 1-byte len + 4-byte addr,
    # 0x24 = 2-byte len + 4-byte addr, 0x13 = 1-byte len + 3-byte addr
    if addr <= 0xFFFFFF and length <= 0xFF:
        yield ("ALFID13+addr3+len1",
               bytes([0x23, 0x13]) + addr.to_bytes(3, 'big') + length.to_bytes(1, 'big'))
    if length <= 0xFF:
        yield ("ALFID14+addr4+len1",
               bytes([0x23, 0x14]) + addr.to_bytes(4, 'big') + length.to_bytes(1, 'big'))
    yield ("ALFID24+addr4+len2",
           bytes([0x23, 0x24]) + addr.to_bytes(4, 'big') + length.to_bytes(2, 'big'))


def _detect_rmba_layout(tp):
    """Probe ReadMemoryByAddress layout variants. Returns (label, builder_fn) or None."""
    print("  [*] probing 23 ReadMemoryByAddress layout variants ...")
    for label, kwp in _rmba_variants(0x000100, 0x04):
        r = req_sid(tp, kwp, tries=2, timeout=2.0)
        tp.keepalive(force=True)
        tag = kfmt(r)
        is_positive = r and r[0] == 0x63
        marker = " <<< POSITIVE" if is_positive else ""
        print(f"    {label:22s} [{kwp.hex()}] -> {tag[:60]}{marker}")
        if is_positive:
            return label
    return None


def _build_rmba(layout, addr, length):
    """Build a ReadMemoryByAddress request in the detected layout."""
    if layout == "addr3+len1":
        return bytes([0x23]) + addr.to_bytes(3, 'big') + length.to_bytes(1, 'big')
    elif layout == "addr3+len2":
        return bytes([0x23]) + addr.to_bytes(3, 'big') + length.to_bytes(2, 'big')
    elif layout == "addr4+len1":
        return bytes([0x23]) + addr.to_bytes(4, 'big') + length.to_bytes(1, 'big')
    elif layout == "addr4+len2":
        return bytes([0x23]) + addr.to_bytes(4, 'big') + length.to_bytes(2, 'big')
    elif layout == "ALFID13+addr3+len1":
        return bytes([0x23, 0x13]) + addr.to_bytes(3, 'big') + length.to_bytes(1, 'big')
    elif layout == "ALFID14+addr4+len1":
        return bytes([0x23, 0x14]) + addr.to_bytes(4, 'big') + length.to_bytes(1, 'big')
    elif layout == "ALFID24+addr4+len2":
        return bytes([0x23, 0x24]) + addr.to_bytes(4, 'big') + length.to_bytes(2, 'big')
    raise ValueError(f"unknown layout: {layout}")


def _max_read_len(layout):
    """Max single-read length for the layout's length field."""
    if "len1" in layout:
        return 0xFF
    return 0xFFFF   # len2 — but the ECU may cap it lower; we'll handle NRC 0x31


# ---------------------------------------------------------------------------
# Unlock sequence (ODIS-proven)
# ---------------------------------------------------------------------------

def do_unlock(args):
    """Full ODIS-style programming-session entry + SA2 unlock.
    Returns (tp, stim, can, layout) on success, or (None,...) on failure.
    The caller must clean up."""
    c = LockedCAN()
    stim = Stim(c, hz=50, ids=[0x200])
    stim.start()
    tp = None

    # ---- Phase 1: application session + descent to bootloader ----
    tp = open_quiet(c, stim)
    if tp is None:
        print("[!] TP2.0 open failed — is the ignition switch ON?")
        return None, stim, c, None

    print(f"[*] TP2.0 OPEN  TX->0x{tp.tx:03x}  RX<-0x{tp.rx:03x}")
    tp.maintain(2.0)  # let the module settle (stimulus running)

    r89 = req_sid(tp, bytes.fromhex('1089'))
    print(f"  10 89 (StartDiagnosticSession app) -> {kfmt(r89)}")
    if not (r89 and r89[0] == 0x50):
        print("  [!] session 89 refused")
        return None, stim, c, None

    r85 = req_sid(tp, bytes.fromhex('1085'))
    print(f"  10 85 (ProgrammingSession descent) -> {kfmt(r85)}")
    if not (r85 and r85[0] == 0x50 and len(r85) > 1 and r85[1] == 0x85):
        print("  [!] programming session refused (need fresh power-cycle to state A)")
        return None, stim, c, None

    # ---- Phase 2: TP2.0 reconnect (bus quiet for bootloader) ----
    # ODIS reconnects to logical addr 0x03 after 10 85. The channel IDs stay the same
    # (TX 0x4a3 / RX 0x300) but the old channel is dead after the bootloader descent.
    stim.resume()
    time.sleep(0.4)
    tp.close()
    tp = open_quiet(c, stim, keep_quiet=True)   # quiet bus — bootloader context
    if tp is None:
        # Retry a few times — the bootloader can take a moment
        for attempt in range(3):
            time.sleep(0.5)
            tp = open_quiet(c, stim, keep_quiet=True)
            if tp is not None:
                break
            print(f"  [*] reconnect attempt {attempt + 2} ...")
    if tp is None:
        print("[!] TP2.0 reconnect failed after descent")
        return None, stim, c, None

    print(f"  [*] TP2.0 reconnected (bootloader)  TX->0x{tp.tx:03x}  RX<-0x{tp.rx:03x}")

    # Confirm we're in the programming session
    r85b = req_sid(tp, bytes.fromhex('1085'))
    print(f"    10 85 (confirm) -> {kfmt(r85b)}")

    # ---- Phase 3: SecurityAccess — back-to-back 27 01 / 27 02 ----
    sr = tp.request(bytes.fromhex('2701'))   # 27 01 = request seed (level 1)
    print(f"    27 01 (request seed) -> {kfmt(sr)}")
    if not sr or sr[0] != 0x67 or len(sr) < 6:
        if sr and sr[0] == 0x7F and len(sr) > 2 and sr[2] == 0x36:
            print("    [!] LOCKED OUT (0x36 exceedNumberOfAttempts) — wait for NVM timer")
            print("        check with fbl_check.py before retrying")
        else:
            print("    [!] no seed returned")
        return None, stim, c, None

    seed_bytes = sr[2:6]
    seed = int.from_bytes(seed_bytes, 'big')
    key = Sa2SeedKey(SA2_TAPE, seed).execute()
    kb = key.to_bytes(4, 'big')
    print(f"      seed = 0x{seed:08X}  ({seed_bytes.hex(' ')})")
    print(f"      SA2  = 0x{key:08X}  ({kb.hex(' ')})  [SGO bytecode, BE/BE]")

    if args.dry_run:
        print(f"    [dry-run] would send: 27 02 {kb.hex(' ')}")
        print("    re-run with --unlock, --read, or --dump to actually send the key")
        return None, stim, c, None

    # CRITICAL: send 27 02 IMMEDIATELY after 27 01 — no intervening frame (~40 ms gap,
    # matching the ODIS capture). Any keepalive/channel-test between resets the state.
    print(f"    >>> SENDING 27 02 {kb.hex(' ')} (immediate, no keepalive)")
    kr = tp.request(bytes([0x27, 0x02]) + kb, timeout=3.0)
    print(f"    27 02 (send key) -> {kfmt(kr)}")

    if kr and kr[0] == 0x67:
        print("    *** FLASH SA UNLOCKED (67 02) — programming access granted ***")
    else:
        print("    [!] SA2 key rejected")
        if kr and kr[0] == 0x7F and len(kr) > 2:
            if kr[2] == 0x35:
                print("        invalidKey — possibly stale seed or lockout artifact")
            elif kr[2] == 0x36:
                print("        exceedNumberOfAttempts — NVM lockout escalated")
        return None, stim, c, None

    # ---- Phase 4: detect ReadMemoryByAddress layout ----
    layout = _detect_rmba_layout(tp)
    if layout:
        print(f"  [*] 23 ReadMemoryByAddress works — layout: {layout}")
    else:
        print("  [!] 23 ReadMemoryByAddress not responding (all layouts refused)")
        print("      the unlock succeeded; try manual probing with the TP channel")

    return tp, stim, c, layout


# ---------------------------------------------------------------------------
# Memory read / dump
# ---------------------------------------------------------------------------

def do_read(tp, layout, addr, length):
    """Read `length` bytes from `addr` using ReadMemoryByAddress (0x23).
    Returns bytes on success, None on failure. Handles chunking for large reads."""
    max_chunk = min(_max_read_len(layout), 0xF0)  # conservative first chunk
    result = bytearray()
    offset = 0

    while offset < length:
        chunk = min(max_chunk, length - offset)
        kwp = _build_rmba(layout, addr + offset, chunk)
        r = req_sid(tp, kwp, tries=3, timeout=3.0)
        tp.keepalive(force=True)

        if r is None:
            print(f"    [!] no response at 0x{addr + offset:06X} +0x{chunk:X}")
            return None

        if r[0] == 0x63:
            # Positive response: 63 [echoed-data...]
            data = r[1:]
            if len(data) < chunk:
                print(f"    [!] short read at 0x{addr + offset:06X}: "
                      f"got {len(data)}, expected {chunk}")
            result.extend(data[:chunk])
            offset += len(data[:chunk])
        elif r[0] == 0x7F:
            nrc = r[2] if len(r) > 2 else 0
            if nrc == 0x31 and chunk > 0x10:
                # requestOutOfRange — try smaller chunks
                max_chunk = max(chunk // 2, 0x10)
                print(f"    [*] requestOutOfRange at chunk 0x{chunk:X}, "
                      f"reducing to 0x{max_chunk:X}")
                continue
            print(f"    [!] 7F at 0x{addr + offset:06X}: {kfmt(r)}")
            return None
        else:
            print(f"    [!] unexpected response at 0x{addr + offset:06X}: {kfmt(r)}")
            return None

    return bytes(result)


def do_dump(tp, layout, addr, length, outfile, verify_path=None):
    """Dump `length` bytes starting at `addr` to `outfile`, with progress."""
    print(f"  [*] dumping 0x{addr:06X} .. 0x{addr + length - 1:06X} "
          f"({length} bytes, {length / 1024:.1f} KB) -> {outfile}")

    max_chunk = min(_max_read_len(layout), 0xF0)
    # Probe with a small read first to find the real max chunk size
    test = _build_rmba(layout, addr, min(max_chunk, length))
    tr = req_sid(tp, test, tries=2, timeout=3.0)
    tp.keepalive(force=True)
    if tr and tr[0] == 0x7F and len(tr) > 2 and tr[2] == 0x31:
        # requestOutOfRange — binary-search for the max accepted chunk
        lo, hi = 0x04, max_chunk
        while lo < hi:
            mid = (lo + hi + 1) // 2
            t2 = _build_rmba(layout, addr, mid)
            r2 = req_sid(tp, t2, tries=1, timeout=2.0)
            tp.keepalive(force=True)
            if r2 and r2[0] == 0x63:
                lo = mid
            else:
                hi = mid - 1
        max_chunk = lo
        print(f"    [*] max accepted chunk size: 0x{max_chunk:X} ({max_chunk} bytes)")

    total = 0
    mismatches = 0
    t0 = time.time()

    # Load reference firmware for verification if available
    ref_data = None
    if verify_path:
        try:
            with open(verify_path, "rb") as f:
                ref_data = f.read()
            print(f"    [*] verification: comparing against {os.path.basename(verify_path)}")
        except FileNotFoundError:
            pass

    with open(outfile, "wb") as f:
        while total < length:
            chunk = min(max_chunk, length - total)
            kwp = _build_rmba(layout, addr + total, chunk)
            r = req_sid(tp, kwp, tries=4, timeout=3.0)
            tp.keepalive(force=True)

            if r is None or r[0] != 0x63:
                print(f"\n    [!] read failed at 0x{addr + total:06X}: {kfmt(r)}")
                elapsed = time.time() - t0
                print(f"    dumped {total} of {length} bytes ({total * 100 / length:.1f}%) "
                      f"in {elapsed:.1f}s before failure")
                return False

            data = r[1:]
            if len(data) < chunk:
                print(f"\n    [!] short read at 0x{addr + total:06X}: "
                      f"got {len(data)}, expected {chunk}")
                chunk = len(data)

            f.write(data[:chunk])

            # Verify against reference if available
            if ref_data and addr + total < len(ref_data):
                ref_chunk = ref_data[addr + total:addr + total + chunk]
                if data[:chunk] != ref_chunk:
                    mismatches += 1
                    if mismatches <= 3:
                        print(f"\n    [!] MISMATCH at 0x{addr + total:06X}: "
                              f"read {data[:min(8, chunk)].hex(' ')} "
                              f"vs ref {ref_chunk[:min(8, chunk)].hex(' ')}")

            total += chunk

            # Progress (every ~4 KB or on last chunk)
            if total % (max_chunk * 16) < max_chunk or total >= length:
                elapsed = time.time() - t0
                rate = total / elapsed if elapsed > 0 else 0
                pct = total * 100.0 / length
                eta = (length - total) / rate if rate > 0 else 0
                print(f"\r    0x{addr + total - 1:06X}  {total:>8d}/{length}  "
                      f"{pct:5.1f}%  {rate / 1024:.1f} KB/s  "
                      f"ETA {eta:.0f}s   ", end="", flush=True)

    elapsed = time.time() - t0
    rate = total / elapsed if elapsed > 0 else 0
    print(f"\n  [*] DONE: {total} bytes in {elapsed:.1f}s ({rate / 1024:.1f} KB/s) -> {outfile}")
    if ref_data and mismatches == 0 and total > 0:
        print("    verification: all bytes match reference firmware")
    elif mismatches > 0:
        print(f"    verification: {mismatches} mismatched chunks (may indicate RAM vs flash)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # Action modes (mutually exclusive)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="(default) full sequence except sending the SA key")
    mode.add_argument("--unlock", action="store_true",
                      help="send the SA2 key (uses one lockout attempt)")
    mode.add_argument("--read", nargs=2, metavar=("ADDR", "LEN"),
                      help="unlock + read LEN bytes at ADDR (hex, e.g. 0x000100 0x10)")
    mode.add_argument("--dump", nargs=3, metavar=("ADDR", "LEN", "FILE"),
                      help="unlock + dump LEN bytes at ADDR to FILE")

    # Options
    ap.add_argument("--verify", metavar="FW_BIN",
                    help="reference firmware .bin for dump verification")
    ap.add_argument("--layout", default=None,
                    help="force a specific 23 layout (skip auto-detect)")

    a = ap.parse_args()

    # If --read or --dump or --unlock given, we're not dry-run
    if a.unlock or a.read or a.dump:
        a.dry_run = False

    tp, stim, can, layout = None, None, None, None
    try:
        tp, stim, can, layout = do_unlock(a)

        if a.dry_run:
            return   # cleanup in finally

        if tp is None:
            print("[!] unlock failed; cannot proceed")
            return

        if a.layout:
            layout = a.layout
            print(f"  [*] using forced layout: {layout}")

        if layout is None:
            print("[!] no working ReadMemoryByAddress layout found")
            print("    the SA unlock succeeded — the channel is still open")
            print("    try manual 23 probing via tp20_kwp.py or extend the layout list")
            return

        if a.read:
            addr = int(a.read[0], 0)
            length = int(a.read[1], 0)
            print(f"\n  [*] reading 0x{addr:06X} +0x{length:X} ...")
            data = do_read(tp, layout, addr, length)
            if data:
                print(f"  [*] {len(data)} bytes:")
                # Hex + ASCII dump
                for off in range(0, len(data), 16):
                    chunk = data[off:off + 16]
                    hexs = " ".join(f"{b:02x}" for b in chunk)
                    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                    print(f"    {addr + off:06X}: {hexs:<48s}  {asc}")

        elif a.dump:
            addr = int(a.dump[0], 0)
            length = int(a.dump[1], 0)
            outfile = a.dump[2]
            do_dump(tp, layout, addr, length, outfile, verify_path=a.verify)

        elif a.unlock:
            # Just unlock — show that we're in and probe a few known addresses
            print("\n  [*] programming access confirmed; reading a few known addresses ...")
            for label, addr, length in [
                ("flash@0x000000 (reset vector)", 0x000000, 0x10),
                ("flash@0x000100", 0x000100, 0x10),
                ("flash@0x008000 (ASW start)", 0x008000, 0x10),
                ("RAM@0x400000", 0x400000, 0x10),
            ]:
                data = do_read(tp, layout, addr, length)
                if data:
                    print(f"    {label}: {data.hex(' ')}")
                else:
                    print(f"    {label}: FAILED")

    finally:
        if stim is not None:
            stim.stop = True
            stim.join(timeout=1.0)
        if tp is not None:
            try:
                tp.close()
            except Exception:
                pass
        if can is not None:
            can.close()


if __name__ == "__main__":
    main()
