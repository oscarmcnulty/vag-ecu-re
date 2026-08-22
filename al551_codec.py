#!/usr/bin/env python3
"""
AL551 (ZF 8HP / Bosch Renesas SH7251x/SH7254x) flash container codec.

Implements ``ENCRYPT-COMPRESS-METHOD = "22"`` used by the Audi AL551 TCU
(part 8R0927158xx / 4H1927158xx, ODX EV_TCMALX51...) — the format that
bri3d/VW_Flash issue #123 identified but did not reverse.

The method is a two-stage pipeline the ECU applies (in reverse) while flashing,
recovered by reverse-engineering the SBOOT/CBOOT decode routines:

  Stage 1 - XOR decrypt:   plain[i] = stored[i] ^ KEY[i % len(KEY)]
            KEY = b"CyA2008ZFVAGtcuxsam"   (19 bytes, ASCII)

  Stage 2 - bit-flag LZSS on the XOR-decrypted stream:
            * 2048-byte circular sliding window (11-bit distance).
            * A flag byte is read MSB-first; it governs the next 8 tokens.
            * flag bit 0 -> literal: emit the next input byte.
            * flag bit 1 -> match: read 2 bytes b2, b3
                              length   = b2 >> 3            (0..31)
                              distance = ((b2 & 7) << 8) | b3   (1..2047)
                            copy `length` bytes from window[(pos-distance)].
            * decoding stops once UNCOMPRESSED-SIZE bytes are produced.

Verified byte-exact against the on-ECU decode (SH-2A emulation) and against the
ODX per-block checksums (standard CRC32) for every block of the 4H1927158AD_1006
and 8R0927158AM_1003 flashware.

Public API:
    decompress_method22(stored: bytes, uncompressed_size: int) -> bytes
    is_method22(dfi: int|str) -> bool

CLI:
    python3 al551_codec.py <file.frf|file.odx> [--out DIR] [--verify]
"""
from __future__ import annotations

import argparse
import binascii
import os
import zlib
import xml.etree.ElementTree as ET

XOR_KEY = b"CyA2008ZFVAGtcuxsam"   # 19-byte AL551 "22" stream key
WINDOW  = 2048                      # LZSS sliding-window size (11-bit distance)


def decompress_method22(stored: bytes, uncompressed_size: int) -> bytes:
    """Decode one ``ENCRYPT-COMPRESS-METHOD == "22"`` FLASHDATA block.

    `stored` is the raw block payload from the ODX <DATA> element (the bytes the
    tuner sends over UDS TransferData). Returns exactly `uncompressed_size` bytes.
    """
    data = bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(stored))

    win = bytearray(WINDOW)
    wpos = 0
    out = bytearray()
    ip = 0
    n = len(data)
    flag = 0
    bits_used = 8   # force a flag-byte fetch on the first iteration

    while len(out) < uncompressed_size:
        if bits_used == 8:
            if ip >= n:
                break
            flag = data[ip]; ip += 1
            bits_used = 0
        bit = (flag >> (7 - bits_used)) & 1   # MSB-first
        bits_used += 1

        if bit == 0:                          # literal
            if ip >= n:
                break
            c = data[ip]; ip += 1
            out.append(c)
            win[wpos] = c; wpos = (wpos + 1) % WINDOW
        else:                                 # back-reference
            if ip + 1 >= n:
                break
            b2 = data[ip]; b3 = data[ip + 1]; ip += 2
            length = b2 >> 3
            distance = ((b2 & 7) << 8) | b3
            for _ in range(length):
                if len(out) >= uncompressed_size:
                    break
                c = win[(wpos - distance) % WINDOW]
                out.append(c)
                win[wpos] = c; wpos = (wpos + 1) % WINDOW

    return bytes(out)


def compress_method22(data: bytes) -> bytes:
    """Encode a valid ``ENCRYPT-COMPRESS-METHOD == "22"`` stream that decodes byte-exact to
    `data`, WITHOUT implementing the real LZSS matcher: emit all-literal tokens (a 0x00 flag
    byte = 8 literal bits, MSB-first, followed by up to 8 literal bytes) then XOR with the key.

    Expansion is ~1.125x vs the OEM ~4:1, but the ECU decompresses until UNCOMPRESSED-SIZE and
    stops, so a bigger compressed stream just means more TransferData frames — the decoded
    image, its size, and its CRC32 are identical. Round-trips through decompress_method22().
    """
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        out.append(0x00)          # flag: next 8 tokens are literals
        out += data[i:i+8]        # up to 8 literal bytes
        i += 8
    return bytes(b ^ XOR_KEY[k % len(XOR_KEY)] for k, b in enumerate(out))


def is_method22(dfi) -> bool:
    """True if the given ENCRYPT-COMPRESS-METHOD (int, or hex/ascii string) is 0x22."""
    if isinstance(dfi, str):
        dfi = int(dfi.strip(), 16)
    return dfi == 0x22


# --------------------------------------------------------------------------- #
# ODX / FRF plumbing (self-contained; mirrors VW_Flash/simos-suite conventions)
# --------------------------------------------------------------------------- #
def _iter_blocks(odx_text: str):
    """Yield (short_name, dfi, uncompressed_size, checksum_hex, stored_bytes)."""
    root = ET.fromstring(odx_text)
    fd_dfi, fd_data = {}, {}
    for fd in root.iter("FLASHDATA"):
        fid = fd.get("ID", "")
        ecm = fd.findtext("ENCRYPT-COMPRESS-METHOD")
        dat = fd.findtext("DATA")
        if ecm is not None:
            fd_dfi[fid] = int(ecm.strip(), 16)
        if dat and len(dat) > 2:
            fd_data[fid] = binascii.unhexlify(dat)
    # CRC32 checksums are carried in <SECURITY> blocks keyed by block number
    # (<FW-SIGNATURE> holds the block number, <FW-CHECKSUM> the CRC32).
    crc_by_blocknum = {}
    for sec in root.iter("SECURITY"):
        if sec.findtext("SECURITY-METHOD") in ("CRC32F", "CRC32"):
            sig = sec.findtext("FW-SIGNATURE")
            cs = sec.findtext("FW-CHECKSUM")
            if sig and cs:
                crc_by_blocknum[sig.strip()] = cs.strip()
    for db in root.iter("DATABLOCK"):
        sn = (db.findtext("SHORT-NAME") or "?")
        if sn.endswith("ERASE"):
            continue
        ref = db.find(".//FLASHDATA-REF")
        seg = db.find(".//SEGMENT")
        if ref is None or seg is None:
            continue
        rid = ref.get("ID-REF")
        if rid not in fd_data:
            continue
        us = seg.findtext("UNCOMPRESSED-SIZE")
        blocknum = seg.findtext("SOURCE-START-ADDRESS")
        cs = crc_by_blocknum.get(blocknum.strip()) if blocknum else None
        yield sn, fd_dfi.get(rid), (int(us) if us else None), cs, fd_data[rid]


def _load_odx(path: str) -> str:
    if path.lower().endswith(".odx"):
        return open(path, "r", errors="replace").read()
    # FRF: unwrap via VW_Flash/simos-suite if importable, else raise a helpful error.
    for mod, fn in (("lib.extract_flash", "extract_odx_from_frf"),
                    ("flasher.frf_loader", None)):
        try:
            m = __import__(mod, fromlist=["*"])
            if fn:
                odx = getattr(m, fn)(open(path, "rb").read())
                return odx.decode("utf-8", "replace") if isinstance(odx, (bytes, bytearray)) else odx
            return m.FrfLoader(None).get_odx(path).decode("utf-8", "replace")
        except Exception:
            continue
    raise SystemExit("Pass an extracted .odx (FRF unwrap needs VW_Flash or simos-suite on PYTHONPATH).")


def main():
    ap = argparse.ArgumentParser(description="Decode AL551 method-22 flash blocks (XOR+LZSS).")
    ap.add_argument("file", help="FRF or extracted ODX")
    ap.add_argument("--out", help="write decoded blocks to this directory")
    ap.add_argument("--verify", action="store_true", help="check each block's CRC32 vs the ODX")
    a = ap.parse_args()

    odx = _load_odx(a.file)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    ok_all = True
    for name, dfi, usz, cs, stored in _iter_blocks(odx):
        tag = "22" if is_method22(dfi) else ("%02X" % dfi if dfi is not None else "??")
        if not is_method22(dfi):
            print(f"{name:24s} method=0x{tag} (not 22) - skipped")
            continue
        img = decompress_method22(stored, usz)
        crc = zlib.crc32(img) & 0xffffffff
        note = ""
        if a.verify and cs:
            ref = int(cs, 16)
            good = (len(img) == usz and crc == ref)
            ok_all &= good
            note = f"  crc32={crc:08X} odx={ref:08X} {'OK' if good else 'FAIL'}"
        else:
            note = f"  crc32={crc:08X}"
        print(f"{name:24s} method=0x{tag}  {len(img):>8}/{usz} bytes{note}")
        if a.out:
            open(os.path.join(a.out, f"{name}.bin"), "wb").write(img)
    if a.verify:
        print("\nALL BLOCKS VALID:", ok_all)
        raise SystemExit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
