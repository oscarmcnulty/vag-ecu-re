#!/usr/bin/env bash
# Multi-arch linear-sweep arch identification for the 8R0907468 gateway plaintext.
# Imports the raw image under each candidate Ghidra language (BinaryLoader, base 0x8010,
# -noanalysis) and runs FullSweep over a window, scoring valid% + call-target reuse.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/.env.sh"
HL="$GHIDRA_HOME/support/analyzeHeadless"
BIN="$ROOT/ecus/gateway/firmware/8R0907468_0060_plain.bin"
SCRIPTS="$ROOT/ecus/gateway/ghidra_scripts"
BASE=0x8010
IMGLO=0x8010; IMGHI=0x78000
# sweep window (args): default a 96KB window at 0x20000, whole code region for final
WIN_START="${1:-0x20000}"; WIN_LEN="${2:-0x18000}"
shift 2 2>/dev/null || true
PROJ="$(mktemp -d /tmp/claude-1000/-home-om-vag-ecu-re/*/scratchpad/gwsweep.XXXXXX 2>/dev/null || mktemp -d)"
LANGS=(
  "V850:LE:32:default"
  "ARM:LE:32:v7"
  "ARM:LE:32:v8T::thumb"
  "M16C/60:LE:16:default"
  "M16C/80:LE:16:default"
  "SuperH4:LE:32:default"
  "NDS32:LE:32:default"
  "Xtensa:LE:32:default"
  "tricore:LE:32:tc176x"
  "PowerPC:BE:32:default"
)
echo "# window $WIN_START +$WIN_LEN  img $IMGLO..$IMGHI"
for entry in "${LANGS[@]}"; do
  lang="${entry%%::*}"; extra=""
  [[ "$entry" == *"::thumb" ]] && extra="thumb"
  tag="$(echo "$lang" | tr '/:' '__')"
  log="$PROJ/$tag.log"
  "$HL" "$PROJ" "gw_$tag" -import "$BIN" -processor "$lang" \
    -loader BinaryLoader -loader-baseAddr "$BASE" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript FullSweep.java "$WIN_START" "$WIN_LEN" "$IMGLO" "$IMGHI" $extra \
    > "$log" 2>&1
  line="$(grep -hoE 'FULL lang=.*' "$log" | head -1)"
  if [ -z "$line" ]; then
    err="$(grep -iE 'exception|error|not a valid|overlap|failed' "$log" | head -1)"
    printf '%-26s IMPORT/RUN FAILED  %s\n' "$lang${extra:+ +thumb}" "${err:0:70}"
  else
    printf '%-26s %s\n' "$lang${extra:+ +thumb}" "${line#FULL lang=}"
  fi
  rm -rf "$PROJ"/*.rep "$PROJ"/*.gpr "$PROJ"/gw_* 2>/dev/null
done
echo "# proj: $PROJ"
