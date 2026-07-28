#!/usr/bin/env python3
"""Batch-annotate decompiled TriCore functions. Two backends:

  --backend claude-cli   shells out to the local `claude` CLI in headless mode
                         (`claude -p`). Runs on your Claude Max plan, no API key,
                         no per-token billing. Best quality. Mind Max rate limits
                         -> use --limit / --addr-list to prioritize.

  --backend openai       POSTs to any OpenAI-compatible /chat/completions endpoint
                         (local Qwen2.5-Coder on the RTX 5070 Ti via Ollama/vLLM,
                         or a hosted model). Free/offline bulk throughput.

Reads <input>/<addr>.c files (from core/ghidra/DecompileAll.java), writes JSON
sidecars to <out>/, and a combined symbols.csv ready for ApplySymbols.java.

Hybrid pattern: run openai (local) over everything, then claude-cli over the
high-value subset via --addr-list, merging into the same symbols.csv.

    annotate.py --input analysis/decompiles --out analysis/annotations \
        --backend claude-cli --limit 150 --addr-list analysis/priority.txt

    annotate.py --input analysis/decompiles --out analysis/annotations \
        --backend openai --endpoint http://HOST:11434/v1 --model qwen2.5-coder:14b
"""
import argparse, csv, glob, json, os, re, socket, subprocess, sys, time
import urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from context import NeighborContext

# Default prompt = the tuned winner from prompt_eval.py (7/7 dimensionality on the
# Simos8.5 eval set). Override per-run with --prompt-file.
DEFAULT_PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "prompts", "v4_final.txt")
PROMPT = (  # embedded fallback if the prompt file is missing
    "You are reversing Infineon TriCore ECU firmware (VAG Simos/MED). Reply with "
    "STRICT JSON only: {\"name\":\"<snake_case>\",\"purpose\":\"<one line>\","
    "\"dimensionality\":\"1d|2d|na\",\"confidence\":0.0-1.0,\"renames\":{}}. "
    "kf_interp_*=2D Kennfeld, kl_interp_*=1D Kennlinie. Function:\n\n"
)


METRICS = {"in": 0, "out": 0, "calls": 0}   # real token counts from the backend


def is_transient(e):
    """Worth retrying: connection refused/reset, timeouts, 5xx/429/408. A 4xx or a
    parse failure is not — retrying it just hammers the host for the same result."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in (408, 429) or e.code >= 500
    if isinstance(e, RuntimeError):   # claude-cli rate limits surface here
        return True
    return isinstance(e, (urllib.error.URLError, socket.timeout,
                          TimeoutError, ConnectionError, OSError))


def endpoint_alive(endpoint, timeout=10):
    try:
        req = urllib.request.Request(endpoint.rstrip("/") + "/models",
                                     headers={"Authorization": "Bearer none"})
        urllib.request.urlopen(req, timeout=timeout).read()
        return True
    except Exception:
        return False


def wait_for_endpoint(endpoint, total, interval=15):
    """Block until the endpoint answers again, up to `total` seconds. Returns True
    if it recovered. This is what stops a mid-batch host death from cascading: we
    park on the current function instead of failing every remaining one instantly."""
    interval = min(interval, total) if total > 0 else interval
    waited = 0
    while waited < total:
        time.sleep(interval)
        waited += interval
        if endpoint_alive(endpoint):
            return True
    return False


def call_with_retry(do_call, addr, *, backend, endpoint, max_retries,
                    base, health_timeout):
    """Run do_call() with exponential backoff on transient failures, and one
    endpoint health-wait before giving up (openai backend). Re-raises the last
    error if it's non-transient or recovery times out."""
    health_waited, attempt = False, 0
    while True:
        try:
            return do_call()
        except Exception as e:
            if is_transient(e) and attempt < max_retries:
                delay = min(base * (2 ** attempt), 60)
                attempt += 1
                print(f"  ~ {addr}: {str(e)[:120]} -> retry {attempt}/{max_retries}"
                      f" in {delay:.0f}s", file=sys.stderr)
                time.sleep(delay)
                continue
            if (is_transient(e) and backend == "openai" and endpoint
                    and not health_waited):
                health_waited = True
                print(f"  ! {addr}: {str(e)[:120]} -> endpoint stalled; waiting up to"
                      f" {health_timeout}s for recovery", file=sys.stderr)
                if wait_for_endpoint(endpoint, health_timeout):
                    attempt = 0
                    print("  + endpoint recovered; resuming", file=sys.stderr)
                    continue
            raise


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # Salvage a reply truncated mid-output (e.g. cut inside a long `renames` dict):
    # the fields we actually use appear early, so recover them by regex. Returns
    # None only when even the name is missing (a genuinely unusable reply).
    def field(k):
        mm = re.search(r'"%s"\s*:\s*"([^"]*)"' % k, text)
        return mm.group(1) if mm else None
    name = field("name")
    if not name:
        return None
    conf = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
    return {"name": name, "purpose": field("purpose") or "",
            "dimensionality": field("dimensionality") or "na",
            "confidence": float(conf.group(1)) if conf else 0.6,
            "renames": {}, "_salvaged": True}


def call_claude_cli(code, model=None, timeout=120):
    cmd = ["claude", "-p"]
    if model:
        cmd += ["--model", model]
    # prompt via stdin: avoids arg-length/escaping issues with large functions
    r = subprocess.run(cmd, input=PROMPT + code, capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude cli rc={r.returncode}: {r.stderr.strip()[:200]}")
    return extract_json(r.stdout)


def call_openai(code, endpoint, model, api_key, max_tokens=512, timeout=180):
    # response_format + max_tokens: force parseable JSON and stop runaway generation
    # (a big confusing function otherwise rambles prose until the socket times out).
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": PROMPT + code}],
    }).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key or 'none'}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    u = data.get("usage", {})
    METRICS["in"] += u.get("prompt_tokens", 0)
    METRICS["out"] += u.get("completion_tokens", 0)
    METRICS["calls"] += 1
    return extract_json(data["choices"][0]["message"]["content"])


def auto_num_ctx(text, lo=4096, hi=16384):
    """Pick a num_ctx that fits the prompt. Ollama's default (~4096) silently
    truncates big functions -> the model sees a chopped prompt and emits empty
    JSON. Dense TriCore decompiles (hex, FUN_/DAT_ symbols) tokenize at ~2 chars/
    token, so estimate conservatively and round UP to a power of two; truncation
    is the failure mode, so bias high. Returns (num_ctx, est); caller skips est>hi."""
    est = len(text) // 2 + 512
    n = lo
    while n < est and n < hi:
        n *= 2
    return min(n, hi), est


def call_ollama(code, endpoint, model, num_ctx, num_predict=512, timeout=240):
    """Native Ollama /api/chat. Unlike the /v1 OpenAI layer it honors num_ctx, so
    we can size the context to each function. format=json forces a parseable reply."""
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    body = json.dumps({
        "model": model, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": num_predict},
        "messages": [{"role": "user", "content": PROMPT + code}],
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    METRICS["in"] += data.get("prompt_eval_count", 0)
    METRICS["out"] += data.get("eval_count", 0)
    METRICS["calls"] += 1
    return extract_json(data["message"]["content"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="dir of <addr>.c files")
    ap.add_argument("--out", required=True, help="output dir for annotations")
    ap.add_argument("--backend", choices=["claude-cli", "openai", "ollama"],
                    required=True,
                    help="ollama = native /api/chat with auto-sized num_ctx + forced "
                         "JSON (recommended for local Qwen; handles large functions)")
    ap.add_argument("--endpoint", help="openai backend: base URL ending in /v1")
    ap.add_argument("--model", help="model id (openai) or --model for claude cli")
    ap.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    ap.add_argument("--prompt-file", default=DEFAULT_PROMPT_FILE,
                    help="prompt text file (default: tuned prompts/v4_final.txt)")
    ap.add_argument("--addr-list", help="file of addresses (one per line) to limit to")
    ap.add_argument("--limit", type=int, default=0, help="max functions (0=all)")
    ap.add_argument("--min-conf", type=float, default=0.5,
                    help="only emit symbols at/above this confidence")
    ap.add_argument("--skip-done", action="store_true",
                    help="skip functions that already have a JSON sidecar")
    ap.add_argument("--context-prefix",
                    help="path prefix of ExportCallgraph.java CSVs "
                         "(<prefix>_edges.csv, <prefix>_cal_reads.csv); "
                         "prepends a bounded neighbor-context block to each prompt")
    ap.add_argument("--context-depth", type=int, default=1,
                    help="neighbor hops to include (1=direct, 2=max sane; default 1)")
    ap.add_argument("--max-retries", type=int, default=4,
                    help="per-call retries on transient errors (exp backoff); default 4")
    ap.add_argument("--retry-base", type=float, default=5.0,
                    help="base seconds for exponential backoff (5,10,20,40...60 cap)")
    ap.add_argument("--health-timeout", type=int, default=600,
                    help="openai/ollama backend: seconds to wait for a stalled endpoint "
                         "to recover before giving up on a function (0=disable)")
    ap.add_argument("--max-tokens", type=int, default=1024,
                    help="cap on generated tokens (num_predict); stops runaway output. "
                         "Big functions emit large `renames` dicts -> keep generous")
    ap.add_argument("--num-ctx", type=int, default=0,
                    help="ollama: fixed context window (0=auto-size per function)")
    ap.add_argument("--max-ctx", type=int, default=16384,
                    help="ollama: auto-size ceiling; functions estimated larger are "
                         "skipped+logged rather than silently truncated")
    a = ap.parse_args()
    if a.backend in ("openai", "ollama") and not a.endpoint:
        sys.exit(f"--backend {a.backend} requires --endpoint")

    ctx = None
    if a.context_prefix:
        ctx = NeighborContext(a.context_prefix)
        print(f"context: {a.context_prefix}_*.csv (depth {a.context_depth})")

    global PROMPT
    if a.prompt_file and os.path.exists(a.prompt_file):
        PROMPT = open(a.prompt_file).read()
        print(f"prompt: {a.prompt_file} ({len(PROMPT)} chars)")
    else:
        print(f"prompt: embedded fallback (no file at {a.prompt_file})")

    os.makedirs(a.out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(a.input, "*.c")))
    if not files:
        sys.exit(f"no .c files in {a.input} (run DecompileAll.java first)")
    if a.addr_list:
        want = {ln.strip().lower() for ln in open(a.addr_list) if ln.strip()}
        files = [f for f in files
                 if os.path.splitext(os.path.basename(f))[0].lower() in want]
    if a.limit:
        files = files[:a.limit]

    # ollama: pick ONE num_ctx for the whole run = the largest any function needs
    # (clamped to --max-ctx). Changing num_ctx between calls forces a model reload
    # (~15s each), so a single run-wide value keeps the model resident. A small-only
    # batch stays at 4096; a batch with big functions loads once at the larger size.
    run_nctx = None
    if a.backend == "ollama":
        if a.num_ctx > 0:
            run_nctx = a.num_ctx
        else:
            run_nctx = 4096
            for path in files:
                addr = os.path.splitext(os.path.basename(path))[0]
                blk = ctx.block_for(addr, a.context_depth) if ctx else ""
                n, est = auto_num_ctx(PROMPT + blk + open(path).read(), hi=a.max_ctx)
                if est <= a.max_ctx:
                    run_nctx = max(run_nctx, n)
        kv_gb = run_nctx * 0.19 / 1024
        print(f"ollama: num_ctx={run_nctx} for the run (~{kv_gb:.1f}GB KV, "
              f"one model load, no reloads)")

    rows, done, errs = [], 0, 0
    for path in files:
        addr = os.path.splitext(os.path.basename(path))[0]
        sidecar = os.path.join(a.out, addr + ".json")
        if a.skip_done and os.path.exists(sidecar):
            continue
        code = open(path).read()
        if ctx:
            code = ctx.block_for(addr, a.context_depth) + code
        if a.backend == "claude-cli":
            do_call = lambda: call_claude_cli(code, a.model)
        elif a.backend == "openai":
            do_call = lambda: call_openai(code, a.endpoint, a.model, a.api_key,
                                          a.max_tokens)
        else:  # ollama: run-wide num_ctx; skip only a function too big to ever fit
            _, est = auto_num_ctx(PROMPT + code, hi=a.max_ctx)
            if a.num_ctx == 0 and est > a.max_ctx:
                errs += 1
                print(f"  ! {addr}: ~{est} tok > max-ctx {a.max_ctx}; skipped "
                      f"(raise --max-ctx)", file=sys.stderr)
                continue
            do_call = lambda: call_ollama(code, a.endpoint, a.model, run_nctx,
                                          a.max_tokens)
        try:
            ann = call_with_retry(do_call, addr, backend=a.backend,
                                  endpoint=a.endpoint, max_retries=a.max_retries,
                                  base=a.retry_base, health_timeout=a.health_timeout)
        except Exception as e:
            errs += 1
            print(f"  ! {addr}: {e}", file=sys.stderr)
            continue
        if not ann:
            errs += 1
            continue
        json.dump(ann, open(sidecar, "w"), indent=2)
        done += 1
        if ann.get("confidence", 0) >= a.min_conf and ann.get("name"):
            # 0xADDR + FUNCTION so the row drops straight into ApplySymbols.java
            rows.append(("0x" + addr.lstrip("0x"), ann["name"], "FUNCTION",
                         ann.get("purpose", "")))
        if done % 25 == 0:
            print(f"  ... {done} annotated, {errs} errors")

    out_csv = os.path.join(a.out, "symbols.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["address", "name", "type", "comment"])
        w.writerows(rows)
    print(f"done: {done} annotated, {errs} errors, "
          f"{len(rows)} symbols >= conf {a.min_conf} -> {out_csv}")
    if METRICS["calls"]:
        tin, tout = METRICS["in"], METRICS["out"]
        # Opux 4.x list price ($15/$75 per 1M) as a single yardstick for savings
        opus = tin / 1e6 * 15 + tout / 1e6 * 75
        print(f"tokens: in={tin:,} out={tout:,} (total {tin+tout:,}) over "
              f"{METRICS['calls']} backend calls; ~${opus:.2f} on Claude Opus, "
              f"~$0 local")
        json.dump({**METRICS, "opus_usd_equiv": round(opus, 2)},
                  open(os.path.join(a.out, "_metrics.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
