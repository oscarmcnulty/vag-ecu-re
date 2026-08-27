#!/usr/bin/env python3
"""Extract flash blocks from a decrypted ODX-F container (the .odx inside an .frf).

Usage:  odx_extract.py <file.odx> [-o OUTDIR]

An ODX-F holds <FLASHDATA> elements (hex payload, with a DATAFORMAT and an
ENCRYPT-COMPRESS-METHOD byte) referenced by <DATABLOCK> elements that carry the
segment list (SOURCE-START-ADDRESS = the UDS 0x34 block id / logical address, and
UNCOMPRESSED-SIZE). We dump one file per DATA/DRIVER block, named by its
short-name, plus a manifest line per block.

Nothing is decrypted here: VAG ABS/ESP payloads are the plain SGO/SGML flashware
(often whole-image XOR 0xFF; see ecus/esp8/docs/RE_findings.md). Sniff the output.
"""
import argparse, pathlib, re, sys

RE_FLASHDATA = re.compile(
    r'<FLASHDATA[^>]*ID="[^"]*\.(?P<sn>\w+)".*?'
    r'(?:<DATAFORMAT SELECTION="(?P<fmt>[^"]*)"/>)?.*?'
    r'(?:<ENCRYPT-COMPRESS-METHOD[^>]*>(?P<ecm>[0-9A-Fa-f]*)</ENCRYPT-COMPRESS-METHOD>)?.*?'
    r'<DATA>(?P<data>[0-9A-Fa-f\s]*)</DATA>', re.S)
RE_DATABLOCK = re.compile(
    r'<DATABLOCK ID="[^"]*\.(?P<sn>\w+)" TYPE="(?P<type>\w+)">(?P<body>.*?)</DATABLOCK>', re.S)
RE_SEG = re.compile(r'<SOURCE-START-ADDRESS>([0-9A-Fa-f]+)</SOURCE-START-ADDRESS>\s*'
                    r'<UNCOMPRESSED-SIZE>(\d+)</UNCOMPRESSED-SIZE>')
RE_FDREF = re.compile(r'FLASHDATA-REF ID-REF="[^"]*\.(\w+)"')
RE_IDENT = re.compile(r'<SHORT-NAME>(EI_\w+)</SHORT-NAME>.*?<LONG-NAME>([^<]*)</LONG-NAME>'
                      r'(?P<vals>.*?)</EXPECTED-IDENT>', re.S)
RE_VAL = re.compile(r'<IDENT-VALUE[^>]*>([^<]*)</IDENT-VALUE>')


def parse(path):
    text = pathlib.Path(path).read_bytes().decode("latin-1")
    fd = {m.group("sn"): (bytes.fromhex(re.sub(r"\s", "", m.group("data"))),
                          m.group("fmt"), m.group("ecm"))
          for m in RE_FLASHDATA.finditer(text)}
    blocks = []
    for m in RE_DATABLOCK.finditer(text):
        ref = RE_FDREF.search(m.group("body"))
        segs = [(int(a, 16), int(n)) for a, n in RE_SEG.findall(m.group("body"))]
        blocks.append((m.group("sn"), m.group("type"), ref.group(1) if ref else None, segs))
    idents = [(m.group(2), RE_VAL.findall(m.group("vals"))) for m in RE_IDENT.finditer(text)]
    return fd, blocks, idents


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("odx")
    ap.add_argument("-o", "--outdir", default=".")
    a = ap.parse_args()
    fd, blocks, idents = parse(a.odx)
    out = pathlib.Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    print(f"# {a.odx}")
    for name, vals in idents:
        print(f"  ident  {name:38} {', '.join(v.strip() for v in vals)}")
    for sn, typ, ref, segs in blocks:
        if typ == "ERASE" or ref not in fd:
            continue
        data, fmt, ecm = fd[ref]
        addr = segs[0][0] if segs else 0
        size = segs[0][1] if segs else len(data)
        path = out / f"{sn}_{addr:02X}.bin"
        path.write_bytes(data)
        flag = "" if len(data) == size else f"  (!! declared size {size})"
        print(f"  {sn:14} {typ:7} blockid={addr:#04x} fmt={fmt} ecm={ecm} "
              f"len={len(data)}{flag} -> {path.name}")


if __name__ == "__main__":
    main()
