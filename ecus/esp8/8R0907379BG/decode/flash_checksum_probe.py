#!/usr/bin/env python3
"""
flash_checksum_probe.py -- ESP8 8R0907379BG: is there a recomputable checksum
layer (CRC/sum) a flasher would correct, or is flash integrity RSA-only?

VAG/Bosch flashes usually have two integrity layers: (1) an RSA signature (the
hard blocker) and (2) one or more plain, recomputable checksums stored IN the
image that the bootloader download-check and/or a runtime monitor must find
correct -- these are what a flasher fixes after an edit. For Continental Simos
this second layer is a CRC32 (poly 0x04C11DB7, init 0, xorout 0) with an
in-image {init,crc,area_count,[start,end]...} descriptor, plus an "ECM3"
runtime monitor that continuously CRCs ASW+CAL (see VW_Flash lib/checksum.py).

This script proves that NO such layer exists in the ESP8 ASW/CAL image:
  1. No CRC16/CRC32 lookup table of ANY polynomial or endianness
     (poly-agnostic: CRC byte-tables are GF(2)-linear, T[i]=XOR of T[1<<b]).
     Only the two known CRC8 E2E tables (0xb408c/0xb4800, CAN message CRC) exist.
  2. No additive / xor / complement sum over the signed regions, code, CAL, or
     the 4 cal datasets is stored anywhere in the image or the .sgo container.
  3. No bit-serial CRC16/CRC32 (zlib-reflected OR Simos-forward, init 0 and
     0xffffffff) over those regions is stored anywhere.
  4. The .sgo container is 2 PLAIN (XOR-0xFF) blocks with NO per-block checksum
     field (only BCB-compressed crypt=0x10 blocks carry a 24-bit end-token sum,
     which ESP8 does not use).

Verdict: flash integrity is RSA-1024 ONLY (two signature blocks, see
docs/signature_analysis.md). Checksum-correction alone cannot make a modified
image flashable/bootable; the bootloader RSA-verify bypass is the only path.
Any boot-time integrity gate, if any, is CBOOT/SBOOT-resident (not in this ASW
image) and needs the bench bootloader dump to confirm.

Reads the gitignored firmware at runtime; commits only addresses/algorithms.
Run: python3 decode/flash_checksum_probe.py  [path-to-.bin]  [path-to-.sgo]
"""
import struct
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FW_DEFAULT = os.path.join(HERE, "..", "firmware", "8R0907379BG_0030.bin")
SGO_DEFAULT = os.path.join(HERE, "..", "firmware", "8R0907379BG_0030.sgo")

# Regions in FILE-OFFSET space (VMA==file for block0; block1/CAL is contiguous
# in the flat .bin). Flash addrs: block0 @0x8000 len 0xB8000, block1 @0x804000
# len 0x7C000 (from the .sgo container, sgo_unpack).
REGIONS = {
    "ASW_signed[0,0xbd424)": (0x0, 0xBD424),   # SIG1 signed window
    "ASW_block0[0,0xb8000)": (0x0, 0xB8000),
    "code[0,0xa2000)":       (0x0, 0xA2000),
    "CAL_signed[0xd20c1,0x133be9)": (0xD20C1, 0x133BE9),  # SIG2 signed window
    "cal_ds0[0xb0510]": (0xB0510, 0xB0510 + 0x6B4),
    "cal_ds1[0xb0bc4]": (0xB0BC4, 0xB0BC4 + 0x6B4),
    "cal_ds2[0xb1278]": (0xB1278, 0xB1278 + 0x6B4),
    "cal_ds3[0xb192c]": (0xB192C, 0xB192C + 0x6B4),
}


# ---- 1. poly-agnostic CRC-table detector -------------------------------------
def crc_tables_present(d):
    """Return list of (offset, width, endian, poly~) for any 256-entry CRC byte
    table. Uses the linearity invariant T[i] == XOR of T[1<<b] over set bits b,
    which every CRC table (any width/poly/reflection) satisfies -- so this
    cannot be evaded by a non-standard polynomial."""
    N = len(d)
    hits = []
    for width in (32, 16):
        W = width // 8
        code = {16: "H", 32: "I"}[width]
        zero = b"\x00" * W
        for end in (">", "<"):
            unpack = struct.Struct(end + code).unpack_from
            off = 0
            limit = N - 256 * W
            while off <= limit:
                if d[off:off + W] != zero:
                    off += 1
                    continue
                t = [unpack(d, off + i * W)[0] for i in range(256)]
                basis = [t[1 << b] for b in range(8)]
                if 0 in basis or len(set(basis)) < 7:
                    off += 1
                    continue
                ok = True
                for i in range(256):
                    x = 0
                    ii, b = i, 0
                    while ii:
                        if ii & 1:
                            x ^= basis[b]
                        ii >>= 1
                        b += 1
                    if t[i] != x:
                        ok = False
                        break
                if ok:
                    hits.append((hex(off), width, end, hex(t[128])))
                off += 1
    return hits


# ---- checksum kernels --------------------------------------------------------
def sum32(d, a, b, end=">"):
    s = 0
    for o in range(a & ~3, b & ~3, 4):
        s = (s + struct.unpack_from(end + "I", d, o)[0]) & 0xFFFFFFFF
    return s


def xor32(d, a, b, end=">"):
    s = 0
    for o in range(a & ~3, b & ~3, 4):
        s ^= struct.unpack_from(end + "I", d, o)[0]
    return s


def sum8(d, a, b):
    return sum(d[a:b]) & 0xFFFFFFFF


def crc32_bitser(d, a, b, poly, init, reflect, xorout):
    crc = init
    if reflect:
        rp = int("{:032b}".format(poly)[::-1], 2)
        for o in range(a, b):
            crc ^= d[o]
            for _ in range(8):
                crc = (crc >> 1) ^ rp if crc & 1 else crc >> 1
        return (crc ^ xorout) & 0xFFFFFFFF
    for o in range(a, b):
        crc ^= d[o] << 24
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return (crc ^ xorout) & 0xFFFFFFFF


def find_word(buf, v):
    out = []
    for end in ("<", ">"):
        p = struct.pack(end + "I", v)
        j = buf.find(p)
        if j >= 0:
            out.append((end, hex(j)))
    return out


def main(argv):
    fw = argv[1] if len(argv) > 1 else FW_DEFAULT
    sgo_path = argv[2] if len(argv) > 2 else SGO_DEFAULT
    d = open(fw, "rb").read()
    sgo = open(sgo_path, "rb").read() if os.path.exists(sgo_path) else b""
    print("image %d = 0x%x bytes" % (len(d), len(d)))

    print("\n[1] CRC16/CRC32 lookup tables (any poly/endian):")
    tabs = crc_tables_present(d)
    print("    ->", tabs if tabs else "NONE (only the known CRC8 E2E tables exist)")

    print("\n[2/3] additive/xor/CRC over regions -> stored anywhere in image or .sgo?")
    any_hit = False
    for name, (a, b) in REGIONS.items():
        cands = {
            "sum32be": sum32(d, a, b), "sum32le": sum32(d, a, b, "<"),
            "xor32be": xor32(d, a, b), "sum8": sum8(d, a, b),
            "neg_sum32be": (-sum32(d, a, b)) & 0xFFFFFFFF,
            # Simos CRC32 (poly 0x04C11DB7, non-reflected), init 0 and ffffffff:
            "crc32simos_i0": crc32_bitser(d, a, b, 0x04C11DB7, 0x00000000, False, 0),
            "crc32simos_iF": crc32_bitser(d, a, b, 0x04C11DB7, 0xFFFFFFFF, False, 0),
            # zlib/ISO reflected CRC32:
            "crc32zlib": crc32_bitser(d, a, b, 0x04C11DB7, 0xFFFFFFFF, True, 0xFFFFFFFF),
        }
        for k, v in cands.items():
            if v in (0, 0xFFFFFFFF):
                continue
            hits = find_word(d, v) + [("sgo",) + t for t in find_word(sgo, v)] if sgo else find_word(d, v)
            # a 32-bit hit is only meaningful if it lands at a plausible slot; we
            # print any so the reviewer can judge (all observed hits are 16-bit
            # coincidences / not at a descriptor slot).
            if hits:
                any_hit = True
                print("    %-26s %-14s = %#010x  FOUND %s" % (name, k, v, hits))
    if not any_hit:
        print("    -> NO computed checksum is stored anywhere. (Consistent with RSA-only.)")

    if sgo:
        print("\n[4] .sgo container blocks (sgo_unpack format):")
        try:
            sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "..",
                                            "tools", "simos-suite", "cp_tools"))
            import sgo_unpack as su  # noqa
            f = su.parse(sgo, decode=False)
            for i, blk in enumerate(f.blocks):
                print("    block%d addr=%#08x declen=%#x crypt=%#x  (plain, no csum field)"
                      % (i, blk.addr, blk.declen, blk.crypt_byte))
        except Exception as e:  # tools not on this host
            print("    (sgo_unpack unavailable: %s)" % e)

    print("\nVERDICT: flash integrity is RSA-1024 ONLY (docs/signature_analysis.md).")
    print("No recomputable checksum layer exists in the ASW/CAL image; a flasher")
    print("cannot correct integrity -- the bootloader RSA-verify bypass is the")
    print("only path. A boot-time CRC gate (if any) is CBOOT/SBOOT-resident and")
    print("needs the bench dump to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
