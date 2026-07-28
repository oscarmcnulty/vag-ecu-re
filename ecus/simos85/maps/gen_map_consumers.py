#!/usr/bin/env python3
"""Attribute the Original-vs-Stage1-vs-Stage2 tuner-diff blocks to their consumer functions
and axis arrays, by joining the byte-diff against maps/map_calls.csv (the map-lookup-framework
trace from core/ghidra/TraceMapCalls.java).

Output: maps/map_consumers.csv  (one row per (diff_block, resolved map/axis arg)):
    diff_block, block_len, stages_changed, map_addr, kind, consumer_func, callee, arg_idx, preview

Run from the simos85 pack dir after reproduce.sh step 8 has produced maps/map_calls.csv:
    python3 maps/gen_map_consumers.py
Needs the three firmware images under firmware/ (gitignored; supply locally)."""
import csv, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
FW = os.path.join(PACK, "firmware", "8R0907551F_%s.bin")
MAP_CALLS = os.path.join(HERE, "map_calls.csv")
OUT = os.path.join(HERE, "map_consumers.csv")
BASE = 0x80000000
REGION = (0x40000, 0x80000)      # calibration region
GAP = 32                          # coalesce differing offsets within GAP bytes


def load(tag):
    with open(FW % tag, "rb") as f:
        return f.read()


def diff_blocks(bins):
    lo, hi = REGION
    hi = min(hi, min(len(b) for b in bins.values()))
    diffs = [i for i in range(lo, hi) if len({b[i] for b in bins.values()}) > 1]
    blocks, start, prev = [], None, None
    for off in diffs:
        if start is None:
            start = prev = off
        elif off - prev <= GAP:
            prev = off
        else:
            blocks.append((start, prev + 1)); start = prev = off
    if start is not None:
        blocks.append((start, prev + 1))
    return blocks


def stages_changed(bins, s, e):
    o, s1, s2 = bins["Original"][s:e], bins["Stage1"][s:e], bins["Stage2"][s:e]
    c1, c2 = o != s1, o != s2
    if c1 and c2:
        return "S1=S2" if s1 == s2 else "S1&S2"
    return "S1-only" if c1 else "S2-only" if c2 else "none"


def is_axis(b, off, n=10):          # monotonic s16 run => looks like an axis
    v = [struct.unpack_from("<h", b, off + 2 * i)[0] for i in range(n) if off + 2 * i + 2 <= len(b)]
    if len(v) < 4:
        return False, v
    up = all(v[k] <= v[k + 1] for k in range(len(v) - 1))
    dn = all(v[k] >= v[k + 1] for k in range(len(v) - 1))
    return (up or dn), v


def main():
    bins = {t: load(t) for t in ("Original", "Stage1", "Stage2")}
    blocks = diff_blocks(bins)
    orig = bins["Original"]

    calls = []
    with open(MAP_CALLS) as f:
        for r in csv.DictReader(f):
            try:
                r["_off"] = int(r["cal_addr"], 16) - BASE
            except (KeyError, ValueError):
                continue
            calls.append(r)

    rows = []
    for s, e in blocks:
        va = BASE + s
        chg = stages_changed(bins, s, e)
        # A map whose base lands inside the changed block (small backward tolerance for a base
        # a few bytes before the first changed cell). NO forward slack: a base at/after the block
        # end is the NEXT map, not this one (that mis-attribution bit the first cut).
        hits = [r for r in calls if s - 8 <= r["_off"] < e]
        if not hits:
            rows.append((f"{va:#x}", e - s, chg, "", "", "", "", "", "no map-call resolved into block"))
            continue
        seen = set()
        for r in hits:
            key = (r["cal_addr"], r["caller_name"], r["callee"], r["arg_idx"])
            if key in seen:
                continue
            seen.add(key)
            ax, vals = is_axis(orig, int(r["cal_addr"], 16) - BASE)
            rows.append((f"{va:#x}", e - s, chg, r["cal_addr"], "axis" if ax else "data",
                         r["caller_name"], r["callee"], r["arg_idx"], str(vals[:8])))

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["diff_block", "block_len", "stages_changed", "map_addr", "kind",
                    "consumer_func", "callee", "arg_idx", "preview"])
        w.writerows(rows)
    print(f"{len(blocks)} diff blocks, {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
