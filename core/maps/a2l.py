#!/usr/bin/env python3
"""Minimal ASAP2 (.a2l) reader for the Simos8.5 pipeline.

`simos85.a2l` is the canonical, hand-edited source of truth for calibration
objects (maps/curves/constants + provenance). Downstream generators
(`a2l_to_symbols.py`, `a2l_catalog.py`) consume the A2L through this module so
there is exactly one A2L parser in the tree.

This parses the ASAP2 subset we emit — COMPU_METHOD (LINEAR / identity RAT_FUNC),
RECORD_LAYOUT, AXIS_PTS, CHARACTERISTIC (VALUE/CURVE/MAP) — not the full standard.
It is a nested `/begin BLOCK ... /end BLOCK` format (not XML): we tokenize with
quoted strings kept intact, build the block tree, then interpret known blocks.
"""
import re

# A2L data type keyword -> element width in bits (what RECORD_LAYOUT/AXIS_PTS use).
DT_BITS = {"UBYTE": 8, "SBYTE": 8, "UWORD": 16, "SWORD": 16,
           "ULONG": 32, "SLONG": 32, "FLOAT32_IEEE": 32}

_TOKEN = re.compile(r'"[^"]*"|/begin|/end|\S+')


class Node:
    """One /begin..../end block: `type`, positional `tokens`, child `blocks`."""
    __slots__ = ("type", "tokens", "blocks")

    def __init__(self, type_):
        self.type = type_
        self.tokens = []      # bare tokens (strings; quotes stripped) before/after children
        self.blocks = []      # nested Node children

    def find(self, type_):
        for b in self.blocks:
            if b.type == type_:
                return b
        return None

    def findall(self, type_):
        return [b for b in self.blocks if b.type == type_]


def _tok(text):
    for m in _TOKEN.finditer(text):
        t = m.group(0)
        yield t[1:-1] if t.startswith('"') else t


def parse_tree(text):
    """Return a synthetic ROOT Node whose blocks are the top-level /begin blocks."""
    root = Node("ROOT")
    stack = [root]
    it = _tok(text)
    for t in it:
        if t == "/begin":
            typ = next(it)
            node = Node(typ)
            stack[-1].blocks.append(node)
            stack.append(node)
        elif t == "/end":
            next(it)  # consume the block-type token following /end
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].tokens.append(t)
    return root


class Model:
    """Interpreted A2L: compu methods, record layouts, axis points, characteristics."""

    def __init__(self):
        self.compu = {}            # name -> (a, b)  physical = a*raw + b
        self.units = {}            # name -> physical unit string ("-" if none)
        self.rl_bits = {}          # record-layout name -> element bits
        self.axis_pts = {}         # name -> dict(addr, bits, cm, npts)
        self.characteristics = []  # list of dicts

    def scale(self, cm_name):
        return self.compu.get(cm_name, (1.0, 0.0))

    def unit(self, cm_name):
        u = self.units.get(cm_name, "-")
        return "" if u == "-" else u


def _flatten(node):
    """Yield every Node in the tree (depth-first), so blocks can be nested anywhere."""
    for b in node.blocks:
        yield b
        yield from _flatten(b)


def load(text):
    root = parse_tree(text)
    m = Model()

    for n in _flatten(root):
        if n.type == "COMPU_METHOD":
            name = n.tokens[0]
            # Header: NAME "desc" LINEAR|RAT_FUNC "%fmt" "unit"  then COEFFS[_LINEAR] ...
            if "COEFFS_LINEAR" in n.tokens:
                i = n.tokens.index("COEFFS_LINEAR")
                a, b = float(n.tokens[i + 1]), float(n.tokens[i + 2])
            elif "COEFFS" in n.tokens:
                i = n.tokens.index("COEFFS")
                a, b = 1.0, 0.0  # identity RAT_FUNC
            else:
                i, a, b = len(n.tokens), 1.0, 0.0
            m.compu[name] = (a, b)
            m.units[name] = n.tokens[i - 1] if i >= 1 else "-"  # unit precedes COEFFS

        elif n.type == "RECORD_LAYOUT":
            name = n.tokens[0]
            for key in ("FNC_VALUES", "AXIS_PTS_X"):
                if key in n.tokens:
                    dt = n.tokens[n.tokens.index(key) + 2]  # KEY <pos> <DTYPE> ...
                    m.rl_bits[name] = DT_BITS.get(dt, 16)
                    break

        elif n.type == "AXIS_PTS":
            # AXIS_PTS <name> "<disp>" 0xADDR <input> <RL> 0 <CM> <npts> <lo> <hi>
            t = n.tokens
            name = t[0]
            m.axis_pts[name] = {
                "addr": int(t[2], 16),
                "rl": t[4],
                "cm": t[6],
                "npts": int(t[7]),
            }

    # second pass: axis element bits now that record layouts are known
    for ap in m.axis_pts.values():
        ap["bits"] = m.rl_bits.get(ap["rl"], 16)

    for n in _flatten(root):
        if n.type != "CHARACTERISTIC":
            continue
        # CHARACTERISTIC <name> "<desc>" \n <KIND> 0xADDR <RL> 0 <CM> <lo> <hi>
        t = n.tokens
        name, desc = t[0], t[1]
        kind, addr, rl, cm = t[2], t[3], t[4], t[6]
        axes = [ad.tokens[ad.tokens.index("AXIS_PTS_REF") + 1]
                for ad in n.findall("AXIS_DESCR") if "AXIS_PTS_REF" in ad.tokens]
        m.characteristics.append({
            "name": name, "desc": desc, "kind": kind,
            "addr": int(addr, 16), "bits": m.rl_bits.get(rl, 16),
            "cm": cm, "scale": m.compu.get(cm, (1.0, 0.0)),
            "unit": m.unit(cm), "axes": axes,
        })

    return m


def scale_str(a, b):
    """Render a linear compu method as a compact physical formula."""
    if abs(a - 1.0) < 1e-12 and abs(b) < 1e-12:
        return "X"
    return f"{a:g}*X{b:+g}" if b else f"{a:g}*X"


def load_path(path):
    with open(path, encoding="latin-1") as f:
        return load(f.read())
