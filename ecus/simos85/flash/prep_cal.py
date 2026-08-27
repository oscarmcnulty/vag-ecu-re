#!/usr/bin/env python3
"""Prepare a modified Simos 8.5 CALIBRATION for flashing.

Simos8.5 (8R0907551F) reflash blocks (from the ODX; SOURCE-START-ADDRESS = UDS block id):
    block 0x01 CBOOT 81408 B | block 0x02 ASW 1572352 B | block 0x03 CAL 261632 B

The calibration carries an INTERNAL CRC-32 the ECU verifies (repro-status bit #15 /
Mode-09 CVN). It is NOT reflected zlib CRC-32 — it is the "Simos" CRC-32:
    poly 0x04C11DB7, init 0x00000000, no input/output reflection, no final XOR.
VERIFIED: over the descriptor segments this reproduces the stock reference 0xA92A60BC
byte-for-byte (../firmware/8R0907551F_Original.bin). The descriptor lives at 0x40300:
    { u32 type, u32 ref_crc (little-endian), u32 seg_count, {u32 start, u32 end}... }
ends are inclusive; addresses masked to file offset. Editing cal without fixing this
makes the change detectable (CVN withheld / repro-status clears), so a clean tune fixes it.

Flash acceptance itself is gated by the loader's streamed per-0x1e00 CRC-16 (init 0xABCD)
and RSA at boot; the UDS checkMemory value is ignored by Simos (sent as a zero header by
the flasher). So this tool's job is: fix the internal Simos CRC-32, extract the CAL block.

ECM3 monitor: Simos also keeps a 64-bit "ECM3" sum near cal offset 0x400 (flagged by the
acceptance test). Its exact region/layout is not yet pinned from our firmware, so this
tool REPORTS it for review rather than patching an unverified value. See flash_protocol.md.

Usage:  prep_cal.py <modified_full_flash.bin> [--out DIR]
Writes: CAL_block3.bin (payload) + updates the CVN word in-place; cvn_crc32.txt
"""
import argparse, os, struct

CAL_FILE_LO = 0x40000
CAL_WIRE_LEN = 261632            # ODX UNCOMPRESSED-SIZE for block 0x03 (part 8R0907551F)
BLOCK_ID = 0x03
CVN_DESC = 0x40300               # {type, ref_crc, seg_count, {start,end}...}


def simos_crc32(data: bytes) -> int:
    """CRC-32, poly 0x04C11DB7, init 0, MSB-first, no reflection, no final XOR."""
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc & 0xFFFFFFFF


def parse_cvn_descriptor(img):
    ref = struct.unpack_from("<I", img, CVN_DESC + 4)[0]
    n = struct.unpack_from("<I", img, CVN_DESC + 8)[0]
    if not (1 <= n <= 8):
        return None
    segs, o = [], CVN_DESC + 12
    for _ in range(n):
        s = struct.unpack_from("<I", img, o)[0] & 0x00FFFFFF
        e = struct.unpack_from("<I", img, o + 4)[0] & 0x00FFFFFF
        segs.append((s, e + 1))          # inclusive end
        o += 8
    return ref, segs


def cvn_over(img, segs):
    return simos_crc32(b"".join(bytes(img[lo:hi]) for lo, hi in segs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="modified full-flash .bin (>= 2 MB, base 0x80000000)")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    img = bytearray(open(a.image, "rb").read())
    assert len(img) >= 0x200000, "expected a >=2 MB full-flash image"
    os.makedirs(a.out, exist_ok=True)

    desc = parse_cvn_descriptor(img)
    if desc:
        ref, segs = desc
        seg_str = "+".join(f"[0x{lo:x}..0x{hi-1:x}]" for lo, hi in segs)
        new = cvn_over(img, segs)
        img[CVN_DESC + 4:CVN_DESC + 8] = struct.pack("<I", new)   # stored little-endian
        with open(a.image, "wb") as fh:
            fh.write(img)
        open(os.path.join(a.out, "cvn_crc32.txt"), "w").write(f"{new:08X}\n")
        was = "unchanged" if new == ref else f"was 0x{ref:08X}"
        print(f"internal Simos CRC-32 @0x{CVN_DESC+4:05x} = 0x{new:08X} ({was}) over {seg_str}")
    else:
        print("CVN descriptor not recognized — skipped.")

    block = bytes(img[CAL_FILE_LO:CAL_FILE_LO + CAL_WIRE_LEN])
    open(os.path.join(a.out, "CAL_block3.bin"), "wb").write(block)
    print(f"CAL block 0x{BLOCK_ID:02x}: {len(block)} B (uncompressed) -> CAL_block3.bin")
    print(f"NOTE: flash_simos85.py LZSS+XOR-encodes this and sends DFI 0xAA; RequestDownload")
    print(f"      size = uncompressed {len(block)} B. ECM3 monitor @~0x400: review manually.")


if __name__ == "__main__":
    main()
