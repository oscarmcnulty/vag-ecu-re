"""Bounded neighbor-context for the annotation pass.

Reads the CSVs from core/ghidra/ExportCallgraph.java and, for one function,
builds a SHORT context block of recovered neighbors to prepend to the LLM prompt.

Deliberately shallow. Beyond a hop or two the neighbors are only weakly related,
and the model starts inventing a domain by association rather than from evidence
(exactly the failure the v4 prompt's EVIDENCE RULE warns against). Default depth 1;
2 is the sane maximum. We also drop un-named neighbors (FUN_xxxx / thunk_*) — they
carry no signal — and cap counts so the block can't dominate the token budget.
"""
import csv, os
from collections import defaultdict


def _named(name):
    """True if a neighbor name carries semantic signal worth showing the model."""
    if not name:
        return False
    low = name.lower()
    if low.startswith("fun_") or low.startswith("thunk_fun_"):
        return False
    return True


class NeighborContext:
    def __init__(self, prefix, max_callees=12, max_callers=8, max_reads=10):
        self.callees = defaultdict(list)   # addr -> [callee_name, ...]
        self.callers = defaultdict(list)   # addr -> [caller_name, ...]
        self.callee_addrs = defaultdict(list)  # addr -> [callee_addr, ...] (for depth>=2)
        self.reads = defaultdict(list)     # addr -> [cal_symbol, ...]
        self.max_callees, self.max_callers, self.max_reads = max_callees, max_callers, max_reads

        edges = prefix + "_edges.csv"
        creads = prefix + "_cal_reads.csv"
        if os.path.exists(edges):
            with open(edges, newline="") as f:
                for r in csv.DictReader(f):
                    ca, ce = r["caller_addr"].lower(), r["callee_addr"].lower()
                    self.callee_addrs[ca].append(ce)
                    if _named(r["callee_name"]):
                        self.callees[ca].append(r["callee_name"])
                    if _named(r["caller_name"]):
                        self.callers[ce].append(r["caller_name"])
        if os.path.exists(creads):
            with open(creads, newline="") as f:
                for r in csv.DictReader(f):
                    fa = r["func_addr"].lower()
                    sym = r["cal_symbol"] or r["cal_addr"]
                    self.reads[fa].append(sym)

    @staticmethod
    def _uniq(seq, cap):
        out = []
        for x in seq:
            if x not in out:
                out.append(x)
            if len(out) >= cap:
                break
        return out

    def block_for(self, addr, depth=1):
        """Return a comment block of recovered neighbors, or '' if nothing useful."""
        addr = addr.lower()
        callees = self._uniq(self.callees.get(addr, []), self.max_callees)
        callers = self._uniq(self.callers.get(addr, []), self.max_callers)
        reads = self._uniq(self.reads.get(addr, []), self.max_reads)

        hop2 = []
        if depth >= 2:
            for ca in self.callee_addrs.get(addr, []):
                hop2.extend(self.callees.get(ca, []))
            hop2 = [n for n in self._uniq(hop2, self.max_callees) if n not in callees]

        if not (callees or callers or reads or hop2):
            return ""
        lines = ["/* RECOVERED NEIGHBORS (ground truth from the disassembly — evidence,",
                 " * NOT names to rename; infer this function's domain from them):"]
        if callees:
            lines.append(" * calls: " + ", ".join(callees))
        if hop2:
            lines.append(" * calls (2nd hop): " + ", ".join(hop2))
        if callers:
            lines.append(" * called by: " + ", ".join(callers))
        if reads:
            lines.append(" * reads calibration: " + ", ".join(reads))
        lines.append(" */\n")
        return "\n".join(lines)
