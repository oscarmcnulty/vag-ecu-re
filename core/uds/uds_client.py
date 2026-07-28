#!/usr/bin/env python3
"""Minimal ISO-14229 (UDS) client harness for cal read/write over CAN.

Protocol-level skeleton: service IDs, ISO-TP framing hook, and the read/write
flows you need for ECU calibration work. Transport (socketcan / Tactrix / J2534)
is pluggable via the `Transport` interface — wire one in for your hardware.

This is arch-agnostic; per-ECU specifics (DIDs, routine IDs, seed/key algorithm,
session/security levels) belong in ecus/<name>/.
"""
import struct

# --- UDS service IDs (subset) ---
DIAGNOSTIC_SESSION_CONTROL = 0x10
ECU_RESET = 0x11
SECURITY_ACCESS = 0x27
READ_DATA_BY_ID = 0x22
WRITE_DATA_BY_ID = 0x2E
ROUTINE_CONTROL = 0x31
REQUEST_DOWNLOAD = 0x34
TRANSFER_DATA = 0x36
REQUEST_TRANSFER_EXIT = 0x37
READ_MEMORY_BY_ADDRESS = 0x23

NRC = {0x10: "generalReject", 0x11: "serviceNotSupported", 0x22: "conditionsNotCorrect",
       0x31: "requestOutOfRange", 0x33: "securityAccessDenied", 0x35: "invalidKey",
       0x78: "responsePending"}


class Transport:
    """Implement send/recv of a full (reassembled) UDS payload over ISO-TP."""
    def request(self, payload: bytes) -> bytes:  # returns response payload
        raise NotImplementedError


class NegativeResponse(Exception):
    pass


class UDS:
    def __init__(self, transport: Transport):
        self.t = transport

    def _req(self, sid, *data):
        payload = bytes([sid]) + b"".join(
            d if isinstance(d, (bytes, bytearray)) else bytes([d]) for d in data)
        resp = self.t.request(payload)
        if resp and resp[0] == 0x7F:
            nrc = resp[2] if len(resp) > 2 else 0
            raise NegativeResponse(f"svc {sid:#x}: {NRC.get(nrc, hex(nrc))}")
        return resp

    def session(self, level=0x03):           # extended diagnostic by default
        return self._req(DIAGNOSTIC_SESSION_CONTROL, level)

    def read_did(self, did):
        return self._req(READ_DATA_BY_ID, struct.pack(">H", did))[3:]

    def write_did(self, did, data):
        return self._req(WRITE_DATA_BY_ID, struct.pack(">H", did), data)

    def security_access(self, request_level, key_from_seed):
        """key_from_seed(seed: bytes) -> key: bytes. ECU-specific; supply per pack."""
        seed = self._req(SECURITY_ACCESS, request_level)[2:]
        if any(seed):
            self._req(SECURITY_ACCESS, request_level + 1, key_from_seed(seed))
        return True

    def routine(self, sub, routine_id, *data):     # sub: 0x01 start/0x02 stop/0x03 result
        return self._req(ROUTINE_CONTROL, sub, struct.pack(">H", routine_id), *data)

    def read_memory(self, addr, size, addr_len=4, size_len=4):
        alfid = (size_len << 4) | addr_len
        return self._req(READ_MEMORY_BY_ADDRESS, alfid,
                         addr.to_bytes(addr_len, "big"),
                         size.to_bytes(size_len, "big"))[1:]


if __name__ == "__main__":
    print("UDS skeleton. Provide a Transport (socketcan/J2534) and a per-ECU "
          "seed/key in ecus/<name>/ to use security_access().")
