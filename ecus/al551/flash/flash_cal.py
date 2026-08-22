#!/usr/bin/env python3
"""Flash an updated CALIBRATION (DB_4) to the Audi AL551 (ZF 8HP) TCU over UDS, following the
bri3d/VW_Flash sequence. On-car write; DRY-RUN by default -- pass --flash to actually program.

Pipeline:   edit CAL -> prep_cal.py (fix CRC32 + method-22 encode) -> this script.

SEQUENCE (standard VW UDS flash; AL551 params CONFIRMED on-car / from the ODX + firmware):
  1  10 03            extended session
  2  04               OBD mode-04 clear DTCs  (the real programming-session precondition)
  3  85 02            ControlDTCSetting = off
  4  28 03 01         CommunicationControl = disableRxAndTx / normal
  5  10 02            PROGRAMMING session
  6  27 11 / 27 12    SecurityAccess SA2  (LEVEL 0x11 -- programming, not 0x03)  [Sa2SeedKey]
  7  31 01 0203       RoutineControl checkProgrammingPreconditions
  8  31 01 FF00 ...   RoutineControl eraseMemory (DB_4)
  9  34 DFI 44 A S    RequestDownload  DFI=0x22 (method "22"), ALFID=0x44 (4B addr+4B len),
                      addr=0x00180200, len=0x0007FE00 (UNCOMPRESSED size)
  10 36 <seq> <...>   TransferData  (method-22 stream from prep_cal.py, chunked to STMIN/blocklen)
  11 37               RequestTransferExit
  12 31 01 0202 CRC   RoutineControl checkMemory  (arg = block CRC32 from prep_cal.py, big-endian)
  13 31 01 FF01       RoutineControl checkProgrammingDependencies
  14 11 01            ECUReset

Checksums (both standard zlib CRC32, big-endian; handled by prep_cal.py):
  * internal CAL CRC32 @0x180244 over 0x190000..0x1FFD5F  (runtime integrity -- edit breaks it)
  * DB_4 block CRC32 over the 523776-B payload            (checkMemory argument)

NOTE / verify-on-car: the RequestDownload memoryAddress (0x180200) and the erase argument
format follow the DB_4 flash-base + standard VW block erase. If your ODX flash job addresses by
logical block number, adjust ERASE_ARG / RD_ADDR accordingly (printed in --dry-run for review).
"""
import sys, time, struct, argparse, os
sys.path.insert(0, "/data")   # comma panda + opendbc on the device

SA2      = bytes.fromhex("6806814A05876B5F7DD5494C")   # AL551/DQ381 SA2 bytecode (CONFIRMED)
BUS, TX, RX = 1, 0x7E1, 0x7E9
RD_ADDR, RD_LEN = 0x00180200, 0x0007FE00               # DB_4 CAL: base + UNCOMPRESSED size
DFI      = 0x22                                          # dataFormatIdentifier = method "22"
ALFID    = 0x44                                          # 4-byte address + 4-byte length
ERASE_RID, PRECOND_RID, CHECKMEM_RID, DEPEND_RID = 0xFF00, 0x0203, 0x0202, 0xFF01

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("payload", help="DB_4_method22.bin from prep_cal.py")
    ap.add_argument("blockcrc", help="block_crc32.txt from prep_cal.py (hex)")
    ap.add_argument("--flash", action="store_true", help="ACTUALLY write (default: dry-run)")
    a = ap.parse_args()
    payload = open(a.payload, "rb").read()
    block_crc = int(open(a.blockcrc).read().strip(), 16)

    print("=== AL551 CAL flash plan ===")
    print(f"  payload {len(payload)} B (method-22) -> RequestDownload addr=0x{RD_ADDR:08x} "
          f"len=0x{RD_LEN:08x} DFI=0x{DFI:02x} ALFID=0x{ALFID:02x}")
    print(f"  erase RID=0x{ERASE_RID:04x}  precond=0x{PRECOND_RID:04x}  "
          f"checkMemory=0x{CHECKMEM_RID:04x} arg CRC32=0x{block_crc:08X}  depend=0x{DEPEND_RID:04x}")
    if not a.flash:
        print("\n(dry run -- pass --flash to execute; ensure battery/charger + engine off)")
        return

    from panda import Panda
    from opendbc.car.uds import (UdsClient, SESSION_TYPE, CONTROL_TYPE, MESSAGE_TYPE,
                                 DTC_SETTING_TYPE, ROUTINE_CONTROL_TYPE, DATA_IDENTIFIER_TYPE,
                                 NegativeResponseError)
    from sa2_seed_key import Sa2SeedKey
    keyf = lambda s: Sa2SeedKey(SA2, int.from_bytes(s, "big")).execute().to_bytes(4, "big")

    p = Panda(); p.set_safety_mode(17); time.sleep(0.2); p.set_heartbeat_disabled()
    c = UdsClient(p, TX, RX, bus=BUS, timeout=5.0, response_pending_timeout=30)

    def routine(rid, data=b"", sub=ROUTINE_CONTROL_TYPE.START):
        return c.routine_control(sub, rid, data)

    print("\n--- preconditions ---")
    c.diagnostic_session_control(SESSION_TYPE.EXTENDED_DIAGNOSTIC)
    p.can_send(0x7DF, bytes([0x01, 0x04]) + b"\x00"*6, BUS); time.sleep(0.3)  # OBD clear DTCs
    c.control_dtc_setting(DTC_SETTING_TYPE.OFF)
    c.communication_control(CONTROL_TYPE.DISABLE_RX_DISABLE_TX, MESSAGE_TYPE.NORMAL)
    print("--- programming session + SA2 (level 0x11) ---")
    c.diagnostic_session_control(SESSION_TYPE.PROGRAMMING)
    c.tester_present()
    seed = c.security_access(0x11)
    c.security_access(0x12, keyf(bytes(seed)))
    routine(PRECOND_RID)                                    # checkProgrammingPreconditions

    print("--- erase DB_4 + download ---")
    # erase arg: VW passes DFI + ALFID + addr + len (memory-range erase). Adjust if block-number.
    erase_arg = bytes([ALFID]) + struct.pack(">I", RD_ADDR) + struct.pack(">I", RD_LEN)
    routine(ERASE_RID, erase_arg)
    # RequestDownload: 34 DFI ALFID addr len
    rd = bytes([0x34, DFI, ALFID]) + struct.pack(">I", RD_ADDR) + struct.pack(">I", RD_LEN)
    resp = c._uds_request(0x34, None, rd[1:])              # returns max blocklength
    maxblk = int.from_bytes(resp[1:], "big") if len(resp) > 1 else 0xF00
    chunk = max(1, maxblk - 2)
    seq = 1
    for off in range(0, len(payload), chunk):
        c._uds_request(0x36, None, bytes([seq & 0xFF]) + payload[off:off+chunk])
        seq += 1
    c._uds_request(0x37, None, b"")                        # RequestTransferExit

    print("--- verify + finalize ---")
    routine(CHECKMEM_RID, struct.pack(">I", block_crc))    # checkMemory(block CRC32)
    routine(DEPEND_RID)                                    # checkProgrammingDependencies
    c.ecu_reset(0x01)
    print("done. reset issued -- verify gear engagement + no DTCs before driving.")

if __name__ == "__main__":
    main()
