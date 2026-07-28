#!/usr/bin/env python3
"""Compare annotation prompt variants on a labeled function set.

For each prompt file, queries the endpoint over every function in the eval set
and auto-scores the 1D/2D map-dimensionality calls (objectively gradable: a fn
that calls kf_interp_* is 2D, kl_interp_* is 1D). Prints a per-variant accuracy
summary plus a side-by-side of the names produced, so you can tune the prompt
before committing to the full run.

    prompt_eval.py --decompiles DIR --eval-set eval_set.txt \
        --endpoint http://host:11434/v1 --model qwen2.5-coder:14b \
        --prompts core/pipeline/prompts/v1_baseline.txt core/pipeline/prompts/v2_glossary.txt
"""
import argparse, json, os, re, sys, urllib.request

KW_2D = ("kennfeld", "2d", "2-d", "two-axis", "two axis", "two-dimensional", "bilinear")
KW_1D = ("kennlinie", "1d", "1-d", "one-axis", "one axis", "one-dimensional", "curve")


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def query(endpoint, model, prompt, code, timeout=120):
    body = json.dumps({
        "model": model, "temperature": 0,
        "messages": [{"role": "user", "content": prompt + code}],
    }).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return extract_json(json.load(r)["choices"][0]["message"]["content"])


def grade_dim(ann, expected):
    """Return 'correct' | 'wrong' | 'unspecified' for a 1d/2d-labeled function."""
    if not ann:
        return "wrong"
    blob = " ".join(str(ann.get(k, "")) for k in ("name", "purpose", "dimensionality")).lower()
    said_2d = any(k in blob for k in KW_2D)
    said_1d = any(k in blob for k in KW_1D)
    pred = "2d" if (said_2d and not said_1d) else "1d" if (said_1d and not said_2d) else None
    if pred is None:
        return "unspecified"
    return "correct" if pred == expected else "wrong"


def load_set(path):
    rows = []
    for ln in open(path):
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        parts = ln.split()
        rows.append((parts[0], parts[1] if len(parts) > 1 else "na"))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decompiles", required=True)
    ap.add_argument("--eval-set", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompts", nargs="+", required=True)
    a = ap.parse_args()

    items = load_set(a.eval_set)
    prompts = {os.path.basename(p): open(p).read() for p in a.prompts}
    results = {name: {} for name in prompts}

    for name, ptext in prompts.items():
        for addr, exp in items:
            cpath = os.path.join(a.decompiles, addr + ".c")
            if not os.path.exists(cpath):
                results[name][addr] = (None, "missing")
                continue
            try:
                ann = query(a.endpoint, a.model, ptext, open(cpath).read())
            except Exception as e:
                results[name][addr] = (None, f"err:{e}")
                continue
            g = grade_dim(ann, exp) if exp in ("1d", "2d") else "-"
            results[name][addr] = (ann, g)

    # summary
    print("\n==================== DIMENSIONALITY ACCURACY ====================")
    for name in prompts:
        gradable = [(addr, exp) for addr, exp in items if exp in ("1d", "2d")]
        tally = {"correct": 0, "wrong": 0, "unspecified": 0}
        for addr, exp in gradable:
            tally[results[name][addr][1]] = tally.get(results[name][addr][1], 0) + 1
        n = len(gradable)
        print(f"  {name:22s}  correct={tally['correct']}/{n}  "
              f"wrong={tally['wrong']}  unspecified={tally['unspecified']}")

    # side-by-side names
    print("\n==================== NAMES (eyeball quality) ====================")
    hdr = f"{'addr':10s} {'exp':4s} " + " ".join(f"{n[:20]:32s}" for n in prompts)
    print(hdr)
    for addr, exp in items:
        cells = []
        for name in prompts:
            ann, g = results[name][addr]
            nm = (ann or {}).get("name", "?") if ann else "?"
            mark = {"correct": "✓", "wrong": "✗", "unspecified": "·"}.get(g, " ")
            cells.append(f"{mark} {nm[:30]:30s}")
        print(f"{addr:10s} {exp:4s} " + " ".join(cells))


if __name__ == "__main__":
    main()
