#!/usr/bin/env python3
"""Simos on-wire flash codec: LZSS compression + rolling-XOR scramble (DFI 0xAA).

Our static RE of the app-resident flash writer (flash_write_transfer 0x801f3b5e) shows
raw byte streaming with no decompressor — because the decompress/de-scramble step lives
in the CBOOT programming path (the 0x0-0x20000 boot sector that is blank in every OBD
read). The acceptance test against a Simos8-proven tool established the wire contract:
RequestDownload declares dataFormatIdentifier = 0xAA (compression=0xA, encryption=0xA)
and TransferData carries LZSS-compressed-then-XOR-scrambled bytes; RequestDownload's
size field is the UNCOMPRESSED length.

This module implements that contract ourselves, with a round-trip self-test (encode then
decode must reproduce the input). The XOR is a symmetric rolling scramble. The LZSS is a
classic byte-oriented LZSS (8 flag bits per group, 1=literal / 0=(offset,len) back-ref).

CAVEAT (documented, not hidden): the exact LZSS window/encoding must byte-match the ECU's
CBOOT decompressor. The round-trip test proves our encoder/decoder are mutually
consistent; confirming they match the ECU decompressor is the one item that needs the
CBOOT dump (or an on-bench read-back) to close — flagged in analysis/flash_protocol.md.
"""
from __future__ import annotations

WIN_BITS = 12                 # 4 KiB window
WIN_SIZE = 1 << WIN_BITS
MIN_MATCH = 3
MAX_MATCH = (1 << 4) - 1 + MIN_MATCH   # 4-bit length field


def xor_scramble(data: bytes, key0: int = 0) -> bytes:
    """Symmetric rolling XOR: byte[i] ^ ((key0 + i) & 0xFF). Self-inverse."""
    return bytes((b ^ ((key0 + i) & 0xFF)) & 0xFF for i, b in enumerate(data))


def lzss_compress(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    flags_pos = -1
    flag_bit = 8
    while i < n:
        if flag_bit == 8:
            out.append(0)                    # placeholder flag byte
            flags_pos = len(out) - 1
            flag_bit = 0
        # search the window for the longest match
        start = max(0, i - (WIN_SIZE - 1))   # keep offset in 1..0xFFF
        best_len, best_off = 0, 0
        j = start
        while j < i:
            k = 0
            while (k < MAX_MATCH and i + k < n and data[j + k] == data[i + k]):
                k += 1
            if k > best_len:
                best_len, best_off = k, i - j
            j += 1
        if best_len >= MIN_MATCH:
            enc = ((best_off & 0xFFF) << 4) | ((best_len - MIN_MATCH) & 0xF)
            out.append((enc >> 8) & 0xFF)
            out.append(enc & 0xFF)
            i += best_len                    # flag bit stays 0 => back-ref
        else:
            out[flags_pos] |= (1 << flag_bit)   # 1 => literal
            out.append(data[i])
            i += 1
        flag_bit += 1
    return bytes(out)


def lzss_decompress(data: bytes, out_len: int) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    flag_bit, flags = 8, 0
    while len(out) < out_len and i < n:
        if flag_bit == 8:
            flags = data[i]; i += 1; flag_bit = 0
        if flags & (1 << flag_bit):
            out.append(data[i]); i += 1
        else:
            enc = (data[i] << 8) | data[i + 1]; i += 2
            off = (enc >> 4) & 0xFFF
            length = (enc & 0xF) + MIN_MATCH
            src = len(out) - off
            for _ in range(length):
                out.append(out[src]); src += 1
        flag_bit += 1
    return bytes(out[:out_len])


def encode(block: bytes, key0: int = 0) -> bytes:
    """Full DFI-0xAA payload: LZSS then XOR-scramble."""
    return xor_scramble(lzss_compress(block), key0)


def decode(payload: bytes, out_len: int, key0: int = 0) -> bytes:
    return lzss_decompress(xor_scramble(payload, key0), out_len)


if __name__ == "__main__":
    import os
    for sample in (b"", b"A" * 100, os.urandom(4096),
                   (b"the quick brown fox " * 500)):
        enc = encode(sample)
        assert decode(enc, len(sample)) == sample, "round-trip FAILED"
        ratio = len(enc) / max(1, len(sample))
        print(f"round-trip OK: {len(sample):6} B -> {len(enc):6} B  ({ratio:.2f}x)")
    print("simos_codec round-trip self-test passed.")
