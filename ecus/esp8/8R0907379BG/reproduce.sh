#!/usr/bin/env bash
# Reproduce the labeled ESP8 (Bosch, 8R0907379BG) Ghidra project + decompiles from committed
# metadata ONLY. ESP8 is mixed ARM/Thumb with a data region, so it does NOT use the generic
# uniform-ISA core/pipeline/reproduce.sh; it imports, splits CODE/DATA, analyzes, then recreates
# the EXACT mixed-ISA function set from a Thumb-annotated manifest, and reuses the core
# ApplySymbols/DecompileAll/CoverageStat tail. Needs Ghidra 12.1.2 + JDK 21 (see .env.sh).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
source "$ROOT/.env.sh"
: "${GHIDRA_HOME:?set GHIDRA_HOME}"; : "${JAVA_HOME:?set JAVA_HOME}"
source "$HERE/ecu.conf"
BIN="$HERE/$FIRMWARE"; PROJ="$HERE/ghidra_proj"; NAME="$ECU_NAME"; PROG="$(basename "$BIN")"
ESP="$ROOT/ecus/esp8/ghidra_scripts"; CORE="$ROOT/core/ghidra"
HL="$GHIDRA_HOME/support/analyzeHeadless"
LOGS="$HERE/analysis/_logs"; mkdir -p "$LOGS"
ENTRIES="$HERE/analysis/function_entries.txt"; BARE="$HERE/analysis/function_entries_bare.txt"
SYMS="$HERE/analysis/symbols_merged.csv"
[ -f "$BIN" ]     || { echo "missing firmware $BIN (gitignored; supply locally)"; exit 1; }
[ -f "$ENTRIES" ] || { echo "missing $ENTRIES (run EspExportFns.java first)"; exit 1; }
sed 's/,.*//; /^#/d; /^[[:space:]]*$/d' "$ENTRIES" > "$BARE"

run(){ local n="$1"; shift; echo "==> $n"; "$HL" "$@" >"$LOGS/$n.log" 2>&1 \
       || { echo "FAILED $n (see $LOGS/$n.log)"; tail -25 "$LOGS/$n.log"; exit 1; }; }
say(){ sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/$1.log" | grep -E "$2" | sed 's/^/    /' || true; }

echo "=== reproduce $NAME ($PROG -> $PROJ) ==="
rm -rf "$PROJ"; mkdir -p "$PROJ"
run 01_import    "$PROJ" "$NAME" -import "$BIN" -processor "$PROCESSOR" \
                 -loader BinaryLoader -loader-baseAddr "$LOADBASE" -noanalysis
run 02_split     "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$ESP" \
                 -postScript EspSplit.java -postScript EspFix.java
say 02_split '(split|RAM|removed)'
run 03_analyze   "$PROJ" "$NAME" -process "$PROG"
run 04_fix       "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$ESP" -postScript EspFix.java
say 04_fix 'removed'
# 04b: bring the SECOND code region (above CODE_HI) into the project. This region
# (~file 0xbb045-0x106000, mixed ARM+Thumb, interleaved with the COM config tables) was excluded
# as DATA; its ARM sub-blocks load at VMA = file_offset + 3 (proven by seg1/config->seg2 refs, e.g.
# 0x67ed0->0xbc5f8, 0xa7b24->0x10002c). EspSeg2 splits the DATA block at SEG2_START, moves the upper
# part +3 so ARM decodes 4-aligned, and creates a function at every ARM prologue. It must run AFTER
# 04_fix (which clears code units in 0xa2000-0x110000). See docs/second_code_segment.md.
run 04b_seg2     "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$ESP" \
                 -postScript EspSeg2.java "${SEG2_START:-0xbb045}"
say 04b_seg2 '^EspSeg2'
# 04c: re-analyze so references from the newly-disassembled seg2 code resolve (xrefs to the COM
# signal buffers -> the CAN-frame trace becomes a normal static xref walk).
run 04c_reanalyze "$PROJ" "$NAME" -process "$PROG"
run 05_createfns "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$ESP" \
                 -postScript EspCreateFns.java "$ENTRIES"
say 05_createfns '^EspCreateFns'
# 05b coverage recovery: claim orphan (disassembled, function-less) code -> +~106 fns / ~25KB.
# ClaimOrphanCode is mixed-ISA-safe (claims ALREADY-disassembled instructions; no re-disasm).
# (RecoverBracketedCode is NOT wired: it pseudo-disassembles UNDEFINED bytes in the default ISA
#  and would mis-decode Thumb regions as ARM -- needs an ARM-aware variant before use here.)
run 05b_orphan   "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$CORE" \
                 -postScript ClaimOrphanCode.java 0x0 "${CODE_HI:-0xa2000}" "$HERE/analysis/orphan_entries.txt"
say 05b_orphan '^ClaimOrphanCode'
# re-export the manifest so the recovered fns persist + get decompiled + recreated next run
run 05c_reexport "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$ESP" \
                 -postScript EspExportFns.java "$ENTRIES"
say 05c_reexport '^EspExportFns'
sed 's/,.*//; /^#/d; /^[[:space:]]*$/d' "$ENTRIES" > "$BARE"
run 06_syms      "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$CORE" \
                 -postScript ApplySymbols.java "$SYMS"
say 06_syms '^ApplySymbols'
# 06b: label the AUTOSAR-COM explicit signal buffers (com_sig_<id>_buf) so COM functions
# decompile with named buffers instead of DAT_004xxxxx.
run 06b_comsig  "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$ESP" \
                 -postScript EspDecodeComSignals.java
say 06b_comsig '^EspDecodeComSignals'
rm -rf "$HERE/analysis/decompiles_r"
run 07_decomp    "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$CORE" \
                 -postScript DecompileAll.java "$HERE/analysis/decompiles_r" "$BARE"
say 07_decomp '^DecompileAll'
run 08_cov       "$PROJ" "$NAME" -process "$PROG" -noanalysis -scriptPath "$CORE" \
                 -postScript CoverageStat.java "$LOADBASE" "$IMAGE_HI"
sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/08_cov.log" > "$HERE/analysis/coverage.log" || true
echo "done. labeled project $PROJ ; decompiles analysis/decompiles_r ; per-step logs $LOGS"
