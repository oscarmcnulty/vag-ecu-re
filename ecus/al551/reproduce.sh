#!/usr/bin/env bash
# Rebuild the labeled AL551 (ZF 8HP TCU) Ghidra project + decompiles. Parameters in ecu.conf;
# the pipeline is core/pipeline/reproduce.sh (shared with every other ECU pack).
set -euo pipefail
export ECU_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$ECU_DIR/../../core/pipeline/reproduce.sh"
