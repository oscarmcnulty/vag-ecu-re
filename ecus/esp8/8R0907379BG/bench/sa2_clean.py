#!/usr/bin/env python3
"""Minimal SA2 unlock — stim on non-0x200 ID to avoid polluting TP2.0 setup channel.

Hypothesis: sending stim frames on CAN 0x200 (the TP2.0 setup address) confuses the
bootloader's TP2.0/SA state. ODIS wouldn't do this.

This script:
  1. Stim on 0x001 (accepted ID, NOT the TP2.0 setup address 0x200)
  2. Open channel, 10 89, 10 85 (descent)
  3. Keep stim running during descent (needed to maintain operational state)
  4. Reconnect, confirm 10 85, then 27 01 / 27 02 back-to-back
  5. Stop stim before the SA exchange (quiet bus for the critical pair)

Usage (32-bit python, module power-cycled):  sa2_clean.py [--stim-id 0xHEX]
"""
import argparse, os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, crc8_j1850
from tp20_kwp import TP20KWP, kfmt
from sa2_unlock import Sa2SeedKey, SA2_TAPE


class LockedCAN(RawCAN):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._lk = threading.Lock()
    def read(self, t=100):
        with self._lk: return super().read(t)
    def write(self, cid, pl):
        with self._lk: return super().write(cid, pl)


class Stim(threading.Thread):
    def __init__(self, can, hz=50, ids=None):
        super().__init__(daemon=True)
        self.c = can; self._period = 1.0 / hz
        self.ids = list(ids) if ids else [0x001]
        self.stop = False; self.paused = True; self.ctr = 0
    def run(self):
        while not self.stop:
            if self.paused:
                time.sleep(0.005); continue
            t = time.time(); self.ctr = (self.ctr + 1) & 0xFF
            gen = bytes([0, 0, 0, 0, 0, 0x08, self.ctr])
            frame = gen + bytes([crc8_j1850(gen)])
            for cid in self.ids:
                if self.paused or self.stop: break
                self.c.write(cid, frame)
            end = t + self._period
            while time.time() < end and not self.stop and not self.paused:
                time.sleep(0.003)
    def pause(self):
        self.paused = True; time.sleep(0.02)
    def resume(self):
        self.paused = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stim-id", default="0x001",
                    help="CAN ID for operational stimulus (default 0x001, NOT 0x200)")
    ap.add_argument("--with-10-85", action="store_true", default=True,
                    help="send 10 85 after reconnect (like fbl_check.py)")
    ap.add_argument("--skip-10-85", action="store_true",
                    help="skip 10 85 after reconnect (like ODIS capture)")
    a = ap.parse_args()
    stim_id = int(a.stim_id, 0)
    send_1085_after = not a.skip_10_85

    c = LockedCAN()
    stim = Stim(c, hz=50, ids=[stim_id])
    stim.start()
    print(f"[*] stim on CAN 0x{stim_id:03X} @ 50 Hz (NOT 0x200)")

    tp = None
    try:
        # --- Phase 1: open channel with stim paused (quiet for TP2.0 handshake) ---
        stim.pause()
        tp = TP20KWP(c)
        if not tp.open():
            print("[!] TP2.0 open failed"); return
        stim.resume()
        print(f"[*] OPEN  TX->0x{tp.tx:03x} RX<-0x{tp.rx:03x}")
        tp.maintain(1.5)

        r89 = tp.request(bytes.fromhex('1089'))
        print(f"  10 89 -> {kfmt(r89)}")

        if r89 and r89[0] == 0x50:
            # ASW state A — normal descent path
            tp.keepalive(force=True)
            r85 = tp.request(bytes.fromhex('1085'))
            print(f"  10 85 -> {kfmt(r85)}")
            if not (r85 and r85[0] == 0x50 and len(r85) > 1 and r85[1] == 0x85):
                print("  [!] programming session refused"); return
            time.sleep(0.4)
            tp.close()
            stim.pause()
            tp = TP20KWP(c)
            if not tp.open(timeout=3.0):
                time.sleep(0.5)
                tp = TP20KWP(c)
                if not tp.open(timeout=3.0):
                    print("[!] reconnect failed"); return
            print(f"  [*] reconnected  TX->0x{tp.tx:03x} RX<-0x{tp.rx:03x}")
        elif r89 and r89[0] == 0x7F and len(r89) > 2 and r89[2] == 0x12:
            # subFnNotSupported — already in bootloader (state B)
            print("  [*] already in bootloader — skipping descent")
            stim.pause()
        else:
            print("  [!] unexpected response"); return

        # --- Phase 2: SA exchange on quiet bus ---
        tp._drain()

        sr = tp.request(bytes.fromhex('2701'), timeout=3.0)
        print(f"    27 01 -> {kfmt(sr)}")
        if not sr or sr[0] != 0x67 or len(sr) < 6:
            if sr and sr[0] == 0x7F and len(sr) > 2:
                if sr[2] == 0x36:
                    print("    [!] LOCKED OUT (0x36)")
                elif sr[2] == 0x12:
                    print("    [!] subFnNotSupported — not in bootloader context")
            return

        seed = int.from_bytes(sr[2:6], 'big')
        key = Sa2SeedKey(SA2_TAPE, seed).execute()
        kb = key.to_bytes(4, 'big')

        # IMMEDIATE send — pre-computed, nothing between 27 01 and 27 02
        kr = tp.request(bytes([0x27, 0x02]) + kb, timeout=3.0)

        print(f"      seed = 0x{seed:08X}  ({sr[2:6].hex(' ')})")
        print(f"      SA2  = 0x{key:08X}  ({kb.hex(' ')})")
        print(f"    27 02 -> {kfmt(kr)}")

        if kr and kr[0] == 0x67:
            print("    *** FLASH SA UNLOCKED ***")

            # --- try 10 85 in bootloader ---
            print("\n  [*] trying 10 85 in bootloader ...")
            r1085 = tp.request(bytes.fromhex('1085'), timeout=2.0)
            print(f"    10 85 -> {kfmt(r1085)}")
            tp.keepalive(force=True)

            # --- 22 with 2-byte DIDs ---
            print("\n  [*] probing 22 with 2-byte DIDs ...")
            for did, label in [
                (0xF186, "activeSession"), (0xF187, "sparePartNo"),
                (0xF189, "swVersion"), (0xF190, "VIN"),
                (0xF191, "hwNumber"), (0xF1A2, "swCalId"),
                (0x0100, "generic"), (0xFD01, "FD01"),
                (0xF1DF, "progPreCond"), (0x0405, "0405"),
            ]:
                r = tp.request(bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]), timeout=1.0)
                tp.keepalive(force=True)
                if r is None: continue
                tag = kfmt(r)
                if r[0] == 0x62:
                    tag = f"POSITIVE [{r[:24].hex(' ')}]"
                print(f"    22 {did:04X} ({label:14s}) -> {tag}")

            # --- 34 RequestDownload (pcap: 34 00 80 00 00 + 3 bytes, len=8) ---
            print("\n  [*] probing 34 RequestDownload ...")
            for label, hx in [
                ("fmt00 a3 @800000 sz0100",   "3400 800000 000100"),
                ("fmt00 a4 @80000000 sz0100",  "3400 80000000 0100"),
                ("fmt00 a4 @80000000 sz000100","3400 80000000 000100"),
                ("fmt00 a3 @A00000 sz0100",   "3400 A00000 000100"),
                ("bare @800000",               "3400 800000"),
                ("noFmt a3 @800000 sz0100",   "34 800000 000100"),
                ("fmt44 UDS @80000000 sz0100", "340044 80000000 000100"),
            ]:
                r = tp.request(bytes.fromhex(hx.replace(' ','')), timeout=2.0)
                tp.keepalive(force=True)
                tag = kfmt(r)
                if r and r[0] == 0x74:
                    tag = f"POSITIVE [{r.hex(' ')}]"
                print(f"    {label:36s} -> {tag}")

            # --- retry 23/35 after 10 85 ---
            print("\n  [*] retrying 23/35 after 10 85 ...")
            for label, hx in [
                ("23 addr3+len1 @800000",     "23800000 10"),
                ("23 addr4+len1 @80000000",   "2380000000 10"),
                ("35 fmt00 a3 @800000 sz0100","3500 800000 000100"),
                ("35 fmt00 a4 @80000000 sz01","3500 80000000 0100"),
            ]:
                r = tp.request(bytes.fromhex(hx.replace(' ','')), timeout=2.0)
                tp.keepalive(force=True)
                tag = kfmt(r)
                if r and r[0] in (0x63, 0x75):
                    tag = f"POSITIVE [{r.hex(' ')}]"
                print(f"    {label:36s} -> {tag}")

            # --- scan more 2-byte DIDs ---
            print("\n  [*] scanning 2-byte DIDs F100-F1FF ...")
            for did in range(0xF100, 0xF200):
                r = tp.request(bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]), timeout=0.5)
                tp.keepalive(force=True)
                if r is None: continue
                if r[0] == 0x7F and len(r) > 2 and r[2] in (0x31, 0x90):
                    continue
                tag = kfmt(r)
                if r[0] == 0x62:
                    asc = bytes(b if 32 <= b < 127 else 46 for b in r[3:]).decode()
                    tag = f"[{r[3:].hex(' ')}] = {asc}"
                print(f"    22 {did:04X} -> {tag}")
        else:
            print("    [!] SA2 key rejected")

    finally:
        stim.stop = True; stim.join(timeout=1.0)
        try: tp.close()
        except: pass
        c.close()


if __name__ == "__main__":
    main()
