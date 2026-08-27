#!/usr/bin/env python3
"""Extract a plaintext firmware image from a VAG '.sgo' (SGML Object File) container.

The container is the same one the Bosch ESP8 ABS uses (ecus/esp8): the WHOLE file is
XOR-0xFF obfuscated and the first 0x200 bytes are a header (part-number + software
version strings, section table, and the SA2 seed/key script). Firmware body = the
XOR-inverted bytes from 0x200 to EOF, mapped 1:1 to the CPU load base.

  python3 extract_sgo.py 8K0907144L__0720.sgo -o firmware/8K0907144L_0720.bin

Verified on 8K0907144L (Audi B8 EPS, TriCore LE, load base 0x80000000): the header
decodes to the part number '8K0907144L__0720.sgm' and version '0720', and the body's
32-bit words self-reference at 0x80000000 (code) / 0x40000000 (RAM) little-endian.
No decryption codec is involved -- the SA2 '22' byte is inside the seed/key bytecode
(on-car UDS access), not a container cipher.
"""
import argparse, sys

HDR_LEN = 0x200

def load(path):
    raw = open(path, "rb").read()
    if raw[:4] != b"SGML":
        sys.exit(f"{path}: not an SGML Object File (magic={raw[:4]!r})")
    inv = bytes(b ^ 0xFF for b in raw)
    return raw, inv

def sa2_script(raw):
    ln = raw[0x1b7]
    return raw[0x1bb:0x1bb + ln]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sgo")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    raw, inv = load(a.sgo)
    # decoded header identity strings
    ident = inv[0x30:0x50].split(b"\x00")[0].decode("latin1", "replace")
    body = inv[HDR_LEN:]
    open(a.out, "wb").write(body)
    print(f"container : {a.sgo}")
    print(f"identity  : {ident}")
    print(f"SA2 script: {sa2_script(raw).hex().upper()}")
    print(f"body      : 0x{len(body):x} bytes -> {a.out} (load @0x80000000)")

if __name__ == "__main__":
    main()
