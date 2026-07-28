#!/usr/bin/env python3
"""Index a Continental/Bosch Funktionsrahmen PDF for label/term search.

Runs pdftotext once, splits the document into pages (form-feed delimited), and
writes a searchable index. The FR has no addresses, but it carries the label
names, computation logic, axis definitions and physical<->internal scaling we
need to align decompiled code to calibration maps.

Outputs (in OUTDIR):
  fr_full.txt     raw pdftotext dump (cached; delete to re-extract)
  fr_pages.jsonl  one {"page":N,"text":...} record per page
  fr_labels.tsv   label-ish token  ->  count  ->  first pages (for fast lookup)

Usage: fr_index.py PDF OUTDIR
"""
import collections, json, os, re, subprocess, sys

# label-ish: an identifier token that has an uppercase letter and either an
# underscore or a digit (NC_*, C_*, KFMIRL, FGR_v_min, ...), or all-caps len>=4.
TOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


def labelish(tok):
    if tok.isupper() and len(tok) >= 4:
        return True
    return any(c.isupper() for c in tok) and (("_" in tok) or any(c.isdigit() for c in tok))


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: fr_index.py PDF OUTDIR")
    pdf, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    full = os.path.join(outdir, "fr_full.txt")

    if not os.path.exists(full) or os.path.getsize(full) == 0:
        print(f"pdftotext {pdf} (large; minutes) ...", flush=True)
        subprocess.run(["pdftotext", "-q", pdf, full], check=True)

    text = open(full, errors="replace").read()
    pages = text.split("\f")
    print(f"{len(pages)} pages", flush=True)

    tok_pages = collections.defaultdict(set)
    with open(os.path.join(outdir, "fr_pages.jsonl"), "w") as pj:
        for i, pg in enumerate(pages, 1):
            pj.write(json.dumps({"page": i, "text": pg}) + "\n")
            for tok in set(TOK.findall(pg)):
                if labelish(tok):
                    tok_pages[tok].add(i)
            if i % 2000 == 0:
                print(f"  indexed {i} pages", flush=True)

    with open(os.path.join(outdir, "fr_labels.tsv"), "w") as lf:
        for tok, pgs in sorted(tok_pages.items(), key=lambda kv: -len(kv[1])):
            lf.write(f"{tok}\t{len(pgs)}\t{','.join(map(str, sorted(pgs)[:30]))}\n")
    print(f"done: {len(tok_pages)} label tokens -> fr_labels.tsv", flush=True)


if __name__ == "__main__":
    main()
