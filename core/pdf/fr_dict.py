#!/usr/bin/env python3
"""Extract the Funktionsrahmen data dictionary from the index built by fr_index.py.

The FR documents every constant / map / variable in a "Name | Mode | Hex. limits |
Phys. limits | Resol. | Unit" table on the owning function's page, under one of the
section headings `Data definition:`, `Input data:`, `Output data:`, `Calibration
data:`.  Those tables are the authoritative "where in the FR is X" answer -- the
alphabetical index (pp.49-575) points at the same rows, but it is typeset in two
columns that pdftotext interleaves unreliably, so we read the tables directly and
get the page number for free.

For a calibration object the table also carries what we need to *pin it to a binary
map*: resolution, unit, and (for maps/curves) the breakpoint-distribution labels
(`LDPM_*`) with their own count / range / resolution.  That is the join key against
`maps/a2l_catalog.csv` -- e.g. FR `IP_TQI_REF` = 0.03125 Nm over LDPM_N_32_1_TQDR
(16 bp, 32 rpm) x LDPM_MAF_1_TQDR (12 bp, 0.0211948 mg/stk) matches the A2L object
`ip_tqi_ref` = 16x12, 0.03125*X Nm.

pdftotext linearises a table page column-wise, so numeric cells are sometimes pooled
after the label block instead of staying on their row.  The label, its section, its
description (the last prose line before the next label) and the page are reliable;
`resol`/`unit` are recovered only when the row survived intact, and are reported as
best-effort.  `cells` keeps the raw cell run so a caller can re-derive them.

Outputs (in OUTDIR):
  fr_dict.jsonl   one JSON record per definition:
                  {label, page, fr_page, chapter, part, section, desc,
                   mode, hex, phys, resol, unit, axes[], cells[]}

Usage: fr_dict.py OUTDIR [--out fr_dict.jsonl]

Then query it with fr_lookup.py.
"""
import argparse, json, os, re

LABEL = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
# array objects are typeset "IP_MFF_COR [NC_CBK_IN_NR]" -- the suffix is the dimension
ARRAY = re.compile(r"^([A-Z][A-Z0-9_]*)\s*\[\s*([A-Z0-9_]+)\s*\]$")
HEADER_WORDS = {
    "HEX", "PHYS", "RESOL", "NAME", "MODE", "UNIT", "CHAPTER", "PART",
    "FUNCTION", "DESCRIPTION", "IF", "THEN", "ELSE", "ENDIF", "AND", "OR", "NOT",
    "TRUE", "FALSE", "NOTE", "A4",
}
SECTIONS = {
    "data definition:": "definition",
    "calibration data:": "calibration",
    "input data:": "input",
    "output data:": "output",
    "local data:": "local",
    "internal data:": "internal",
    "application data:": "calibration",
}
MODE = re.compile(r"^(O|V|M|I|O/V|O/M|V/M|O/V/M)$")
HEXLIM = re.compile(r"^[0-9A-F]+\s*\.{2,3}\s*[0-9A-F]+H?$|^[0-9A-F]{1,8}H$")
NUMRANGE = re.compile(r"^[-+]?[0-9][0-9.eE+-]*\s*\.{2,3}\s*[-+]?[0-9][0-9.eE+-]*$")
NUM = re.compile(r"^[-+]?[0-9][0-9.]*(?:[eE][-+]?[0-9]+)?$")
UNIT = re.compile(
    r"^(-|km/h|mph|m/s\^?2|m/s2|Nm|Nm/s|N|s|ms|us|%|C|K|deg\s*CR|Deg\s*CR|deg|rpm|RPM|"
    r"1/min|mg/stk|mg|g/s|kg/h|MPa|kPa|hPa|bar|V|mV|A|mA|Hz|Ohm|l/h|ml|norm|Gear|bit|"
    r"Bit|counts|cnt|factor|ratio)$", re.I)
# breakpoint-distribution / axis labels
AXIS = re.compile(r"^(LDPM|LDPX|DPM|BP)_[A-Z0-9_]+$")
BOILER = (
    "Transmittal, reproduction", "as well as utilisation", "without express",
    "for payment of damages", "of a utility model", "Copyright ( C ) Continental",
    "Designed by", "Baseline", "Document key", "Regensburg",
)
DROP_EXACT = {"Chapter", "Part", "Name", "Mode", "Hex. limits", "Phys. limits",
              "Resol.", "Unit", "Date", "File", "Project", "Pages", "Page", "of",
              "where", "with"}


def split_label(line):
    """-> (label, dim) for a table Name cell, else (None, '')."""
    m = ARRAY.match(line)
    if m:
        line, dim = m.group(1), m.group(2)
    else:
        dim = ""
    if LABEL.match(line) and line not in HEADER_WORDS:
        return line, dim
    return None, ""


def is_label(line):
    return split_label(line)[0] is not None


def is_cell(line):
    return bool(MODE.match(line) or HEXLIM.match(line) or NUMRANGE.match(line)
                or NUM.match(line) or UNIT.match(line))


def is_prose(line):
    if is_cell(line):
        return False
    return bool(re.search(r"[a-z]{3}", line))


def clean(text):
    out = []
    for raw in text.splitlines():
        l = raw.strip()
        if not l or l in DROP_EXACT:
            continue
        if any(l.startswith(b) for b in BOILER):
            continue
        out.append(l)
    return out


def page_titles(lines):
    """Chapter / Part titles: the prose lines before the first table heading."""
    head = []
    for l in lines[:8]:
        if l.lower() in SECTIONS or l.rstrip(":").lower() + ":" in SECTIONS:
            break
        if is_prose(l) and not is_label(l):
            head.append(l)
    return (head[0] if head else "", head[1] if len(head) > 1 else "")


def parse_page(page, text):
    lines = clean(text)
    chapter, part = page_titles(lines)

    # walk the page, tracking which table we are inside
    section = ""
    marks = []           # (index, label) and section switches
    for i, l in enumerate(lines):
        key = l.lower()
        if key in SECTIONS:
            section = SECTIONS[key]
            continue
        lab, dim = split_label(l)
        if lab:
            marks.append((i, lab, section, dim))

    out = []
    for n, (i, label, sect, dim) in enumerate(marks):
        # axis labels belonging to a map: LDPM_* rows that directly follow it
        axes = []
        k = n + 1
        while k < len(marks) and AXIS.match(marks[k][1]):
            axes.append(marks[k][1])
            k += 1
        # a map's description sits after its axis rows, so the chunk spans them
        end = marks[k][0] if k < len(marks) else len(lines)
        chunk = lines[i + 1:end]

        mode = chunk[0] if chunk and MODE.match(chunk[0]) else ""
        hexlim = next((c for c in chunk[:3] if HEXLIM.match(c)), "")
        phys = next((c for c in chunk[:6] if NUMRANGE.match(c)), "")
        # a row that survived intact ends ... <resol> <unit>
        cells = [c for c in chunk if is_cell(c)]
        resol = unit = ""
        for j, c in enumerate(cells[:-1]):
            if NUM.match(c) and UNIT.match(cells[j + 1]):
                resol, unit = c, cells[j + 1]
                break
        prose = [c for c in chunk if is_prose(c)]
        desc = prose[-1] if prose else ""

        if AXIS.match(label):
            continue  # emitted as an axis of its owner, not a standalone object

        out.append({
            "label": label, "page": page, "fr_page": page - 1,
            "chapter": chapter, "part": part, "section": sect, "desc": desc,
            "mode": mode, "hex": hexlim, "phys": phys, "resol": resol,
            "unit": unit, "dim": dim, "axes": axes, "cells": cells[:10],
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--out", default="fr_dict.jsonl")
    a = ap.parse_args()

    src = os.path.join(a.outdir, "fr_pages.jsonl")
    dst = os.path.join(a.outdir, a.out)
    n_pages = n_def = 0
    with open(dst, "w") as w:
        for line in open(src):
            r = json.loads(line)
            if "Hex. limits" not in r["text"] or "Resol." not in r["text"]:
                continue
            n_pages += 1
            for rec in parse_page(r["page"], r["text"]):
                w.write(json.dumps(rec) + "\n")
                n_def += 1
    print(f"{n_pages} definition pages -> {n_def} definitions -> {dst}")


if __name__ == "__main__":
    main()
