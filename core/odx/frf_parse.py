#!/usr/bin/env python3
"""VAG flash-container parsing: ODX-F / FRF / SGML flashware.

VW/Audi ship ECU software as ODX-F (.odx-f / packed into .frf). An FRF is a
container around ODX-F describing flash blocks (logical address, size, data,
compression/encryption, checksums). This module sketches the parse so you can
extract the raw block images and feed them to core/ghidra/ and core/diff/.

Reality check by ECU generation:
  - Simos8.5 / MED17 : ODX-F blocks, may be LZMA/zlib-ish compressed, no per-block
                       AES. Integrity = flash-loader CRC + boot RSA.
  - Simos18          : flash blocks are AES-encrypted; the key/flow is implemented
                       in bri3d/VW_Flash. For simos18, DELEGATE to VW_Flash rather
                       than reimplementing decryption here.

This is a skeleton: FRF/ODX-F is XML/SGML-ish with embedded binary; a full parser
is non-trivial. Start by detecting the container and listing blocks.
"""
import argparse, re, sys


def sniff(buf: bytes) -> str:
    head = buf[:64]
    if head[:4] == b"FRF\x00" or b"FRF" in head[:16]:
        return "frf"
    if b"<ODX" in buf[:4096] or b"ODX-F" in buf[:4096] or head[:5] == b"<?xml":
        return "odx-f"
    if head[:2] == b"PK":
        return "zip/odx-bundle"
    return "unknown/raw"


def list_blocks_odx(buf: bytes):
    """Very rough: surface logical-block hints from an ODX-F XML body.
    Replace with a real ODX parser (e.g. odxtools) for production use."""
    text = buf.decode("latin-1", "replace")
    blocks = []
    for m in re.finditer(r'(?i)<(?:flash-?data|datablock|block)[^>]*>', text):
        blocks.append((m.start(), m.group(0)[:120]))
    return blocks


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("container")
    a = ap.parse_args()
    buf = open(a.container, "rb").read()
    kind = sniff(buf)
    print(f"# {a.container}: {len(buf)} bytes, detected: {kind}")
    if kind == "odx-f":
        for off, tag in list_blocks_odx(buf):
            print(f"  {off:#010x}  {tag}")
    elif kind == "frf":
        print("  FRF container: unwrap to ODX-F first (TODO: FRF header parse).")
    else:
        print("  Not a recognized VAG container. For simos18 encrypted flashware, "
              "use bri3d/VW_Flash to decrypt/extract blocks.", file=sys.stderr)


if __name__ == "__main__":
    main()
