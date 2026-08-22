#!/usr/bin/env python3
"""Prepare an updated AL551 CAL for flashing: fix the internal CRC32, extract the DB_4
(calibration) block, method-22 encode it, and compute the block CRC32 for checkMemory.

The AL551 flash is 4 UDS blocks: DB_1 ASW@0x40000, DB_2 blk2@0x6000, DB_3 CBOOT@0x20000,
DB_4 CAL@0x180200 (523776 B). We only reflash DB_4 to change calibration.

Two checksums must be right (both standard zlib CRC32, big-endian, VERIFIED on the stock image):
  * INTERNAL CAL CRC32 @ flash 0x180244, computed over 0x190000..0x1FFD5F. The ECU checks this
    at runtime; edit the CAL then rewrite this field or the box faults.
  * BLOCK CRC32 over the whole 523776-byte DB_4 payload — the argument to the checkMemory
    routine (0x0202) the ECU runs to accept the download.

Usage:
  python3 prep_cal.py <modified_full_flash.bin> [--out DIR]
Writes:  DB_4_plain.bin (fixed), DB_4_method22.bin (flash payload), block_crc32.txt
"""
import sys, os, struct, zlib, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from al551_codec import compress_method22, decompress_method22   # repo-root

DB4_BASE, DB4_LEN = 0x180200, 0x7FE00          # 523776
CAL_CRC_ADDR      = 0x180244                    # internal CRC32 field (big-endian)
CAL_LO, CAL_HI    = 0x190000, 0x1FFD60          # CRC region 0x190000..0x1FFD5F

def fix_internal_crc(img: bytearray) -> int:
    crc = zlib.crc32(bytes(img[CAL_LO:CAL_HI])) & 0xffffffff
    img[CAL_CRC_ADDR:CAL_CRC_ADDR+4] = struct.pack(">I", crc)   # big-endian
    return crc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="modified full-flash .bin (0..0x200000)")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    img = bytearray(open(a.image, "rb").read())
    assert len(img) >= 0x200000, "expected a 2 MB full-flash image"
    os.makedirs(a.out, exist_ok=True)

    crc = fix_internal_crc(img)
    print(f"internal CAL CRC32 @0x{CAL_CRC_ADDR:06x} set to 0x{crc:08x} (over 0x{CAL_LO:x}..0x{CAL_HI-1:x})")

    block = bytes(img[DB4_BASE:DB4_BASE+DB4_LEN])
    assert len(block) == DB4_LEN
    block_crc = zlib.crc32(block) & 0xffffffff
    enc = compress_method22(block)
    assert decompress_method22(enc, DB4_LEN) == block, "method-22 round-trip failed"

    open(os.path.join(a.out, "DB_4_plain.bin"), "wb").write(block)
    open(os.path.join(a.out, "DB_4_method22.bin"), "wb").write(enc)
    open(os.path.join(a.out, "block_crc32.txt"), "w").write(f"{block_crc:08X}\n")
    print(f"DB_4 block: {len(block)} B plain, {len(enc)} B method-22 (all-literal)")
    print(f"block CRC32 (checkMemory arg): 0x{block_crc:08X}")
    print(f"flash target: RequestDownload addr=0x{DB4_BASE:06x} size=0x{DB4_LEN:x} uncompressed")
    print(f"wrote DB_4_plain.bin, DB_4_method22.bin, block_crc32.txt -> {a.out}")

if __name__ == "__main__":
    main()
