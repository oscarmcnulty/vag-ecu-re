#!/usr/bin/env python3
"""J2534 (PassThru v04.04) ISO-TP transport for the UDS client.

Drives a SAE-J2534 pass-thru device's ISO15765 protocol, so the DLL handles
ISO-TP segmentation + flow control and we exchange whole UDS payloads. Wraps the
vendor DLL with ctypes; on Windows only, and the DLL bitness must match the
Python bitness (Scanmatik's smj2534.dll is 32-bit -> use 32-bit Python).

Implements core.uds.uds_client.Transport: request(payload) -> response payload.

Standalone smoke test:
    python -m core.uds.j2534_transport \
        --dll "C:/Program Files (x86)/Scanmatik/smj2534.dll" \
        --tx 0x713 --rx 0x77D --baud 500000 --send 3E00

Reference: SAE J2534-1 (v04.04). Constants below are from that spec.
"""
import argparse
import ctypes
from ctypes import (POINTER, Structure, byref, c_char, c_char_p, c_ubyte,
                    c_ulong, create_string_buffer)

# --- J2534 protocol / flag / ioctl / filter constants (v04.04) ---
CAN = 5
ISO15765 = 6

CAN_29BIT_ID = 0x0100          # Connect flag; omit for 11-bit
ISO15765_FRAME_PAD = 0x0040    # TxFlags: pad single frames to 8 bytes

# RxStatus bits
TX_MSG_TYPE = 0x0001           # this is a TX echo/indication, not RX data
START_OF_MESSAGE = 0x0002      # ISO15765 first-frame indication (DataSize==4)

# Filter types
PASS_FILTER = 1
FLOW_CONTROL_FILTER = 3

# Ioctl IDs
CLEAR_RX_BUFFER = 0x08
CLEAR_TX_BUFFER = 0x07

STATUS_NOERROR = 0


class PASSTHRU_MSG(Structure):
    _fields_ = [
        ("ProtocolID", c_ulong),
        ("RxStatus", c_ulong),
        ("TxFlags", c_ulong),
        ("Timestamp", c_ulong),
        ("DataSize", c_ulong),
        ("ExtraDataIndex", c_ulong),
        ("Data", c_ubyte * 4128),
    ]


class J2534Error(Exception):
    pass


class J2534:
    """Thin ctypes binding for the PassThru v04.04 entry points we need."""

    def __init__(self, dll_path):
        self.dll = ctypes.WinDLL(dll_path)
        self._bind("PassThruOpen", [c_char_p, POINTER(c_ulong)])
        self._bind("PassThruClose", [c_ulong])
        self._bind("PassThruConnect",
                   [c_ulong, c_ulong, c_ulong, c_ulong, POINTER(c_ulong)])
        self._bind("PassThruDisconnect", [c_ulong])
        self._bind("PassThruReadMsgs",
                   [c_ulong, POINTER(PASSTHRU_MSG), POINTER(c_ulong), c_ulong])
        self._bind("PassThruWriteMsgs",
                   [c_ulong, POINTER(PASSTHRU_MSG), POINTER(c_ulong), c_ulong])
        self._bind("PassThruStartMsgFilter",
                   [c_ulong, c_ulong, POINTER(PASSTHRU_MSG),
                    POINTER(PASSTHRU_MSG), POINTER(PASSTHRU_MSG),
                    POINTER(c_ulong)])
        self._bind("PassThruIoctl", [c_ulong, c_ulong, ctypes.c_void_p,
                                     ctypes.c_void_p])
        self._bind("PassThruGetLastError", [c_char_p])

    def _bind(self, name, argtypes):
        fn = getattr(self.dll, name)
        fn.argtypes = argtypes
        fn.restype = c_ulong
        setattr(self, name, fn)

    def _check(self, rc, where):
        if rc != STATUS_NOERROR:
            buf = create_string_buffer(160)
            try:
                self.PassThruGetLastError(buf)
                detail = buf.value.decode("latin-1", "replace")
            except Exception:
                detail = ""
            raise J2534Error(f"{where} failed rc={rc} ({rc:#x}) {detail}")


def _mk_msg(protocol, can_id, payload=b"", tx_flags=0):
    m = PASSTHRU_MSG()
    m.ProtocolID = protocol
    m.TxFlags = tx_flags
    data = can_id.to_bytes(4, "big") + payload
    m.DataSize = len(data)
    for i, b in enumerate(data):
        m.Data[i] = b
    return m


class J2534IsoTpTransport:
    """UDS Transport over J2534 ISO15765 (11-bit). The DLL does ISO-TP framing.

    tx_id = physical request CAN ID (tester -> ECU), rx_id = response ID.
    """

    def __init__(self, dll_path, tx_id, rx_id, baud=500000,
                 device_name=None, timeout_ms=2000):
        self.j = J2534(dll_path)
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.timeout_ms = timeout_ms
        self.device_id = c_ulong(0)
        self.channel_id = c_ulong(0)
        name = device_name.encode() if device_name else None
        self.j._check(self.j.PassThruOpen(name, byref(self.device_id)),
                      "PassThruOpen")
        self.j._check(
            self.j.PassThruConnect(self.device_id, ISO15765, 0, baud,
                                   byref(self.channel_id)),
            "PassThruConnect(ISO15765)")
        self._flow_control_filter()

    def _flow_control_filter(self):
        mask = _mk_msg(ISO15765, 0xFFFFFFFF)
        patt = _mk_msg(ISO15765, self.rx_id)
        flow = _mk_msg(ISO15765, self.tx_id)
        fid = c_ulong(0)
        self.j._check(
            self.j.PassThruStartMsgFilter(self.channel_id, FLOW_CONTROL_FILTER,
                                          byref(mask), byref(patt),
                                          byref(flow), byref(fid)),
            "PassThruStartMsgFilter(FLOW_CONTROL)")

    def request(self, payload: bytes) -> bytes:
        """Send one UDS payload, return the (reassembled) response payload.

        Skips the TX echo and the ISO15765 first-frame indication; waits for
        the response addressed from rx_id. Raises J2534Error on timeout.
        """
        # flush stale RX
        try:
            self.j.PassThruIoctl(self.channel_id, CLEAR_RX_BUFFER, None, None)
        except Exception:
            pass
        msg = _mk_msg(ISO15765, self.tx_id, payload, ISO15765_FRAME_PAD)
        n = c_ulong(1)
        self.j._check(
            self.j.PassThruWriteMsgs(self.channel_id, byref(msg), byref(n),
                                     self.timeout_ms),
            "PassThruWriteMsgs")

        deadline_reads = 64
        for _ in range(deadline_reads):
            rx = PASSTHRU_MSG()
            cnt = c_ulong(1)
            rc = self.j.PassThruReadMsgs(self.channel_id, byref(rx),
                                         byref(cnt), self.timeout_ms)
            if rc != STATUS_NOERROR or cnt.value == 0:
                # ERR_BUFFER_EMPTY (0x10) / ERR_TIMEOUT (0x09) -> nothing yet
                raise J2534Error(f"no response within {self.timeout_ms} ms "
                                 f"(rc={rc:#x})")
            if rx.RxStatus & TX_MSG_TYPE:
                continue  # our own TX echo
            if rx.RxStatus & START_OF_MESSAGE and rx.DataSize <= 4:
                continue  # multi-frame start indication, data follows
            if rx.DataSize <= 4:
                continue  # header only, no payload
            return bytes(bytes(rx.Data[:rx.DataSize])[4:])
        raise J2534Error("exhausted reads without a data frame")

    def close(self):
        try:
            if self.channel_id.value:
                self.j.PassThruDisconnect(self.channel_id)
        finally:
            if self.device_id.value:
                self.j.PassThruClose(self.device_id)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _main():
    ap = argparse.ArgumentParser(description="J2534 ISO-TP smoke test")
    ap.add_argument("--dll", required=True)
    ap.add_argument("--tx", default="0x713")
    ap.add_argument("--rx", default="0x77D")
    ap.add_argument("--baud", type=int, default=500000)
    ap.add_argument("--send", default="3E00",
                    help="hex UDS payload, e.g. 3E00 (TesterPresent)")
    ap.add_argument("--timeout", type=int, default=2000)
    a = ap.parse_args()
    tx, rx = int(a.tx, 0), int(a.rx, 0)
    payload = bytes.fromhex(a.send)
    print(f"open {a.dll}\nISO15765 {a.baud} bps  tx={tx:#05x} rx={rx:#05x}")
    with J2534IsoTpTransport(a.dll, tx, rx, a.baud, timeout_ms=a.timeout) as t:
        print(f"-> {payload.hex(' ')}")
        resp = t.request(payload)
        print(f"<- {resp.hex(' ')}")


if __name__ == "__main__":
    _main()
