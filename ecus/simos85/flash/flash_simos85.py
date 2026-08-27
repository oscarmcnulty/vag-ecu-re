#!/usr/bin/env python3
"""Flash a calibration to the Continental Simos 8.5 (Audi Q5 3.0T, 8R0907551F) over UDS.

Built from this repo's RE (../analysis/flash_protocol.md); the SA2 seed->key is our own
sa2.py and the LZSS+XOR codec is our own simos_codec.py. The bri3d/VW_Flash acceptance
test corrected several on-wire specifics (DFI 0xAA, erase/checkMemory arg shapes, the
OBD-04 / workshop-code / TesterPresent additions, and the precondition ordering); those
corrections are folded in here and each is cited in flash_protocol.md §6.

On-car write. DRY-RUN by default; pass --flash to program. Battery charger on, engine off.

SEQUENCE (the proven Simos8 order):
   04                       OBD Mode-04 clear DTCs (functional)  <- programming precondition
   10 03                    extended diagnostic session
   31 01 0203               checkProgrammingPreconditions (in extended session)
   10 02                    PROGRAMMING session
   3E 00                    TesterPresent
   27 11 -> 27 12 <key>     SecurityAccess SA2 (sa2.py)
   2E F1 5A <fingerprint>   write programming fingerprint / workshop code
   31 01 FF00 01 03         eraseMemory(block 0x03)
   34 AA 41 03 <unc size:4> RequestDownload  DFI=0xAA (lzss+xor), ALFID=0x41, uncompressed size
   36 <seq> <enc chunks>    TransferData (LZSS+XOR stream, chunked to maxNumberOfBlockLength)
   37                       RequestTransferExit
   31 01 0202 01 03 00 04 00000000   checkMemory (Simos ignores the value -> zero header)
   31 01 FF01               checkProgrammingDependencies
   11 01                    ECUReset
   04                       OBD Mode-04 clear DTCs (post-reset)
TesterPresent (3E 00) is sent after each major step to hold the session.
"""
import argparse
import struct
import time

from sa2 import SIMOS85_SA2, seed_to_key
import simos_codec

TX_ID, RX_ID = 0x7E0, 0x7E8       # Simos reflash channel (VW_Flash constants.py:77)
OBD_FUNCTIONAL = 0x7DF            # Mode-04 clear (VW_Flash uses 0x700; 0x7DF is the OBD broadcast)
BLOCK_ID = 0x03                   # CAL
DFI = 0xAA                        # compression=0xA (lzss) | encryption=0xA (xor)
ALFID = 0x41                      # 4-byte size + 1-byte block id
SA_REQUEST, SA_SEND = 0x11, 0x12
PRECOND_RID, ERASE_RID, CHECKMEM_RID, DEPEND_RID = 0x0203, 0xFF00, 0x0202, 0xFF01
# programming fingerprint / workshop code written to DID 0xF15A before erase.
FINGERPRINT_DID = 0xF15A
FINGERPRINT = bytes.fromhex("20042042042042B13D")
MAX_CHUNK = 0xFFD                 # VW_Flash caps TransferData payload at 0xFFD


class NegativeResponse(Exception):
    pass


class Transport:
    def request(self, payload: bytes, pending_timeout: float = 30.0) -> bytes:
        raise NotImplementedError

    def send_raw(self, can_id: int, data: bytes):
        raise NotImplementedError


class IsoTpTransport(Transport):
    """Linux SocketCAN + isotp kernel module (pip install can-isotp)."""

    def __init__(self, channel="can0", tx=TX_ID, rx=RX_ID, timeout=5.0):
        import isotp
        import socket
        self.timeout = timeout
        self.channel = channel
        self.s = isotp.socket()
        self.s.set_opts(txpad=0x00)
        self.s.bind(channel, isotp.Address(rxid=rx, txid=tx))
        self._raw = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self._raw.bind((channel,))

    def request(self, payload, pending_timeout=30.0):
        self.s.send(payload)
        deadline = time.time() + pending_timeout
        while True:
            self.s.settimeout(min(self.timeout, max(0.1, deadline - time.time())))
            resp = self.s.recv()
            if resp and resp[0] == 0x7F and len(resp) > 2 and resp[2] == 0x78:
                continue                       # responsePending
            return resp

    def send_raw(self, can_id, data):
        frame = struct.pack("=IB3x8s", can_id, len(data), data.ljust(8, b"\x00"))
        self._raw.send(frame)


class PandaTransport(Transport):
    """comma panda backend (mirrors the AL551 flasher's wiring)."""

    def __init__(self, tx=TX_ID, rx=RX_ID, bus=0, timeout=5.0):
        from panda import Panda
        from opendbc.car.isotp_parser import IsoTpParser
        self.p = Panda()
        self.p.set_safety_mode(17)
        time.sleep(0.2)
        self.p.set_heartbeat_disabled()
        self.tx, self.rx, self.bus, self.timeout = tx, rx, bus, timeout
        self._parser = IsoTpParser(self.p, tx, rx, bus)

    def request(self, payload, pending_timeout=30.0):
        return self._parser.request(payload, timeout=pending_timeout)

    def send_raw(self, can_id, data):
        self.p.can_send(can_id, data.ljust(8, b"\x00"), self.bus)


class Uds:
    def __init__(self, t: Transport):
        self.t = t

    def req(self, sid, *data, pending_timeout=30.0):
        payload = bytes([sid]) + b"".join(
            d if isinstance(d, (bytes, bytearray)) else bytes([d]) for d in data)
        resp = self.t.request(payload, pending_timeout)
        if not resp:
            raise NegativeResponse(f"svc 0x{sid:02x}: no response")
        if resp[0] == 0x7F:
            raise NegativeResponse(f"svc 0x{sid:02x}: NRC 0x{resp[2] if len(resp)>2 else 0:02x}")
        if resp[0] != sid + 0x40:
            raise NegativeResponse(f"svc 0x{sid:02x}: bad echo 0x{resp[0]:02x}")
        return resp

    def tester_present(self):
        return self.req(0x3E, 0x00)

    def session(self, level):
        r = self.req(0x10, level); return r

    def security_access(self, bytecode):
        seed = self.req(0x27, SA_REQUEST)[2:]
        if not any(seed):
            return
        key = seed_to_key(bytecode, int.from_bytes(seed, "big"))
        self.req(0x27, SA_SEND, key.to_bytes(4, "big"))

    def write_did(self, did, data):
        return self.req(0x2E, struct.pack(">H", did), data)

    def routine(self, rid, arg=b"", sub=0x01):
        return self.req(0x31, sub, struct.pack(">H", rid), arg)

    def request_download(self, block_id, uncompressed_size, dfi=DFI, alfid=ALFID):
        addr_len, size_len = alfid & 0x0F, (alfid >> 4) & 0x0F
        body = (bytes([dfi, alfid])
                + block_id.to_bytes(addr_len, "big")
                + uncompressed_size.to_bytes(size_len, "big"))
        resp = self.req(0x34, *body)
        lfid = (resp[1] >> 4) & 0x0F if len(resp) > 1 else 2
        maxblk = int.from_bytes(resp[2:2 + lfid], "big") if lfid else MAX_CHUNK + 2
        return min(maxblk, MAX_CHUNK + 2)

    def transfer_data(self, payload, maxblk):
        chunk = max(1, maxblk - 2)          # minus SID + block-seq-counter
        seq = 1
        for off in range(0, len(payload), chunk):
            self.req(0x36, seq & 0xFF, payload[off:off + chunk])
            seq = (seq + 1) & 0xFF
            if seq == 0:
                seq = 0                      # VW wraps 0xFF -> 0x00

    def transfer_exit(self):
        return self.req(0x37)

    def ecu_reset(self, kind=0x01):
        return self.req(0x11, kind)


def obd_clear_dtcs(t: Transport):
    # Mode 04 (clear emissions DTCs): single frame [len=1][0x04]
    try:
        t.send_raw(OBD_FUNCTIONAL, bytes([0x01, 0x04]))
        time.sleep(0.3)
    except NotImplementedError:
        pass


def flash(t: Transport, block: bytes, bytecode: bytes):
    u = Uds(t)
    print("--- preconditions (extended session) ---")
    obd_clear_dtcs(t)
    u.session(0x03)
    u.routine(PRECOND_RID)                                   # checkProgrammingPreconditions
    print("--- programming session + SA2 ---")
    u.session(0x02)
    u.tester_present()
    u.security_access(bytecode)
    u.tester_present()
    u.write_did(FINGERPRINT_DID, FINGERPRINT)               # programming fingerprint
    print("--- erase + download ---")
    u.routine(ERASE_RID, bytes([0x01, BLOCK_ID]))           # eraseMemory(block 0x03)
    u.tester_present()
    payload = simos_codec.encode(block)                     # LZSS + XOR (DFI 0xAA)
    maxblk = u.request_download(BLOCK_ID, len(block))       # size = UNCOMPRESSED length
    print(f"    payload {len(block)} B -> {len(payload)} B encoded; "
          f"maxNumberOfBlockLength = 0x{maxblk:x}")
    u.transfer_data(payload, maxblk)
    u.transfer_exit()
    u.tester_present()
    print("--- verify + finalize ---")
    # Simos ignores the UDS checksum value -> zero header {ALFID? , block, len=4, crc=0}
    u.routine(CHECKMEM_RID, bytes([0x01, BLOCK_ID, 0x00, 0x04]) + b"\x00\x00\x00\x00")
    u.routine(DEPEND_RID)                                    # checkProgrammingDependencies
    u.ecu_reset(0x01)
    time.sleep(2.0)
    obd_clear_dtcs(t)
    print("done. reset issued — verify no DTCs before driving.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload", help="CAL_block3.bin from prep_cal.py (raw, uncompressed)")
    ap.add_argument("--transport", choices=["isotp", "panda"], default="isotp")
    ap.add_argument("--channel", default="can0", help="socketcan channel (isotp)")
    ap.add_argument("--flash", action="store_true", help="ACTUALLY write (default: dry-run)")
    a = ap.parse_args()

    block = open(a.payload, "rb").read()
    encoded = simos_codec.encode(block)
    assert simos_codec.decode(encoded, len(block)) == block, "codec round-trip failed"

    print("=== Simos 8.5 CAL flash plan ===")
    print(f"  block id 0x{BLOCK_ID:02x} (CAL), {len(block)} B raw -> {len(encoded)} B "
          f"(LZSS+XOR), DFI=0x{DFI:02x}, ALFID=0x{ALFID:02x}")
    print(f"  SA2 seed/key via sa2.py (level 0x{SA_REQUEST:02x}/0x{SA_SEND:02x}); "
          f"erase 0x{ERASE_RID:04x} arg 01 {BLOCK_ID:02x}; checkMemory 0x{CHECKMEM_RID:04x} zero-header")
    if not a.flash:
        print("\n(dry run — pass --flash to execute; battery charger on, engine off)")
        return

    t = IsoTpTransport(a.channel) if a.transport == "isotp" else PandaTransport()
    flash(t, block, SIMOS85_SA2)


if __name__ == "__main__":
    main()
