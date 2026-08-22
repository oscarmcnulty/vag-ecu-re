#!/usr/bin/env bash
# Regenerate ram_bases.csv AUTHORITATIVELY by EMULATING the boot init stubs (InitEmu.java),
# not by static pool-deref (which mis-resolved 72/154 values). Enumerates the install-stub
# functions from the decompiled corpus, then runs them under Ghidra's SH-2A emulator.
set -euo pipefail
ECU_DIR="$(cd "$(dirname "$0")/.." && pwd)"; ROOT="$(cd "$ECU_DIR/../.." && pwd)"
source "$ROOT/.env.sh"
CORP="$ECU_DIR/analysis/decompiles_r"
STUBS="$(mktemp)"
python3 - "$CORP" "$STUBS" <<'PY'
import re,glob,os,sys
corp,out=sys.argv[1],sys.argv[2]
sr=re.compile(r"^\s*\*_?DAT_[0-9a-f]{8}\s*=\s*(?:_?DAT_[0-9a-f]{8}|0x[0-9a-f]+)\s*;\s*$",re.M)
e=[]
for f in glob.glob(f"{corp}/*.c"):
    t=open(f,errors='replace').read(); b=t[t.find('{')+1:t.rfind('}')]
    if sr.findall(b) and all(("*" in l) for l in b.splitlines() if l.strip() and "=" in l and "return" not in l and "{" not in l and "}" not in l):
        e.append(os.path.basename(f)[:-2])
open(out,"w").write(" ".join(sorted(set(e))))
PY
"$GHIDRA_HOME/support/analyzeHeadless" "$ECU_DIR/ghidra_proj" AL551 -process 8R_full_flash.bin -noanalysis \
  -scriptPath "$ROOT/core/ghidra" -postScript InitEmu.java "$ECU_DIR/analysis/ram_bases.csv" "$STUBS" 2>&1 \
  | sed 's/.*java> //;s/ (GhidraScript).*//' | grep InitEmu
rm -f "$STUBS"
