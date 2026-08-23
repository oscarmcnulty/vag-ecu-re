#!/usr/bin/env bash
# Reproduce the labeled EPB (8K0907801N, HCS12X/S12X) Ghidra project from committed metadata
# ONLY: the raw flash blocks (gitignored; regenerate with ./extract.sh from the FRF) + the
# version-controlled analysis/symbols.csv. No derived/decompiled source is committed.
#
# S12X BANKED LOAD (see docs/RE_findings.md sec.2). Ghidra's HCS12X decompiler forms global
# addresses (0x400000 + PPAGE*0x4000 + off) for windowed (0x8000-0xBFFF) accesses, so the pages
# are loaded at those globals with PPAGE context set per page (EpbMap.java) -- otherwise every
# cross-page flow escapes to unmapped memory and bodies come out empty. Confirmed page map:
#   DB_4 = PPAGE 0xE0-0xE6  -> global 0x780000 (the -import block)
#   DB_6 = PPAGE 0xF8-0xFD  -> global 0x7e0000 (loaded by EpbMap)
#   fixed-low page 0xFD (global 0x7f4000) also visible at local 0x4000-0x7FFF (byte-mapped alias)
#   IO 0x0-0x3FF (volatile), RAM 0x400-0x3FFF. Vector page 0xFF = bootloader, absent.
# Canonical symbol address = the GLOBAL address above (DB_4 fn at combined off O -> 0x780000+O;
# DB_6 -> 0x7e0000+(O-0x1c000); fixed-low tables labelled at their local 0x4xxx alias).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
source "$ROOT/.env.sh"; : "${GHIDRA_HOME:?}"; : "${JAVA_HOME:?}"
HL="$GHIDRA_HOME/support/analyzeHeadless"; CORE="$ROOT/core/ghidra"; EPBS="$HERE/ghidra_scripts"
FW="$HERE/firmware"; AN="$HERE/analysis"; LOGS="$AN/_logs"; PROJ="$HERE/ghidra_proj"
DB4="$FW/DB_4_01.bin"; DB6="$FW/DB_6_02.bin"; NAME="EPB_8K0907801N"; SYMS="$AN/symbols.csv"
ENTRIES="$AN/function_entries.txt"; DEC="$AN/decompiles_named"
mkdir -p "$LOGS"
[ -f "$DB4" ] && [ -f "$DB6" ] || { echo "missing $DB4 / $DB6 -- run ./extract.sh (needs the gitignored FRF)"; exit 1; }
run(){ local l="$LOGS/$1.log"; shift; "$HL" "$@" >"$l" 2>&1 || { echo "FAILED $l"; tail -25 "$l"; exit 1; }; }
say(){ sed 's/.*java> //;s/ (GhidraScript).*//' "$LOGS/$1.log" | grep -E "$2" | sed 's/^/    /' || true; }

echo "==> 1 import DB_4 @0x780000 + EpbMap (DB_6 + IO/RAM/alias + PPAGE context)"
rm -rf "$PROJ"; mkdir -p "$PROJ"
run 01_import "$PROJ" "$NAME" -import "$DB4" -processor "HCS-12X:BE:24:default" \
  -loader BinaryLoader -loader-baseAddr 0x780000 -noanalysis \
  -scriptPath "$EPBS" -preScript EpbMap.java "$DB6"
say 01_import '^EpbMap'

echo "==> 2 seed disassembly (no reset vector -> linear sweep, PPAGE context already set)"
run 02_seed "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$EPBS" -postScript SeedSweep.java
say 02_seed '^SeedSweep'

echo "==> 2b auto-analyze (PPAGE context set -> cross-page flows + call graph resolve)"
run 02b_analyze "$PROJ" "$NAME" -process "$(basename "$DB4")"
echo "    analysis complete"

echo "==> 2c mark data-table regions (fixed-low CAN matrix/config tables -> data, not junk fns)"
run 02c_markdata "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis   -scriptPath "$EPBS" -postScript MarkDataRegions.java 0x7f4800:0x7f5c00 0x7f6b00:0x7f6e00 0x7f7f00:0x7f8000
say 02c_markdata '^MarkDataRegions'

echo "==> 2d claim orphan code (disassembled-but-function-less) over both flash blocks"
for rg in 0x780000:0x79c000 0x7e0000:0x7f8000; do
  run "02d_orphan_${rg%%:*}" "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis     -scriptPath "$CORE" -postScript ClaimOrphanCode.java "${rg%:*}" "${rg#*:}" "$AN/orphan_${rg%%:*}.txt"
  say "02d_orphan_${rg%%:*}" '^ClaimOrphanCode'
done

echo "==> 2d2 resolve S12X fn-pointer tables (RTE ports / dispatch) -> functions + refs"
run 02d2_fnptr "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$EPBS" -postScript ResolveFnPtrTables.java
say 02d2_fnptr '^ResolveFnPtrTables'

echo "==> 2d3 resolve indexed-dispatch tables (COM/OS/handler) -> functions + call refs"
run 02d3_dispatch "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$EPBS" -postScript EpbResolveDispatch.java
say 02d3_dispatch '^EpbResolveDispatch'

echo "==> 2e force-create functions at every named entry (computed-call/jump targets included)"
run 02e_forcefns "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$EPBS" -postScript ForceFns.java "$SYMS"
say 02e_forcefns '^ForceFns'

echo "==> 3 apply symbols (create+name confirmed functions, plate comments, reg/RAM labels)"
run 03_syms "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$CORE" -postScript ApplySymbols.java "$SYMS"
say 03_syms '^ApplySymbols'

echo "==> 4 export function-entry manifest"
run 04_export "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$CORE" -postScript ExportFunctions.java "$ENTRIES"
say 04_export '^ExportFunctions'

echo "==> 5 decompile the named (confirmed) functions -> analysis/decompiles_named (DERIVED, gitignored)"
rm -rf "$DEC"
awk -F, 'NR>1 && $3=="FUNCTION"{print $1}' "$SYMS" > "$AN/named_fns.txt"
run 05_decompile "$PROJ" "$NAME" -process "$(basename "$DB4")" -noanalysis \
  -scriptPath "$EPBS" -postScript DecompileNamed.java "$DEC" "$AN/named_fns.txt"
say 05_decompile '^DecompileNamed'
echo "done. project=$PROJ  decompiles=$DEC"
