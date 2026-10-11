#!/usr/bin/env python3
"""ESP8 (8R0907379BG) — ODIS-proven programming-session entry + flash SA2 unlock.

Replicates the exact sequence captured from a real ODIS flash session (2026-10-10,
F:\\data\\20a2-0001-20261010-153902.pcap):

    1.  1-msg stimulus (any accepted CAN ID) to clear the operational gate
    2.  TP2.0 channel open (ABS logical addr 0x03)
    3.  10 89 StartDiagnosticSession (application)
    4.  10 85 StartDiagnosticSession (programming)  -> module descends to SBOOT
    5.  TP2.0 reconnect (bus quiet for handshake)
    6.  27 01 / 27 02 SA2 unlock (SGO bytecode, BE/BE)
    7.  Bootloader access: 10/22/27/31/33/34/36/37 available

CRITICAL: TP2.0 multi-frame sends MUST use op=2 (more, NO ACK) for non-last frames,
matching ODIS. Using op=0 (ACK expected) inserts an ACK round-trip that breaks the
SBOOT's SA state machine. Fixed in tp20_kwp.py _send_frames().

NOTE: SID 0x23 (ReadMemoryByAddress) is NOT supported in the bootloader (NRC 0x90).
SID 0x35 (RequestUpload) is also not supported. Memory dump requires a different path
(ASW-side with coding SA, or RequestDownload/TransferData for flash content).

SAFE BY DEFAULT: the --dry-run flag (default) does everything EXCEPT sending the SA key
(27 02), so it costs zero lockout attempts. --unlock sends the key (costs one attempt).

PREREQUISITE: the flash-SA lockout must be cleared. Check with fbl_check.py first; if
it shows 0x36 (exceedNumberOfAttempts), wait for the NVM time-delay to clear it.

Usage (32-bit python, module power-cycled to state A):
  prog_session.py                        # dry-run: full sequence, stop before key
  prog_session.py --unlock               # send the SA2 key + read bootloader DIDs
  prog_session.py --identify             # unlock + read all bootloader DIDs
"""
import argparse
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emu_unlock import LockedCAN, Stim, open_quiet, req_sid
from sa2_unlock import Sa2SeedKey, SA2_TAPE
from tp20_kwp import kfmt


# ---------------------------------------------------------------------------
# Bootloader identification (SID 0x22 with 2-byte DIDs)
# ---------------------------------------------------------------------------

BOOT_DIDS = [
    (0xF17C, "bootloaderVersion"),
    (0xF17E, "bootloaderFingerprint"),
    (0xF184, "flashStatus"),
    (0xF187, "sparePartNo"),
    (0xF189, "swVersion"),
    (0xF18C, "swSerial"),
    (0xF191, "hwNumber"),
    (0xF197, "systemName"),
    (0xF1A3, "hwVersion"),
    (0xF1A5, "progDate"),
    (0xF1A6, "progCounter"),
    (0xF1AA, "moduleDesignation"),
    (0xF1DF, "progPreconditions"),
    (0x0405, "status0405"),
]


def read_boot_dids(tp):
    """Read all known bootloader DIDs. Returns dict {did: bytes}."""
    results = {}
    for did, label in BOOT_DIDS:
        r = req_sid(tp, bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]),
                    tries=2, timeout=1.0)
        tp.keepalive(force=True)
        if r and r[0] == 0x62 and len(r) > 3:
            data = r[3:]
            asc = bytes(b if 32 <= b < 127 else 46 for b in data).decode()
            print(f"    {did:04X} {label:22s} = {data.hex(' ')}  {asc}")
            results[did] = data
    return results


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

    # NOTE: ODIS does NOT send 10 85 again after reconnect — it goes straight to 27 01.
    # Sending 10 85 here may reset SBOOT SA state. Match ODIS exactly.

    # ---- Phase 3: SecurityAccess — back-to-back 27 01 / 27 02 ----
    # Drain any stale frames before the critical pair
    tp._drain()
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

    if args.dry_run:
        print(f"      seed = 0x{seed:08X}  ({seed_bytes.hex(' ')})")
        print(f"      SA2  = 0x{key:08X}  ({kb.hex(' ')})  [SGO bytecode, BE/BE]")
        print(f"    [dry-run] would send: 27 02 {kb.hex(' ')}")
        print("    re-run with --unlock, --read, or --dump to actually send the key")
        return None, stim, c, None

    # CRITICAL: send 27 02 IMMEDIATELY after 27 01 — no intervening frame (~40 ms gap,
    # matching the ODIS capture). Compute the key BEFORE printing so the send is instant.
    kr = tp.request(bytes([0x27, 0x02]) + kb, timeout=3.0)
    # Now safe to print
    print(f"      seed = 0x{seed:08X}  ({seed_bytes.hex(' ')})")
    print(f"      SA2  = 0x{key:08X}  ({kb.hex(' ')})  [SGO bytecode, BE/BE]")
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

    return tp, stim, c




# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="(default) full sequence except sending the SA key")
    mode.add_argument("--unlock", action="store_true",
                      help="send the SA2 key (uses one lockout attempt)")
    mode.add_argument("--identify", action="store_true",
                      help="unlock + read all bootloader identification DIDs")

    a = ap.parse_args()

    if a.unlock or a.identify:
        a.dry_run = False

    tp, stim, can = None, None, None
    try:
        tp, stim, can = do_unlock(a)

        if a.dry_run:
            return

        if tp is None:
            print("[!] unlock failed; cannot proceed")
            return

        if a.unlock or a.identify:
            print("\n  [*] reading bootloader identification DIDs ...")
            read_boot_dids(tp)

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
