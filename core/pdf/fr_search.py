#!/usr/bin/env python3
"""Search the Funktionsrahmen index built by fr_index.py.

  # term search (case-insensitive substring, any-of)
  fr_search.py OUTDIR --term cruise "vehicle speed" "set speed" [--max 20] [--context 2]
  # exact label lookup (uses fr_labels.tsv for the page list, then shows snippets)
  fr_search.py OUTDIR --label NC_SREP_STP_BUFFER_LEN
  # list label tokens matching a regex (discover naming, e.g. cruise/speed labels)
  fr_search.py OUTDIR --grep-labels 'FGR|GRA|CRUISE|VMIN|V_MIN|SPEED'
"""
import argparse, json, os, re


def iter_pages(outdir):
    with open(os.path.join(outdir, "fr_pages.jsonl")) as f:
        for line in f:
            yield json.loads(line)


def show_snippets(rec, terms, context):
    lines = rec["text"].splitlines()
    idx = [i for i, l in enumerate(lines) if any(t in l.lower() for t in terms)]
    shown = set()
    for i in idx[:4]:
        for j in range(max(0, i - context), min(len(lines), i + context + 1)):
            if j not in shown and lines[j].strip():
                print("    " + lines[j].strip())
                shown.add(j)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--term", nargs="+")
    ap.add_argument("--label")
    ap.add_argument("--grep-labels")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--context", type=int, default=1)
    a = ap.parse_args()

    if a.grep_labels:
        rx = re.compile(a.grep_labels, re.I)
        with open(os.path.join(a.outdir, "fr_labels.tsv")) as f:
            for line in f:
                tok = line.split("\t", 1)[0]
                if rx.search(tok):
                    print(line.rstrip())
        return

    terms = [a.label.lower()] if a.label else [t.lower() for t in (a.term or [])]
    if not terms:
        ap.error("need --term, --label, or --grep-labels")

    hits = 0
    for rec in iter_pages(a.outdir):
        low = rec["text"].lower()
        which = [t for t in terms if t in low]
        if not which:
            continue
        hits += 1
        if hits <= a.max:
            print(f"\n=== page {rec['page']} (matched: {', '.join(which)}) ===")
            show_snippets(rec, terms, a.context)
    print(f"\n[{hits} pages matched; showing first {min(hits, a.max)}]")


if __name__ == "__main__":
    main()
