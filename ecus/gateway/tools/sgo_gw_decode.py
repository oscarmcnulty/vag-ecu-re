#!/usr/bin/env python3
"""Decode an Audi B8 J533 gateway SGO flash container (crypt=0x01).

The gateway ships its flashdaten as a VAG "SGML Object File" whose single block
carries crypt byte 0x01. simos-suite labels crypt=0x01 "AES (key unknown)" and
walls it -- but for this LEAR B8 gateway that label is wrong. The payload is a
*multiplicative self-synchronising bit scrambler*, LSB-first, with the maximal
15-bit polynomial x^15 + x^14 + 1:

    descramble:  p[t] = c[t] XOR c[t-14] XOR c[t-15]      (bit index t, taps for t>=15)
    scramble:    c[t] = p[t] XOR c[t-14] XOR c[t-15]

How it was cracked (reproducible, no key/bench dump needed):
  1. a constant-input (erased-flash) region repeats with period 0x7FFF = 2^15-1
     -> a 15-bit LFSR governs it (and this rules out any 16-byte AES mode);
  2. Berlekamp-Massey on that region -> linear complexity 15 in LSB-first order
     (120 in MSB-first), fixing degree and bit endianness;
  3. a GF(2) solve on the zero-fill region returns taps [14,15];
  4. re-scrambling the recovered plaintext reproduces the ciphertext byte-for-byte,
     and erased flash decodes to clean 0x00.

Usage:
    python3 sgo_gw_decode.py <file.sgo> -o <plain.bin>   # write descrambled image
    python3 sgo_gw_decode.py <file.sgo> --verify         # byte-exact round-trip check

The plaintext is a raw MCU flash image whose block base address is reported
(0x8010 for 8R0907468_0060). It is firmware-derived -> keep it out of git.
"""
import argparse
import struct
import sys

MAGIC = b"SGML Object File"


def _w32(d, p):
    return struct.unpack_from("<I", d, p)[0]


def _w24(d, p):
    return struct.unpack(">I", b"\x00" + d[p:p + 3])[0]


def _xorstr(data):
    out = []
    for b in data:
        if b == 0:
            break
        out.append(b ^ 0xFF)
    return bytes(out).decode("ascii", errors="replace")


def parse_container(data):
    """Return dict with part/version and the single flash block's fields + raw blob."""
    if data[:len(MAGIC)] != MAGIC:
        raise ValueError("not an SGML Object File (bad magic)")
    idx = _w32(data, 0x19)
    part = _xorstr(data[idx:idx + 260]).replace(".sgm", "").replace(".sgo", "")
    ver = _xorstr(data[idx + 260:idx + 265])
    meta_start = _w32(data, 0x29)
    meta_len = _w32(data, meta_start)
    end = _w32(data, 0x2D)
    pos = meta_start + meta_len + 4
    blocks = []
    while pos + 0x19 <= end:
        addr = _w24(data, pos)
        crypt = data[pos + 3]
        declen = _w24(data, pos + 4)
        blob_len = _w32(data, pos + 0x15)
        blob = data[pos + 0x19: pos + 0x19 + blob_len]
        blocks.append(dict(addr=addr, crypt=crypt, declen=declen,
                           blob_len=blob_len, blob=blob))
        pos += 0x19 + blob_len
    return dict(part=part, ver=ver, blocks=blocks)


# ── the crypt=0x01 scrambler (pure-python, no numpy dependency) ────────────────

def _unpack_lsb(data):
    bits = bytearray()
    for b in data:
        for i in range(8):
            bits.append((b >> i) & 1)
    return bits


def _pack_lsb(bits):
    out = bytearray(len(bits) // 8)
    for t, bit in enumerate(bits):
        if bit:
            out[t >> 3] |= (1 << (t & 7))
    return bytes(out)


def descramble(blob):
    """p[t] = c[t] ^ c[t-14] ^ c[t-15], LSB-first."""
    c = _unpack_lsb(blob)
    p = bytearray(c)
    n = len(c)
    for t in range(15, n):
        p[t] ^= c[t - 14] ^ c[t - 15]
    return _pack_lsb(p)


def scramble(image):
    """Inverse: c[t] = p[t] ^ c[t-14] ^ c[t-15], LSB-first."""
    p = _unpack_lsb(image)
    c = bytearray(len(p))
    n = len(p)
    for t in range(n):
        v = p[t]
        if t >= 15:
            v ^= c[t - 14] ^ c[t - 15]
        c[t] = v
    return _pack_lsb(c)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sgo")
    ap.add_argument("-o", "--out", help="write descrambled flash image here")
    ap.add_argument("--verify", action="store_true",
                    help="round-trip: scramble(descramble(blob)) == blob")
    a = ap.parse_args(argv)

    data = open(a.sgo, "rb").read()
    c = parse_container(data)
    print(f"part    : {c['part']}")
    print(f"version : {c['ver']}")
    for i, b in enumerate(c["blocks"]):
        print(f"block {i} : addr=0x{b['addr']:06X} crypt=0x{b['crypt']:02X} "
              f"len=0x{b['blob_len']:X} (declen=0x{b['declen']:X})")
    blk = c["blocks"][0]
    if blk["crypt"] != 0x01:
        print(f"warning: block crypt is 0x{blk['crypt']:02X}, not 0x01 -- "
              "this tool only inverts the crypt=0x01 gateway scrambler",
              file=sys.stderr)

    plain = descramble(blk["blob"])
    print(f"\ndescrambled {len(plain)} bytes; flash base 0x{blk['addr']:06X}, "
          f"end 0x{blk['addr'] + len(plain):06X}")

    if a.verify:
        ok = scramble(plain) == blk["blob"]
        print("round-trip byte-exact:", ok)
        if not ok:
            return 1
    if a.out:
        open(a.out, "wb").write(plain)
        print(f"wrote -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
