#!/usr/bin/env bash
# Rebuild the labeled Audi B8/8R CAN gateway (J533, 8R0907468) Ghidra project + decompiles.
# Prereq: firmware/8R0907468_0060_plain.bin (regenerate from the .sgo with tools/sgo_gw_decode.py).
# NOTE: PROCESSOR is unset in ecu.conf until the arch sweep confirms it; until then the pipeline
# skips loudly (see docs/RE_findings.md "Architecture identification").
set -euo pipefail
export ECU_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$ECU_DIR/../../core/pipeline/reproduce.sh"
