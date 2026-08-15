#!/usr/bin/env bash
# Shared reproduce driver: rebuild a labeled Ghidra project + decompiles for ANY ECU pack
# in this repo, from version-controlled metadata ONLY (no derived/decompiled source is
# committed -- it is regenerated here).
#
# Usage:  ecus/<ecu>/reproduce.sh            (a 2-line wrapper that sources ecu.conf and execs this)
#     or: ECU_DIR=ecus/<ecu> core/pipeline/reproduce.sh
#
# Every step is conditional on the config declaring the inputs it needs, and SKIPS LOUDLY
# rather than silently faking a result. That is what makes one driver serve a mature pack
# (simos85: a large named corpus, an A2L, a map-lookup framework) and a cold-start pack
# (a fresh ECU with nothing but a firmware image) without divergence.
#
# --- ecu.conf keys ------------------------------------------------------------------
# REQUIRED
#   ECU_NAME        Ghidra project name (e.g. Simos85, MED1711)
#   FIRMWARE        path to the image, relative to the pack dir (gitignored; supply locally)
#   LOADBASE        load address of the image (e.g. 0x80000000)
# OPTIONAL -- each unset key disables its step
#   PROCESSOR       Ghidra language id            (default tricore:LE:32:tc176x)
#   EXPECT_SHA      sha256 of FIRMWARE; verified before anything runs
#   MEMMAP          array of MapMemory args       -> step 1 maps alias/RAM/CSFR blocks
#   ALIAS_BASE/_LEN non-cached flash alias        -> step 3b collapses alias twin functions
#   BASEREGS        array a0=0x.. a1=0x.. a8=0x.. -> step 3 sets base registers + re-analyzes
#   CODE_RANGES     array of lo:hi                -> step 4b claims orphan (function-less) code
#   CAL_LO/CAL_HI   calibration window            -> steps 6 + 9 type it and resolve cal reads
#   A2L             path to the canonical A2L     -> step 5b applies cal labels from it
#   TRACE_MAP_CALLS output csv path               -> step 10 traces map-lookup framework calls
#   RESOLVE_DISPATCH output csv path              -> step 10b resolves indirect-call jumptables
#   IMAGE_HI        end of image for coverage     (default LOADBASE + firmware size)
# ------------------------------------------------------------------------------------
set -euo pipefail

ECU_DIR="${ECU_DIR:?set ECU_DIR (or call via ecus/<ecu>/reproduce.sh)}"
HERE="$(cd "$ECU_DIR" && pwd)"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/.env.sh"
: "${GHIDRA_HOME:?set GHIDRA_HOME in .env.sh}"; : "${JAVA_HOME:?set JAVA_HOME in .env.sh}"

[ -f "$HERE/ecu.conf" ] || { echo "missing $HERE/ecu.conf"; exit 1; }
# Defaults BEFORE the conf so the conf can override them; arrays default to empty.
PROCESSOR="tricore:LE:32:tc176x"
MEMMAP=(); BASEREGS=(); CODE_RANGES=()
ALIAS_BASE=""; ALIAS_LEN=""; CAL_LO=""; CAL_HI=""; A2L=""; TRACE_MAP_CALLS=""; RESOLVE_DISPATCH=""
EXPECT_SHA="${EXPECT_SHA:-}"; IMAGE_HI=""
# shellcheck source=/dev/null
source "$HERE/ecu.conf"
: "${ECU_NAME:?ecu.conf must set ECU_NAME}"
: "${FIRMWARE:?ecu.conf must set FIRMWARE}"
: "${LOADBASE:?ecu.conf must set LOADBASE}"

BIN="$HERE/$FIRMWARE"
PROG="$(basename "$BIN")"
PROJ="$HERE/ghidra_proj"
SCRIPTS="$ROOT/core/ghidra"
HL="$GHIDRA_HOME/support/analyzeHeadless"
LOGS="$HERE/analysis/_logs"; mkdir -p "$LOGS" "$HERE/analysis"
ENTRIES="$HERE/analysis/function_entries.txt"
SYMS="$HERE/analysis/symbols_merged.csv"
MANIFEST="$HERE/analysis/decompiles_r.manifest.csv"

[ -f "$BIN" ] || { echo "missing $BIN (supply the firmware locally; it is gitignored)"; exit 1; }
if [ -n "$EXPECT_SHA" ]; then
  echo "$EXPECT_SHA  $BIN" | sha256sum -c - || { echo "firmware sha256 mismatch"; exit 1; }
fi
if [ -z "$IMAGE_HI" ]; then
  IMAGE_HI="$(printf '0x%x' $(( LOADBASE + $(stat -Lc %s "$BIN") )))"
fi

run() {  # run <logname> <analyzeHeadless args...>   -- per-step log, fail loudly with a tail
  local log="$LOGS/$1.log"; shift
  "$HL" "$@" > "$log" 2>&1 || { echo "FAILED -- see $log"; tail -20 "$log"; exit 1; }
}
say() { sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/$1.log" | grep -E "$2" | sed 's/^/    /' || true; }
skip() { echo "==> $1 SKIPPED: $2"; }

echo "=== reproduce $ECU_NAME  ($PROG -> $PROJ) ==="

echo "==> 1 import + auto-analyze (fresh project)"
rm -rf "$PROJ"; mkdir -p "$PROJ"
if [ ${#MEMMAP[@]} -gt 0 ]; then
  run 01_import "$PROJ" "$ECU_NAME" -import "$BIN" \
    -processor "$PROCESSOR" -loader BinaryLoader -loader-baseAddr "$LOADBASE" \
    -scriptPath "$SCRIPTS" -preScript MapMemory.java "${MEMMAP[@]}"
  say 01_import '^(alias|uninit|skip|MapMemory)'
else
  run 01_import "$PROJ" "$ECU_NAME" -import "$BIN" \
    -processor "$PROCESSOR" -loader BinaryLoader -loader-baseAddr "$LOADBASE"
fi

echo "==> 2 recover TriCore base-register init values -> analysis/basereg.log"
run 02_basereg "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
  -scriptPath "$SCRIPTS" -postScript FindBaseRegs.java
sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/02_basereg.log" > "$HERE/analysis/basereg.log"
say 02_basereg '^(scanned:|===|  a[0-9]+=0x)'

if [ ${#BASEREGS[@]} -gt 0 ]; then
  echo "==> 3 set base registers (${BASEREGS[*]}) + re-analyze"
  run 03_setbase "$PROJ" "$ECU_NAME" -process "$PROG" \
    -scriptPath "$SCRIPTS" -postScript SetBaseRegs.java "${BASEREGS[@]}"
  say 03_setbase '^(set a|re-analysis)'
else
  skip 3 "BASEREGS empty -- read analysis/basereg.log, then set it in ecu.conf"
fi

if [ -n "$ALIAS_BASE" ]; then
  echo "==> 3b canonicalize alias functions ($ALIAS_BASE twins -> their $LOADBASE address)"
  run 03b_canon "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript CanonicalizeAlias.java "$ALIAS_BASE" "$LOADBASE" "$ALIAS_LEN"
  say 03b_canon '^(CanonicalizeAlias:|  NOTE)'
else
  skip 3b "no ALIAS_BASE (image has no mapped non-cached alias)"
fi

if [ -f "$ENTRIES" ]; then
  echo "==> 4 recreate the full function set from the committed entry manifest"
  run 04_createfns "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript CreateFunctions.java "$ENTRIES"
  say 04_createfns '^CreateFunctions:'
else
  echo "==> 4 COLD START: no function_entries.txt -- seeding it from auto-analysis"
  run 04_exportfns "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript ExportFunctions.java "$ENTRIES"
  say 04_exportfns '^ExportFunctions:'
fi

if [ ${#CODE_RANGES[@]} -gt 0 ]; then
  echo "==> 4b claim orphan code (disassembled but in NO function) + re-export the manifest"
  # Auto-analysis disassembles code it reaches via jump/dispatch edges but does not always
  # create a function for it. Those bytes then produce no C and never appear in the decompile
  # manifest -- invisible loss. On MED17.1.1 that was 621 KB across 2149 functions.
  #
  # NOTE: deliberately NOT RecoverGapWalk.java. That walks UNDEFINED bytes and, over an image
  # whose erased sectors read as 0x00, disassembles erased flash into ~33k junk functions
  # (measured on MED17). Claiming code that is ALREADY disassembled is the safe half.
  for r in "${CODE_RANGES[@]}"; do
    run "04b_claim_${r/:/_}" "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
      -scriptPath "$SCRIPTS" -postScript ClaimOrphanCode.java "${r%:*}" "${r#*:}" \
      "$HERE/analysis/orphan_entries_${r/:/_}.txt"
    say "04b_claim_${r/:/_}" '^ClaimOrphanCode'
  done
  run 04c_reexport "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript ExportFunctions.java "$ENTRIES"
  say 04c_reexport '^ExportFunctions:'

  echo "==> 4d AUDIT: code reachable only through a function-pointer table (report only)"
  # A handler whose sole entry is a dispatch-table slot is invisible to every step above:
  # the table is raw data, so no reference exists, so ClaimOrphanCode/RecoverReferencedCode
  # never see it (the latter reports seeds=0 on this image while 325 computed call sites are
  # still unresolved). This reports candidates; it deliberately does NOT create them.
  #
  # Report-only ON PURPOSE. Measured on MED17.1.1: of 20 surviving candidates only 3 were real
  # code -- the rest were u16 axis tables, ROM constant-pool slots and an ASCII version string
  # that all pass the "looks like a code pointer" test. Auto-creating them would corrupt the
  # function set. Vet the list by hand, then add confirmed entries to function_entries.txt,
  # which is what makes step 4 create and step 7 decompile them on every future run.
  for r in "${CODE_RANGES[@]}"; do
    run "04d_ptraudit_${r/:/_}" "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
      -scriptPath "$SCRIPTS" -postScript RecoverPointerTargets.java "${r%:*}" "${r#*:}" -n
    sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/04d_ptraudit_${r/:/_}.log" \
      | grep -E '^(  would create|RecoverPointerTargets)' \
      > "$HERE/analysis/pointer_target_audit_${r/:/_}.txt" || true
    say "04d_ptraudit_${r/:/_}" '^RecoverPointerTargets'
  done
else
  skip 4b "no CODE_RANGES declared (orphan-code claim disabled)"
fi

if [ -f "$SYMS" ]; then
  echo "==> 5 apply recovered function names + comments"
  run 05_applysyms "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript ApplySymbols.java "$SYMS"
  say 05_applysyms '^ApplySymbols:'
else
  skip 5 "no analysis/symbols_merged.csv yet (nothing named on this ECU)"
fi

if [ -n "$A2L" ]; then
  echo "==> 5b apply calibration labels derived from the canonical A2L"
  A2L_SYMS="$(dirname "$HERE/$A2L")/a2l_symbols.csv"
  python3 "$ROOT/core/maps/a2l_to_symbols.py" "$HERE/$A2L" --out "$A2L_SYMS"
  run 05b_a2lsyms "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript ApplySymbols.java "$A2L_SYMS"
  say 05b_a2lsyms '^ApplySymbols:'
else
  skip 5b "no A2L declared for this ECU"
fi

if [ -n "$CAL_LO" ] && [ -n "$CAL_HI" ]; then
  echo "==> 6 data-type the calibration region $CAL_LO..$CAL_HI (keeps coverage honest)"
  run 06_markcal "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript MarkCalData.java "$CAL_LO" "$CAL_HI"
  say 06_markcal '^MarkCalData'
else
  skip 6 "cal window not pinned yet (set CAL_LO/CAL_HI in ecu.conf)"
fi

if [ -n "${COM_DESC_CB:-}" ]; then
  echo "==> 6b decode the COM signal-descriptor table -> bind signals to their RAM targets"
  # Must run BEFORE step 7 so the decompiles carry the bindings as comments.
  run 06b_combind "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript DecodeComBindings.java "$COM_DESC_CB" "${COM_DESC_MASK:-0x0000ffff}"
  say 06b_combind '^DecodeComBindings'
else
  skip 6b "COM_DESC_CB not pinned in ecu.conf (signal bindings stay opaque)"
fi

echo "==> 7 decompile every function + manifest (DERIVED WORK -- gitignored)"
# Clear first: the decompile dir otherwise accumulates stale .c across runs (alias twins from
# before canonicalization, functions from a reverted experiment), so the corpus on disk
# silently stops matching the manifest.
rm -rf "$HERE/analysis/decompiles_r"
run 07_decompile "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
  -scriptPath "$SCRIPTS" -postScript DecompileAll.java "$HERE/analysis/decompiles_r" "$ENTRIES"
say 07_decompile '^DecompileAll'

echo "==> 8 annotated disasm for EVERY fn without usable C (degraded|fail|absent)"
# Two disjoint failure buckets, both needing the disasm fallback:
#   degraded    -- decompiler completed but the body is compromised (bad/unmodeled instruction
#                  or truncated control flow). NOT the benign 'space' restart or the benign
#                  jumptable fall-back, both of which complete with full C.
#   fail/absent -- no .c at all (timeout/error), or the entry never became a live function.
# Driven by the manifest, so a function with no .c is never silently invisible.
awk -F, 'NR>1 && ($4=="degraded" || $4=="fail" || $4=="absent"){ sub(/^0x/,"",$1); print $1 }' "$MANIFEST" \
  | sort -u > "$HERE/analysis/degraded_fns.txt"
echo "    $(wc -l < "$HERE/analysis/degraded_fns.txt") functions need the disasm fallback"
run 08_disasm "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
  -scriptPath "$SCRIPTS" -postScript DumpDisasmFns.java \
  "$HERE/analysis/degraded_fns.txt" "$HERE/analysis/disasm_r"
# Pure-Python: recover return types the decompiler could not type, from disasm + caller use.
python3 "$ROOT/core/maps/recover_sigs.py" "$HERE/analysis" || true

if [ -n "$CAL_LO" ] && [ -n "$CAL_HI" ]; then
  echo "==> 9 resolve base-relative cal accesses -> analysis/cal_reads.csv"
  run 09_calreads "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript ResolveCalReads.java \
    "$HERE/analysis/cal_reads.csv" "--cal=$CAL_LO:$CAL_HI"
  say 09_calreads 'CALDONE'
else
  skip 9 "cal window not pinned yet"
fi

if [ -n "$TRACE_MAP_CALLS" ]; then
  echo "==> 10 trace map-lookup framework calls -> $TRACE_MAP_CALLS"
  run 10_tracemaps "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript TraceMapCalls.java "$HERE/$TRACE_MAP_CALLS"
  say 10_tracemaps '^TraceMapCalls'
else
  skip 10 "no TRACE_MAP_CALLS (map-lookup framework not identified on this ECU)"
fi

if [ -n "$RESOLVE_DISPATCH" ]; then
  echo "==> 10b resolve indirect-call jumptable targets -> $RESOLVE_DISPATCH"
  # Statically-resolvable subset only (const fn-ptr + const-base indexed tables); RAM-vtable /
  # trampoline dispatch needs EmulBoot. CSV only -- add --addrefs manually to create references.
  run 10b_dispatch "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript ResolveDispatchTables.java "$HERE/$RESOLVE_DISPATCH"
  say 10b_dispatch '^DISPATCHDONE'
else
  skip 10b "no RESOLVE_DISPATCH declared"
fi

echo "==> 11 byte-level coverage report -> analysis/coverage.log"
# The per-function "% decompiled cleanly" only counts functions Ghidra already found; bytes
# that never became a function are invisible to it. This measures the IMAGE: in-function vs
# orphan-disassembled vs data vs erased vs genuinely unaccounted.
CALARG=()
if [ -n "$CAL_LO" ] && [ -n "$CAL_HI" ]; then CALARG=("--cal=$CAL_LO:$CAL_HI"); fi
run 11_coverage "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
  -scriptPath "$SCRIPTS" -postScript CoverageStat.java "$LOADBASE" "$IMAGE_HI" "${CALARG[@]}"
sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/11_coverage.log" > "$HERE/analysis/coverage.log"
sed -n '/=== image/,/^$/p;/LIVE CONTENT/,/NOT accounted/p' "$HERE/analysis/coverage.log" | sed 's/^/    /'

echo "==> 11b indirect-branch audit -> analysis/indirect_branches.csv"
# Byte coverage and the per-function manifest both measure only what Ghidra already found.
# Neither can see a computed call whose target was never resolved -- that shows up as a clean
# 100% while a whole dispatch tree is missing. This walks every ji/calli and classifies it, so
# UNRESOLVED and OFF-IMAGE counts are visible on every run instead of being discovered by hand.
run 11b_indirect "$PROJ" "$ECU_NAME" -process "$PROG" -noanalysis \
  -scriptPath "$SCRIPTS" -postScript AuditIndirectBranches.java \
  "$HERE/analysis/indirect_branches.csv"
say 11b_indirect '^  (computed|UNRESOLVED|RESOLVED|OFF-IMAGE)'

echo
echo "done. labeled project in $PROJ ; decompiles in analysis/decompiles_r (regenerable)."
echo "      per-step logs in analysis/_logs/"
