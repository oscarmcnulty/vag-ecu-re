#!/usr/bin/env python3
"""Closed-loop iterative annotation for a TriCore ECU project.

The single annotation pass in annotate.py names each function in isolation. This
driver closes the loop the methodology describes but never actually ran:

    annotate (ollama, neighbor-context) -> merge symbols -> ApplySymbols.java
      -> ExportCallgraph.java (refresh neighbor names) -> DecompileAll.java
      -> re-annotate ONLY the functions whose decompile changed -> repeat

Why it converges: once a callee is renamed and symbols are re-applied, every
caller's decompiled body now shows that name (and the neighbor-context block is
refreshed), so the next pass has strictly more grounding. After pass 1 we only
re-annotate functions whose decompile text actually changed since the previous
pass -- a set that shrinks to zero. Stop when it's empty (or below --threshold,
or --max-passes is hit).

    iterate.py --ecu ecus/simos85 --endpoint http://gpu:11434/v1 \
        --model qwen2.5-coder:14b --max-passes 4

Scope the FIRST pass with --addr-list (e.g. the folded set); later passes follow
the change frontier automatically. Symbols/callgraph/decompiles are always
applied and refreshed project-wide so renames propagate to every caller.
"""
import argparse, csv, glob, hashlib, json, os, subprocess, sys, time


def sh(cmd, log):
    """Run a subprocess, tee output to `log`, return (rc, tail)."""
    with open(log, "w") as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    tail = open(log).read().splitlines()[-3:]
    return p.returncode, "\n".join(tail)


def headless(ghidra, proj, name, binfile, scriptdir, script, args, log):
    cmd = [os.path.join(ghidra, "support", "analyzeHeadless"), proj, name,
           "-process", binfile, "-noanalysis",
           "-scriptPath", scriptdir, "-postScript", script] + list(args)
    return sh(cmd, log)


def file_hash(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def changed_addrs(dir_a, dir_b):
    """Addresses whose decompile differs between two dirs (new or content-changed)."""
    out = []
    for p in glob.glob(os.path.join(dir_b, "*.c")):
        addr = os.path.splitext(os.path.basename(p))[0]
        old = os.path.join(dir_a, addr + ".c")
        if not os.path.exists(old) or file_hash(old) != file_hash(p):
            out.append(addr)
    return sorted(out)


def names_from_csv(path):
    d = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                d[r["address"].lower()] = r["name"]
    return d


def merge_symbols(base_csv, new_csv, out_csv):
    """Overlay new per-pass symbols onto the cumulative set (new wins by address)."""
    rows = {}
    for src in (base_csv, new_csv):
        if not os.path.exists(src):
            continue
        with open(src, newline="") as f:
            for r in csv.DictReader(f):
                rows[r["address"].lower()] = r
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["address", "name", "type", "comment"])
        for addr in sorted(rows):
            r = rows[addr]
            w.writerow([r["address"], r["name"], r.get("type", "FUNCTION"),
                        r.get("comment", "")])
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ecu", required=True, help="ECU pack dir, e.g. ecus/simos85")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", default="qwen2.5-coder:14b")
    ap.add_argument("--proj-name", default="Simos85")
    ap.add_argument("--bin", default="8R0907551F_Original.bin")
    ap.add_argument("--ghidra-home", default=os.environ.get("GHIDRA_HOME", ""))
    ap.add_argument("--max-passes", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.01,
                    help="stop when changed-fraction of the frontier drops below this")
    ap.add_argument("--addr-list", help="limit the FIRST pass to these addresses")
    ap.add_argument("--start-decompiles", default="analysis/decompiles_r",
                    help="decompile dir to seed pass 1 (relative to --ecu)")
    a = ap.parse_args()
    if not a.ghidra_home:
        sys.exit("set --ghidra-home or GHIDRA_HOME (source .env.sh)")

    ecu = os.path.abspath(a.ecu)
    proj = os.path.join(ecu, "ghidra_proj")
    scriptdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "ghidra")
    here = os.path.dirname(os.path.abspath(__file__))
    ann = os.path.join(ecu, "analysis", "annotations_iter")
    cum_csv = os.path.join(ecu, "analysis", "symbols_iter.csv")
    cg = os.path.join(ecu, "analysis", "callgraph")
    logdir = os.path.join(ecu, "analysis", "iter_logs")
    os.makedirs(ann, exist_ok=True)
    os.makedirs(logdir, exist_ok=True)
    # seed cumulative symbols from the existing merged set if present
    base_merged = os.path.join(ecu, "analysis", "symbols_merged.csv")
    if not os.path.exists(cum_csv) and os.path.exists(base_merged):
        merge_symbols(base_merged, base_merged, cum_csv)

    cur_decompiles = os.path.join(ecu, a.start_decompiles)
    addr_list = a.addr_list
    prev_names = names_from_csv(cum_csv)
    run_metrics = {"in": 0, "out": 0, "calls": 0}   # summed across all passes

    for p in range(1, a.max_passes + 1):
        t0 = time.time()
        print(f"\n===== PASS {p} =====", flush=True)

        # 1) annotate (ollama + neighbor context), scoped to the frontier
        acmd = [sys.executable, os.path.join(here, "annotate.py"),
                "--input", cur_decompiles, "--out", ann,
                "--backend", "ollama", "--endpoint", a.endpoint, "--model", a.model,
                "--context-prefix", cg, "--context-depth", "1"]
        if addr_list:
            acmd += ["--addr-list", addr_list]
            n_target = sum(1 for _ in open(addr_list))
        else:
            n_target = len(glob.glob(os.path.join(cur_decompiles, "*.c")))
        print(f"  annotate: {n_target} functions -> {ann}", flush=True)
        rc, tail = sh(acmd, os.path.join(logdir, f"p{p}_annotate.log"))
        print(f"    {tail.splitlines()[-1] if tail else ''}", flush=True)
        # accumulate this pass's real token counts (annotate.py writes _metrics.json
        # into its --out dir, overwritten each pass, so read it before the next one)
        mp = os.path.join(ann, "_metrics.json")
        if os.path.exists(mp):
            m = json.load(open(mp))
            for k in run_metrics:
                run_metrics[k] += m.get(k, 0)

        # 2) merge this pass's symbols into the cumulative set, apply project-wide
        pass_csv = os.path.join(ann, "symbols.csv")
        total = merge_symbols(cum_csv, pass_csv, cum_csv)
        print(f"  apply: {total} cumulative symbols", flush=True)
        rc, tail = headless(a.ghidra_home, proj, a.proj_name, a.bin, scriptdir,
                            "ApplySymbols.java", [cum_csv],
                            os.path.join(logdir, f"p{p}_apply.log"))

        # 3) refresh callgraph (names now reflect the applied symbols)
        headless(a.ghidra_home, proj, a.proj_name, a.bin, scriptdir,
                 "ExportCallgraph.java", [cg],
                 os.path.join(logdir, f"p{p}_callgraph.log"))

        # 4) re-decompile project-wide so renames show up in every caller
        new_decompiles = os.path.join(ecu, "analysis", f"decompiles_p{p}")
        rc, tail = headless(a.ghidra_home, proj, a.proj_name, a.bin, scriptdir,
                            "DecompileAll.java", [new_decompiles],
                            os.path.join(logdir, f"p{p}_decompile.log"))
        print(f"    {tail.splitlines()[-1] if tail else ''}", flush=True)

        # 5) measure: name changes this pass + the decompile-change frontier
        new_names = names_from_csv(cum_csv)
        renamed = sum(1 for k, v in new_names.items()
                      if k in prev_names and prev_names[k] != v)
        frontier = changed_addrs(cur_decompiles, new_decompiles)
        print(f"  PASS {p}: {renamed} names changed, {len(frontier)} decompiles "
              f"changed, {time.time()-t0:.0f}s", flush=True)

        # 6) converge: next pass re-annotates only the changed decompiles
        denom = max(len(new_names), 1)
        if not frontier or len(frontier) / denom < a.threshold:
            print(f"\nCONVERGED after pass {p} "
                  f"(frontier {len(frontier)}/{denom}).", flush=True)
            break
        fl = os.path.join(logdir, f"frontier_p{p}.txt")
        open(fl, "w").write("\n".join(frontier) + "\n")
        addr_list = fl
        cur_decompiles = new_decompiles
        prev_names = new_names
    else:
        print(f"\nstopped at --max-passes {a.max_passes}", flush=True)

    print(f"\ncumulative symbols -> {cum_csv}", flush=True)
    tin, tout, calls = run_metrics["in"], run_metrics["out"], run_metrics["calls"]
    if calls:
        opus = tin / 1e6 * 15 + tout / 1e6 * 75   # Opus 4.x list price yardstick
        print(f"run tokens: in={tin:,} out={tout:,} (total {tin+tout:,}) over "
              f"{calls} calls; ~${opus:.2f} on Claude Opus, ~$0 local", flush=True)
        json.dump({**run_metrics, "opus_usd_equiv": round(opus, 2)},
                  open(os.path.join(ecu, "analysis", "iter_metrics.json"), "w"),
                  indent=2)


if __name__ == "__main__":
    main()
