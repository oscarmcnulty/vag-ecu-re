#!/usr/bin/env bash
# Rebuild the labeled MED17.1.1 Ghidra project + decompiles. Parameters live in ecu.conf;
# the pipeline itself is core/pipeline/reproduce.sh (shared with every other ECU pack).
set -euo pipefail
export ECU_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$ECU_DIR/../../core/pipeline/reproduce.sh"
