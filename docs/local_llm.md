# LLM backends for annotation

`core/pipeline/annotate.py` supports two backends. Recommended flow is **hybrid**:
local model first-passes all ~2069 functions for free, Claude refines the
high-value subset.

## A. Claude Max via the local CLI (`--backend claude-cli`)

No API key, no per-token billing — runs on your Max subscription through Claude
Code headless mode. Highest quality. Mind Max rate limits, so prioritize:

```bash
# annotate only a curated high-value list (one address per line, e.g. 801dc544)
python3 core/pipeline/annotate.py \
  --input ecus/simos85/analysis/decompiles \
  --out   ecus/simos85/analysis/annotations \
  --backend claude-cli --addr-list ecus/simos85/analysis/priority.txt
```

The Anthropic *API* (api.anthropic.com) is billed separately and is NOT covered by
Max — that's why we shell out to the `claude` CLI instead of using an API key.

## B. Local model on the RTX 5070 Ti (`--backend openai`)

16 GB VRAM. Sweet spot: **Qwen2.5-Coder-14B-Instruct** at Q5 (~10-11 GB, leaves
room for context). Alternatives: Qwen2.5-Coder-7B (faster), Codestral-22B (Q4).

Note: RTX 50-series (Blackwell) needs recent CUDA 12.8+ / driver builds.

### Ollama (simplest)
```bash
# on the GPU host
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:14b
# serves an OpenAI-compatible API on :11434/v1
python3 core/pipeline/annotate.py \
  --input ecus/simos85/analysis/decompiles \
  --out   ecus/simos85/analysis/annotations \
  --backend openai --endpoint http://<gpu-host>:11434/v1 \
  --model qwen2.5-coder:14b
```

### vLLM (higher throughput, batching)
```bash
pip install vllm
vllm serve Qwen/Qwen2.5-Coder-14B-Instruct-AWQ --port 8000
# then --endpoint http://<gpu-host>:8000/v1 --model Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
```

## Hybrid recipe

```bash
# 1) local pass over everything (free)
python3 core/pipeline/annotate.py --input .../decompiles --out .../annotations \
  --backend openai --endpoint http://gpu:11434/v1 --model qwen2.5-coder:14b

# 2) Claude refines the important ones, overwriting their sidecars
python3 core/pipeline/annotate.py --input .../decompiles --out .../annotations \
  --backend claude-cli --addr-list .../priority.txt

# 3) feed merged symbols.csv back into the Ghidra project
analyzeHeadless <proj> Simos85 -process 8R0907551F_Original.bin -noanalysis \
  -scriptPath core/ghidra -postScript ApplySymbols.java .../annotations/symbols.csv
```

The loop closes: decompile -> annotate -> apply -> re-decompile with better names.
