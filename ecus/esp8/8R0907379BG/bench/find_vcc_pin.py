#!/usr/bin/env python3
"""Identify which Scanmatik FEPS pin drives the module's VCC+/term-15 — using the MODULE as detector.

No multimeter: the module sleeps within seconds once CAN stimulus stops (observed term15-OFF behavior).
If a FEPS pin actually feeds VCC+/term-15, then with that pin energized the module should STAY awake
(keep broadcasting) after we stop the NM wake stimulus; with any other pin it sleeps. The pin that
keeps it broadcasting in the final seconds of a passive window = the VCC+ pin (and confirms term15
gates the ECU). We also probe UDS while each pin is energized — a reply is the jackpot.

One shared J2534 device drives both the CAN channel and PassThruSetProgrammingVoltage (dev handle).
Safe pins only: {8,9,11,12,13} (never 6/14 = CAN). All pins forced OFF at start and exit.

Run: <py311x86>\\python.exe bench/find_vcc_pin.py
"""
import os
import sys
import time
from ctypes import c_char_p, c_ulong, POINTER, byref, create_string_buffer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN, module_alive, HEARTBEAT_ID  # noqa: E402
from nm_uds_probe import container_frames, send_container, send_nm_direct, NM_NODES  # noqa: E402

PINS = [8, 9, 11, 12, 13]
VOLTAGE_OFF = 0xFFFFFFFF
MV = 12000


def bind_feps(c):
    c.d.PassThruSetProgrammingVoltage.argtypes = [c_ulong, c_ulong, c_ulong]
    c.d.PassThruSetProgrammingVoltage.restype = c_ulong
    c.d.PassThruGetLastError.argtypes = [c_char_p]; c.d.PassThruGetLastError.restype = c_ulong

    def setv(pin, mv):
        rc = c.d.PassThruSetProgrammingVoltage(c.dev, pin, mv)
        return rc
    return setv


def wake(c, secs=6):
    """Drive NM wake until broadcasting or timeout; return set of broadcast ids seen."""
    wni = 0
    t = time.time()
    alive = set()
    while time.time() - t < secs and not alive:
        for _ in range(8):
            send_container(c, container_frames(NM_NODES[wni % 6]))
            send_nm_direct(c, NM_NODES[wni % 6], 0)
            wni += 1
        alive = module_alive(c, 0.5)
    return alive


def passive_window(c, secs=8, tail=2.0):
    """Sniff with NO TX for `secs`. Return (total_frames, frames_in_final_`tail`_seconds)."""
    total = 0
    tail_cnt = 0
    t0 = time.time()
    while time.time() - t0 < secs:
        r = c.read(20)
        if r and r[0] != HEARTBEAT_ID:
            total += 1
            if (time.time() - t0) >= (secs - tail):
                tail_cnt += 1
    return total, tail_cnt


def iso_sf(p):
    return bytes([len(p)]) + p + b"\xAA" * (7 - len(p))


def uds_probe(c, secs=3):
    """While awake, send 3E00/1003 on 0x6b4 and 0x713, watch all rx for a UDS reply."""
    t0 = time.time()
    found = None
    while time.time() - t0 < secs and not found:
        for rq in (0x6B4, 0x713):
            c.write(rq, iso_sf(bytes.fromhex("3E00")))
            c.write(rq, iso_sf(bytes.fromhex("1003")))
        tw = time.time()
        while time.time() - tw < 0.2:
            r = c.read(10)
            if not r:
                continue
            pl = r[1]
            if pl and (pl[0] >> 4) == 0:
                uds = pl[1:1 + (pl[0] & 0xF)]
                if uds and (uds[0] in (0x50, 0x7E) or (uds[0] == 0x7F and uds[1] in (0x3E, 0x10))
                            or uds[0] == 0x7E):
                    found = (r[0], bytes(uds))
                    break
    return found


def main():
    c = RawCAN()
    setv = bind_feps(c)
    results = []
    try:
        for p in PINS:
            setv(p, VOLTAGE_OFF)
        time.sleep(0.5)

        # --- control: no pin energized ---
        print("[control] no FEPS pin energized: wake, then watch if it stays awake...")
        a = wake(c, 6)
        print(f"  woke: {bool(a)}")
        tot, tail = passive_window(c, 8)
        print(f"  after stimulus stop: {tot} frames total, {tail} in final 2s -> "
              f"{'STAYS AWAKE' if tail > 0 else 'sleeps'} (baseline should sleep)")
        base_tail = tail
        time.sleep(3)  # let it settle/sleep

        # --- per pin ---
        for pin in PINS:
            print(f"\n[pin {pin}] energizing {MV}mV ...")
            rc = setv(pin, MV)
            if rc != 0:
                print(f"  set failed rc={rc}; skipping")
                continue
            time.sleep(0.3)
            a = wake(c, 6)
            woke = bool(a)
            tot, tail = passive_window(c, 8)
            uds = uds_probe(c, 3) if woke else None
            setv(pin, VOLTAGE_OFF)
            stays = tail > 0
            print(f"  woke={woke}  after-stop: {tot} frames ({tail} in final 2s) -> "
                  f"{'STAYS AWAKE (**VCC+ pin?**)' if stays else 'sleeps'}"
                  + (f"  UDS={uds[1].hex(' ')} on 0x{uds[0]:03x}" if uds else ""))
            results.append((pin, woke, tot, tail, stays, uds))
            time.sleep(4)  # allow sleep between pins for an independent test
    finally:
        for p in PINS:
            try: setv(p, VOLTAGE_OFF)
            except Exception: pass
        c.close()

    print("\n=== SUMMARY ===")
    hits = [r for r in results if r[4]]  # stays awake
    uds_hits = [r for r in results if r[5]]
    if uds_hits:
        for pin, *_ , uds in uds_hits:
            print(f"  JACKPOT pin {pin}: UDS responded ({uds[1].hex(' ')}) — this pin drives term15 and it gates diag")
    if hits:
        print("  VCC+/term15 pin(s) (module stays awake when energized): " +
              ", ".join(str(r[0]) for r in hits))
    if not hits and not uds_hits:
        print("  No pin kept the module awake and no UDS reply. Either none of {8,9,11,12,13} is wired")
        print("  to your VCC+ lead, or term15 does not control the module's sleep. Tell me the ElsaWin")
        print("  pin-15 finding / which pigtail lead you connected and I'll adjust.")


if __name__ == "__main__":
    main()
