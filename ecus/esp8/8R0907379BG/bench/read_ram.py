#!/usr/bin/env python3
"""ESP8 (8R0907379BG) live-RAM reader over UDS ReadMemoryByAddress (svc 0x23).

WHY: cold software materialization of the COM object table (0x40a1a8) is provably
blocked on the one SBOOT-installed config-source pointer (the config-graph iterator is
RAM-dispatched with no static caller; see analysis note in FUN_000a1cac / docs/
operational_gate_trace.md). But the table IS built in the live, powered ECU's RAM.
Reading it back over UDS lets us SEED the emulator with the real materialized tables
(object table + transport channel struct + dispatch pointers) so the reassembler can be
run — i.e. it materializes the RAM for the emulation path.

This tool:
  1) proves liveness (TesterPresent) and identity (F187),
  2) probes ReadMemoryByAddress (0x23) in default -> extended (-> optional programming)
     session with several addressAndLengthFormatIdentifier layouts on a scratch address,
  3) on success, dumps the RAM regions that matter into emu/ramdump_*.bin (one file per
     region) plus a manifest, ready for harness.py to map.

Read-only w.r.t. ECU memory (0x23 is a read; 0x10 0x03 extended session is reversible and
restored on exit). ReadMemoryByAddress is frequently gated (NRC 0x33 securityAccess /
0x31 requestOutOfRange / 0x7F serviceNotSupported) — a clean negative is itself the
answer (records which sessions/ranges the ECU permits).

Run with the 32-bit Python that loads smj2534.dll:
  <py311x86>\python.exe ecus/esp8/8R0907379BG/bench/read_ram.py
  <py311x86>\python.exe .../read_ram.py --programming-session   # if extended is denied
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "core", "uds"))
from j2534_transport import J2534IsoTpTransport  # noqa: E402
from uds_client import UDS, NegativeResponse     # noqa: E402

DEFAULT_DLL = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
OUT = os.path.join(os.path.dirname(__file__), "..", "emu")

# RAM regions to capture (name, addr, length) — the materialized COM/transport state.
REGIONS = [
    ("objtable",   0x0040a1a8, 0x4000),   # COM runtime object table (handle->descriptors->bufs)
    ("transport",  0x00407990, 0x0080),   # transport channel struct (PCI@+0x34=0x4079d4, status@+0x44)
    ("nm_state",   0x00408f00, 0x0040),   # NM status word 0x408f10 + net-active flags 0x408f20/21
    ("enable",     0x00409220, 0x0040),   # comm_netmode 0x409230
    ("enflag",     0x00409430, 0x0060),   # comm_enable_flag 0x40944c, tx_gate2 0x409438, nm_mode 0x4090d8-ish
    ("nm_mode",    0x004090c0, 0x0040),   # nm_mode 0x4090d8, 0x4090d0 struct
    ("sig047b",    0x00408f00, 0x0020),   # com_sig_047b 0x408f0c (overlaps nm_state; fine)
    ("mbstatus",   0x00406cc0, 0x0060),   # per-mailbox status desc 0x406cd0 + CAN status 0x406dd0/406dc8
    ("cfg_cursor", 0x00406960, 0x0080),   # config walker cursor/flags 0x406980, 0x4069xx
]

# addressAndLengthFormatIdentifier layouts to probe: (addr_len, size_len)
ALFID_TRY = [(4, 4), (4, 2), (4, 1), (3, 1), (2, 1)]


def try_read(uds, addr, size, alfids):
    for al, sl in alfids:
        try:
            data = uds.read_memory(addr, size, addr_len=al, size_len=sl)
            return data, (al, sl)
        except NegativeResponse as e:
            last = str(e)
        except Exception as e:
            last = repr(e)
    return None, last


def dump_region(uds, name, addr, length, alfid, chunk):
    buf = bytearray()
    a = addr
    while a < addr + length:
        n = min(chunk, addr + length - a)
        data, _ = try_read(uds, a, n, [alfid])
        if data is None:
            print(f"  [{name}] stopped at 0x{a:08x} (+0x{a-addr:x}) — {n}B read denied")
            break
        buf += data
        a += n
    path = os.path.join(OUT, f"ramdump_{name}_{addr:08x}.bin")
    if buf:
        with open(path, "wb") as f:
            f.write(buf)
        print(f"  [{name}] 0x{addr:08x} +0x{len(buf):x} -> {os.path.basename(path)}")
    return bytes(buf), addr


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=DEFAULT_DLL)
    ap.add_argument("--tx", type=lambda s: int(s, 0), default=0x713)
    ap.add_argument("--rx", type=lambda s: int(s, 0), default=0x77D)
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--timeout", type=int, default=1000)
    ap.add_argument("--chunk", type=lambda s: int(s, 0), default=0x40)
    ap.add_argument("--programming-session", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    with J2534IsoTpTransport(a.dll, a.tx, a.rx, a.baud, timeout_ms=a.timeout) as t:
        uds = UDS(t)
        try:
            print("[*] TesterPresent:", t.request(b"\x3e\x00").hex(" "))
        except Exception as e:
            print("[!] TesterPresent failed:", e); return
        try:
            print("[*] F187 part no:", uds.read_did(0xF187).hex(" "))
        except Exception as e:
            print("[!] F187 read failed:", e)

        # Probe 0x23 across sessions. Scratch probe addr = objtable base, 16 bytes.
        sessions = [("default", None), ("extended", 0x03)]
        if a.programming_session:
            sessions.append(("programming", 0x02))
        alfid = None
        for sname, lvl in sessions:
            if lvl is not None:
                try:
                    print(f"[*] session {sname}:", uds.session(lvl).hex(" "))
                except Exception as e:
                    print(f"[!] session {sname} refused:", e); continue
            data, info = try_read(uds, 0x0040a1a8, 0x10, ALFID_TRY)
            if data is not None:
                alfid = info
                print(f"[OK] ReadMemoryByAddress works in {sname} session, "
                      f"alfid=addr{alfid[0]}/size{alfid[1]}")
                print(f"     sample @0x40a1a8: {data.hex(' ')}")
                break
            else:
                print(f"[--] 0x23 denied in {sname} session: {info}")
        if alfid is None:
            print("\nRESULT: ReadMemoryByAddress not permitted in tried sessions. "
                  "Next: security access (need seed/key), or use the flash bootloader "
                  "read path. The materialized table cannot be pulled via 0x23 here.")
            return

        print("\n[*] dumping RAM regions:")
        manifest = []
        for name, addr, length in REGIONS:
            buf, base = dump_region(uds, name, addr, length, alfid, a.chunk)
            if buf:
                manifest.append((name, base, len(buf)))
        mpath = os.path.join(OUT, "ramdump_manifest.txt")
        with open(mpath, "w") as f:
            f.write("# name,addr,len — live ESP8 RAM snapshot via UDS 0x23\n")
            for name, base, ln in manifest:
                f.write(f"{name},0x{base:08x},0x{ln:x}\n")
        print(f"\n[OK] wrote {len(manifest)} regions + manifest {os.path.basename(mpath)}")
        print("Seed harness.py from these to run the reassembler with real dispatch tables.")


if __name__ == "__main__":
    main()
